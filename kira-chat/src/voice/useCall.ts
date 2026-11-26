/**
 * The call's state machine, on the browser's side of `/v1/voice`.
 *
 * Two things are deliberately not here. Audio never passes through React state — a 100 ms PCM packet
 * re-rendering a component is how a call stutters — and interruption is decided locally: the engine is
 * deaf while it thinks or speaks, so the only party that knows the user talked over the answer is the
 * one that played it. `deps` replaces the socket factory and the whole media stack, which is what lets
 * the hook be tested without `AudioContext` or `getUserMedia`.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import type { ChainRecord, Mode, VoiceStatus } from "../contracts.ts";
import { parseEvent, voiceUrl } from "./protocol.ts";
import type { CallCommand, CallEvent } from "./protocol.ts";
import { FRAME_INTERVAL_MS, frameDue } from "./frames.ts";
import { CallAudio } from "./audio.ts";
import type { CallAudioLike } from "./audio.ts";

export type CallPhase = "idle" | "connecting" | "listening" | "thinking" | "speaking" | "ended" | "error";

export interface CallOptions {
  baseUrl: string;
  token: string;
  model: string;
  mode: Mode;
}

export interface CallDeps {
  connect?: (url: string) => WebSocket;
  audio?: CallAudioLike;
}

export interface CallEntry {
  id: number;
  role: "user" | "assistant";
  text: string;
}

export interface CallState {
  phase: CallPhase;
  voice: VoiceStatus | null;
  entries: CallEntry[];
  live: string;
  error: string | null;
  muted: boolean;
  camera: boolean;
  level: number;
  /**
   * How loud the answer is, right now, for the avatar's mouth to read every frame.
   *
   * A ref rather than state on purpose: the stage asks for it 60 times a second, and a React render per
   * frame is how a call stutters. `useCall` keeps it current; nobody re-renders on it.
   */
  playbackLevel: RefObject<number>;
  sessionId: string | null;
  chain: ChainRecord[];
  videoRef: RefObject<HTMLVideoElement | null>;
  start(): Promise<void>;
  end(): void;
  toggleMute(): void;
  toggleCamera(): Promise<void>;
  look(): void;
  say(text: string): void;
}

const SOCKET_OPEN = 1;
const BARGE_RMS = 0.04;
const BARGE_DEBOUNCE_MS = 700;
/**
 * RMS to display units.
 *
 * A talking voice sits around 0.05-0.3 RMS, so the raw number would light a meter up to a third of its
 * width and walk a mouth through two of its five shapes. Both the mic bar and the avatar's jaw use this
 * same gain, which is what makes them comparable on screen.
 */
const LEVEL_GAIN = 4;
const LOOK_PROMPT = "what do you see?";

