/**
 * Media, behind one seam.
 *
 * `CallAudioLike` is what the call hook talks to; `CallAudio` is the Web Audio answer to it. The
 * split exists so `useCall` is testable in jsdom, where there is no `AudioContext`, no
 * `getUserMedia` and nothing to interrupt — and so a future Linux or macOS backend can arrive
 * without touching the state machine.
 */
import { encodePcm } from "./protocol.ts";
import { jpegFromVideo } from "./frames.ts";

export interface CallAudioLike {
  startMic(onPacket: (pcm: string) => void, onLevel: (level: number) => void): Promise<void>;
  /**
   * Register — or with `null`, drop — the listener for what is coming *out* of the speakers.
   *
   * Separate from `startMic` because playback has no start the caller sees: sentences arrive when the
   * engine sends them. One listener, one pump, one number per frame; the mouth that reads it is the
   * stage's, and a call with no stage mounted simply never registers one.
   */
  onPlaybackLevel(onLevel: ((level: number) => void) | null): void;
  startCamera(video: HTMLVideoElement | null): Promise<void>;
  stopCamera(): void;
  frame(): string | null;
  play(pcm: string): Promise<void>;
  stopPlayback(): void;
  setMuted(muted: boolean): void;
  stopAll(): void;
}

const MIC: MediaStreamConstraints = {
  audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
  video: false,
};

/** RMS at which a level tick counts as "someone is talking over the answer". */
const BARGE_LEVEL = 0.04;
export const LEVEL_WINDOW = 1024;

function unbase64(text: string): Uint8Array {
  const binary = atob(text);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

export class CallAudio implements CallAudioLike {
  private capture: AudioContext | null = null;
  private micStream: MediaStream | null = null;
  private analyser: AnalyserNode | null = null;
  private meter: number | null = null;
  private meterHandle: number | null = null;
  private ticks = 0;
  private onLevel: ((level: number) => void) | null = null;
  private muted = false;

  private speaker: AudioContext | null = null;
  /** The one analyser the speakers feed, so every sentence is measured on its way out. */
  private playback: AnalyserNode | null = null;
  private playbackHandle: number | null = null;
  private playbackListener: ((level: number) => void) | null = null;
  private queue: Promise<void> = Promise.resolve();
  private sources = new Set<AudioBufferSourceNode>();
  /**
   * Bumped by `stopPlayback`. Sentences are queued as promises, so without a generation the ones
   * still waiting would start playing right after an interruption — the user spoke over the answer
   * and the rest of it arrives anyway.
   */
  private epoch = 0;

  private videoEl: HTMLVideoElement | null = null;
  private cameraStream: MediaStream | null = null;
  private canvas: HTMLCanvasElement | null = null;

  async startMic(onPacket: (pcm: string) => void, onLevel: (level: number) => void): Promise<void> {
    const stream = await navigator.mediaDevices.getUserMedia(MIC);
    if (!stream.getAudioTracks().length) throw new Error("no microphone is available");
    const context = new AudioContext({ sampleRate: 16000 });
    await context.audioWorklet.addModule(new URL("./capture-worklet.js", import.meta.url));
    const source = context.createMediaStreamSource(stream);
    const node = new AudioWorkletNode(context, "kira-capture");
    node.port.onmessage = (event: MessageEvent<Int16Array>) => {
      if (!this.muted) onPacket(encodePcm(event.data));
    };
    // A zero-gain sink keeps the worklet pulled without ever leaking mic sound to the speakers.
    const sink = context.createGain();
    sink.gain.value = 0;
    source.connect(node);
    node.connect(sink);
    sink.connect(context.destination);

    const analyser = context.createAnalyser();
    analyser.fftSize = LEVEL_WINDOW;
    source.connect(analyser);

    this.capture = context;
    this.micStream = stream;
    this.analyser = analyser;
    this.onLevel = onLevel;
    this.pumpMeter();
  }

  private pumpMeter() {
    const analyser = this.analyser;
    if (!analyser) return;
    const data = new Float32Array(analyser.fftSize);
    const tick = () => {
      if (!this.analyser) return;
      this.analyser.getFloatTimeDomainData(data);
      let total = 0;
      for (const sample of data) total += sample * sample;
      const rms = Math.sqrt(total / data.length);
      // Report every crossing of the barge bar, and otherwise throttle so React re-renders the
      // level meter at ~15 fps instead of 60.
      const hot = rms >= BARGE_LEVEL;
      const wasHot = (this.meter ?? 0) >= BARGE_LEVEL;
      this.meter = rms;
      if (hot !== wasHot || this.ticks++ % 4 === 0) this.onLevel?.(rms);
      this.meterHandle = requestAnimationFrame(tick);
    };
    this.meterHandle = requestAnimationFrame(tick);
  }

  async startCamera(video: HTMLVideoElement | null): Promise<void> {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: { width: 640, height: 480 } });
    if (!video) {
      for (const track of stream.getTracks()) track.stop();
      throw new Error("no video element to attach the camera to");
    }
    this.videoEl = video;
    this.cameraStream = stream;
    video.srcObject = stream;
    video.hidden = false;
    await video.play();
  }

  stopCamera(): void {
    for (const track of this.cameraStream?.getTracks() ?? []) track.stop();
    this.cameraStream = null;
    if (this.videoEl) this.videoEl.srcObject = null;
  }

  frame(): string | null {
    if (!this.cameraStream || !this.videoEl) return null;
    this.canvas ??= document.createElement("canvas");
    return jpegFromVideo(this.videoEl, this.canvas);
  }

  play(pcm: string): Promise<void> {
    const generation = this.epoch;
    const run = this.queue.then(() => (generation === this.epoch ? this.speak(pcm) : undefined));
    // A decode failure must not poison the queue: later sentences still play.
    this.queue = run.catch(() => undefined);
    return run;
  }

  private async speak(pcm: string): Promise<void> {
    const context = this.speaker ?? (this.speaker = new AudioContext());
    if (context.state === "suspended") await context.resume();
    const bytes = unbase64(pcm);
    // `decodeAudioData` wants an ArrayBuffer it can own; the view is already its own buffer.
    const buffer = await context.decodeAudioData(bytes.buffer as ArrayBuffer);
    const source = context.createBufferSource();
    source.buffer = buffer;
    const analyser = this.playback ?? this.measure(context);
    source.connect(analyser);
    const done = new Promise<void>((resolve) => {
      source.onended = () => {
        this.sources.delete(source);
        resolve();
      };
    });
    this.sources.add(source);
    source.start();
    this.pumpPlayback();
    return done;
  }

  /**
   * The analyser between every sentence and the speakers.
   *
   * In the graph rather than beside it, because a tap that is not on the signal path measures whatever
   * the browser feels like feeding it. One node for the whole context: sentences queue back to back and
   * a mouth does not care which buffer it is chewing.
   */
  private measure(context: AudioContext): AnalyserNode {
    const analyser = context.createAnalyser();
    analyser.fftSize = LEVEL_WINDOW;
    analyser.connect(context.destination);
    this.playback = analyser;
    return analyser;
  }

  /**
   * Report the loudness of the answer, one reading per frame, while an answer is playing.
   *
   * The pump stops itself when nothing is left in `sources` — an orphan `requestAnimationFrame` is both a
   * battery drain and a mouth that never closes — and it only runs at all when somebody registered, so a
   * call with no stage mounted pays for no measurement.
   */
  private pumpPlayback() {
    const analyser = this.playback;
    if (!analyser || this.playbackListener === null || this.playbackHandle !== null) return;
    const data = new Float32Array(analyser.fftSize);
    const tick = () => {
      if (!this.playback || this.sources.size === 0 || this.playbackListener === null) {
        this.stopPump();
        this.playbackListener?.(0);
        return;
      }
      this.playback.getFloatTimeDomainData(data);
      let total = 0;
      for (const sample of data) total += sample * sample;
      this.playbackListener(Math.sqrt(total / data.length));
      this.playbackHandle = requestAnimationFrame(tick);
    };
    this.playbackHandle = requestAnimationFrame(tick);
  }

  private stopPump() {
    if (this.playbackHandle !== null) cancelAnimationFrame(this.playbackHandle);
    this.playbackHandle = null;
  }

  onPlaybackLevel(onLevel: ((level: number) => void) | null): void {
    this.playbackListener = onLevel;
    if (onLevel === null) this.stopPump();
    else this.pumpPlayback();
  }

  stopPlayback(): void {
    this.epoch += 1;
    for (const source of this.sources) {
      try {
        source.stop();
      } catch {
        this.sources.delete(source);
      }
    }
    this.sources.clear();
    // Silence, said out loud: a barge-in that leaves the last viseme open looks like Kira went on talking.
    if (this.playbackHandle !== null) {
      this.stopPump();
      this.playbackListener?.(0);
    }
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
    for (const track of this.micStream?.getAudioTracks() ?? []) track.enabled = !muted;
  }

  stopAll(): void {
    if (this.meterHandle !== null) cancelAnimationFrame(this.meterHandle);
    this.meterHandle = null;
    this.onLevel = null;
    this.analyser = null;
    this.stopPump();
    this.stopPlayback();
    this.playbackListener = null;
    this.playback = null;
    this.stopCamera();
    for (const track of this.micStream?.getTracks() ?? []) track.stop();
    this.micStream = null;
    void this.capture?.close().catch(() => undefined);
    this.capture = null;
    void this.speaker?.close().catch(() => undefined);
    this.speaker = null;
    this.queue = Promise.resolve();
  }
}