export function useCall(options: CallOptions, deps: CallDeps = {}): CallState {
  const [phase, setPhase] = useState<CallPhase>("idle");
  const [voice, setVoice] = useState<VoiceStatus | null>(null);
  const [entries, setEntries] = useState<CallEntry[]>([]);
  const [live, setLive] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [muted, setMuted] = useState(false);
  const [camera, setCamera] = useState(false);
  const [level, setLevel] = useState(0);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [chain, setChain] = useState<ChainRecord[]>([]);

  const socket = useRef<WebSocket | null>(null);
  const audio = useRef<CallAudioLike | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const playbackLevel = useRef(0);
  const liveRef = useRef("");
  const nextId = useRef(1);
  const bargeAt = useRef(0);
  const lastFrame = useRef(0);
  const playing = useRef(0);
  const waitingTurnDone = useRef(false);
  const timer = useRef<number | null>(null);
  const phaseRef = useRef<CallPhase>("idle");
  const cameraRef = useRef(false);

  const config = useRef(options);
  config.current = options;
  const seams = useRef(deps);
  seams.current = deps;

  phaseRef.current = phase;
  cameraRef.current = camera;

  const media = () => {
    if (!audio.current) audio.current = seams.current.audio ?? new CallAudio();
    return audio.current;
  };

  const send = useCallback((command: CallCommand) => {
    const active = socket.current;
    if (active && active.readyState === SOCKET_OPEN) active.send(JSON.stringify(command));
  }, []);

  const push = useCallback((role: CallEntry["role"], text: string) => {
    if (!text.trim()) return;
    setEntries((list) => [...list, { id: nextId.current++, role, text }]);
  }, []);

  const speak = useCallback(async (pcm: string) => {
    playing.current += 1;
    try {
      await media().play(pcm);
    } finally {
      playing.current = Math.max(0, playing.current - 1);
      // A turn is only over when the audio that answered it is: `turn_done` arrives while the last
      // sentence is still playing, and going back to listening then would cut the answer short.
      if (playing.current === 0 && waitingTurnDone.current) {
        waitingTurnDone.current = false;
        setPhase("listening");
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const barged = useCallback(() => {
    bargeAt.current = Date.now();
    playing.current = 0;
    waitingTurnDone.current = false;
    media().stopPlayback();
    send({ type: "barge" });
    setPhase("listening");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [send]);

  const heard = useCallback((rms: number) => {
    setLevel(Math.min(1, rms * LEVEL_GAIN));
    const now = phaseRef.current;
    if (rms > BARGE_RMS && (now === "thinking" || now === "speaking") && Date.now() - bargeAt.current > BARGE_DEBOUNCE_MS) {
      barged();
    }
  }, [barged]);

  /**
   * The answer's loudness, written where the stage reads it.
   *
   * No state, no render: a mouth is a 60 Hz thing and the only consumer already runs at 60 Hz. The audio
   * module reports 0 the moment the sentence ends or the user talks over it, so nobody has to guess here
   * when the jaw should let go.
   */
  const spoken = useCallback((rms: number) => {
    playbackLevel.current = Math.min(1, rms * LEVEL_GAIN);
  }, []);

  const handle = useCallback((event: CallEvent) => {
    switch (event.type) {
      case "ready":
        setVoice(event.voice);
        setSessionId(event.session_id);
        setPhase("listening");
        break;
      case "speech_start":
        setPhase("listening");
        break;
      case "speech_end":
        if (!event.discarded) setPhase("thinking");
        break;
      case "transcript":
        if (event.final) {
          push("user", event.text);
          setPhase("thinking");
        }
        break;
      case "thinking":
        setPhase("thinking");
        break;
      case "answer_delta":
        liveRef.current += event.text;
        setLive(liveRef.current);
        setPhase("speaking");
        break;
      case "audio_out":
        void speak(event.pcm);
        break;
      case "turn_done": {
        push("assistant", liveRef.current);
        liveRef.current = "";
        setLive("");
        setChain(event.chain);
        setSessionId(event.session_id);
        if (playing.current > 0) waitingTurnDone.current = true;
        else setPhase("listening");
        break;
      }
      case "cancelled":
        liveRef.current = "";
        setLive("");
        playing.current = 0;
        waitingTurnDone.current = false;
        setPhase("listening");
        break;
      case "error":
        setError(`${event.code}: ${event.message}`);
        break;
    }
  }, [push, speak]);

  const stopTimers = useCallback(() => {
    if (timer.current !== null) {
      clearInterval(timer.current);
      timer.current = null;
    }
  }, []);

  const tick = useCallback(() => {
    if (!cameraRef.current || phaseRef.current === "idle" || phaseRef.current === "ended") return;
    if (!frameDue(lastFrame.current, Date.now(), document.hidden, FRAME_INTERVAL_MS)) return;
    const jpeg = media().frame();
    if (!jpeg) return;
    lastFrame.current = Date.now();
    send({ type: "frame", jpeg, mime: "image/jpeg" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [send]);

  const start = useCallback(async () => {
    const now = phaseRef.current;
    if (now === "connecting" || now === "listening" || now === "thinking" || now === "speaking") return;
    setError(null);
    setPhase("connecting");
    const url = voiceUrl(config.current.baseUrl);
    const active = (seams.current.connect ?? ((target: string) => new WebSocket(target)))(url);
    socket.current = active;
    active.onopen = () => {
      send({
        type: "hello",
        token: config.current.token,
        model: config.current.model || null,
        mode: config.current.mode || null,
        session_id: null,
      });
      void media()
        .startMic((pcm) => send({ type: "audio", pcm }), heard)
        .catch((reason: unknown) => {
          // A refused mic is a message, not an end: the call keeps its socket, and a typed turn
          // still works on a machine with no microphone at all.
          setError(reason instanceof Error ? reason.message : String(reason));
        });
      // Registered on the media stack, not per sentence: the answer arrives when the engine sends it, and
      // a mouth wants the whole run of them. A refused microphone changes nothing here — the listener is
      // not part of the microphone. Setting it again is a no-op while a pump is already running.
      media().onPlaybackLevel(spoken);
    };
    active.onmessage = (message: MessageEvent) => {
      const event = parseEvent(message.data);
      if (event) handle(event);
    };
    active.onerror = () => {
      if (phaseRef.current !== "ended") setError("the voice connection dropped; start the call again");
    };
    active.onclose = () => {
      stopTimers();
      if (phaseRef.current !== "ended" && phaseRef.current !== "idle") setPhase("error");
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handle, heard, send, spoken, stopTimers]);

  const end = useCallback(() => {
    stopTimers();
    send({ type: "close" });
    media().onPlaybackLevel(null);
    media().stopAll();
    playbackLevel.current = 0;
    const active = socket.current;
    socket.current = null;
    if (active && active.readyState === SOCKET_OPEN) {
      active.onclose = null;
      active.close();
    }
    setCamera(false);
    setMuted(false);
    setLevel(0);
    setPhase("ended");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [send, stopTimers]);

  const toggleMute = useCallback(() => {
    const next = !muted;
    setMuted(next);
    media().setMuted(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [muted]);

  const toggleCamera = useCallback(async () => {
    if (camera) {
      media().stopCamera();
      setCamera(false);
      stopTimers();
      return;
    }
    try {
      await media().startCamera(videoRef.current);
      setCamera(true);
      lastFrame.current = 0;
      stopTimers();
      timer.current = window.setInterval(tick, 1000);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [camera, stopTimers, tick]);

  const look = useCallback(() => {
    const jpeg = media().frame();
    if (jpeg) {
      lastFrame.current = Date.now();
      send({ type: "frame", jpeg, mime: "image/jpeg" });
    }
    send({ type: "text", text: LOOK_PROMPT });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [send]);

  const say = useCallback((text: string) => send({ type: "text", text }), [send]);

  useEffect(() => () => {
    stopTimers();
    audio.current?.onPlaybackLevel(null);
    audio.current?.stopAll();
    socket.current?.close();
  }, [stopTimers]);

  return { phase, voice, entries, live, error, muted, camera, level, playbackLevel, sessionId, chain, videoRef, start, end, toggleMute, toggleCamera, look, say };
}
