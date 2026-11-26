import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CallAudio } from "./audio.ts";

/**
 * A Web Audio graph you can read back.
 *
 * The claim under test is a *shape* — an `AnalyserNode` sits between the buffer source and the
 * destination — and no assertion about numbers can catch the shape being wrong. So every node records
 * what it was connected to, and the fake context hands out the same objects a real one would.
 */
class FakeNode {
  connections: FakeNode[] = [];
  fftSize = 0;
  /** what `getFloatTimeDomainData` copies out; the test sets the amplitude this "audio" has */
  samples: number[] = [];
  connect(target: FakeNode) {
    this.connections.push(target);
  }
  getFloatTimeDomainData(out: Float32Array) {
    for (let at = 0; at < out.length; at += 1) out[at] = this.samples[at % (this.samples.length || 1)] ?? 0;
  }
}

class FakeSource extends FakeNode {
  buffer: unknown = null;
  started = false;
  onended: (() => void) | null = null;
  start() {
    this.started = true;
  }
  /** An interrupted source ends right now — `onended` is the only notice the player gets. */
  stop() {
    this.onended?.();
  }
}

class FakeContext {
  state = "running";
  destination = new FakeNode();
  analysers: FakeNode[] = [];
  sources: FakeSource[] = [];
  closed = 0;
  createAnalyser(): FakeNode {
    const node = new FakeNode();
    this.analysers.push(node);
    return node;
  }
  createBufferSource(): FakeSource {
    const node = new FakeSource();
    this.sources.push(node);
    return node;
  }
  decodeAudioData(bytes: ArrayBuffer) {
    return Promise.resolve({ bytes });
  }
  resume() {
    return Promise.resolve();
  }
  close() {
    this.closed += 1;
    return Promise.resolve();
  }
}

let context: FakeContext;
let audio: CallAudio;
let levels: number[];

beforeEach(() => {
  context = new FakeContext();
  levels = [];
  // `CallAudio` reaches for the global, exactly as it does on a page.
  vi.stubGlobal("AudioContext", function kiraAudioContext() {
    return context;
  });
  vi.useFakeTimers();
  audio = new CallAudio();
  audio.onPlaybackLevel((level) => levels.push(level));
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

/** The one analyser the player built — the tests fail loudly if there is not exactly one. */
function analyser(): FakeNode {
  expect(context.analysers, "the player should hold exactly one analyser for the speakers").toHaveLength(1);
  return context.analysers[0];
}

/**
 * Send a sentence and let it get as far as being audible.
 *
 * Deliberately not awaited to completion: `play()` resolves when the *buffer* ends, and a real call
 * holds it open for the whole sentence. Everything here finishes it with `end()` instead.
 */
async function say(amplitude: number, at = 0) {
  void audio.play("aGVsbG8=");
  await vi.advanceTimersByTimeAsync(5);
  const node = analyser();
  node.samples = amplitude > 0 ? new Array(node.fftSize).fill(amplitude) : [];
  await vi.advanceTimersByTimeAsync(16);
  expect(context.sources[at].started, "the sentence never reached the speakers").toBe(true);
}

/** The buffer ran out. */
async function end(at = 0) {
  context.sources[at].onended?.();
  await vi.advanceTimersByTimeAsync(16);
}

describe("the playback meter's graph", () => {
  it("puts the analyser between the sentence and the speakers", async () => {
    await say(0.2);
    expect(context.sources[0].connections).toContain(analyser());
    expect(analyser().connections).toContain(context.destination);
    expect(analyser().fftSize).toBeGreaterThan(0);
    await end();
  });

  it("is built whether or not anyone is listening to it", async () => {
    // A call with no stage mounted must not acquire a second job — be measured — but the graph is the
    // graph, and it is not there to be conditional.
    audio.onPlaybackLevel(null);
    levels = [];
    await say(0.2);
    expect(context.sources[0].connections).toContain(analyser());
    expect(levels).toEqual([]);
    await end();
  });
});

describe("the playback meter's numbers", () => {
  it("reports what is coming out of the speakers, not what the microphone hears", async () => {
    await say(0.25);
    expect(levels.at(-1)).toBeCloseTo(0.25, 6);
    await end();
  });

  it("closes the mouth and stops the loop the sentence ends", async () => {
    await say(0.3);
    await end();
    expect(levels.at(-1)).toBe(0);

    // And nothing is left running: a pump with no audio in it is an orphan rAF, forever.
    const settled = levels.length;
    analyser().samples = new Array(analyser().fftSize).fill(0.9);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(levels.length).toBe(settled);
  });

  it("reports silence the moment the user talks over the answer", async () => {
    await say(0.4);
    audio.stopPlayback();
    expect(levels.at(-1)).toBe(0);
    const settled = levels.length;
    await vi.advanceTimersByTimeAsync(10_000);
    expect(levels.length).toBe(settled);
  });

  it("keeps one pump across queued sentences", async () => {
    void audio.play("aGVsbG8=");
    void audio.play("aGVsbG8=");
    await vi.advanceTimersByTimeAsync(5);
    analyser().samples = new Array(analyser().fftSize).fill(0.1);
    await vi.advanceTimersByTimeAsync(16);
    // The queue runs the second sentence only after the first has ended.
    expect(context.sources[0].started).toBe(true);
    expect(context.sources[1]).toBeUndefined();

    await end();
    await vi.advanceTimersByTimeAsync(5);
    expect(context.sources[1].started).toBe(true);
    expect(context.analysers).toHaveLength(1);
    expect(levels.length).toBeGreaterThan(1);

    await end(1);
    expect(levels.at(-1)).toBe(0);
  });

  it("stops with the call and takes the analysis with it", async () => {
    await say(0.2);
    expect(levels.length).toBeGreaterThan(0);
    audio.stopAll();
    expect(context.closed).toBe(1);
    const settled = levels.length;
    await vi.advanceTimersByTimeAsync(10_000);
    expect(levels.length).toBe(settled);
  });

  it("starts again when a listener arrives after the sentence did", async () => {
    // The stage mounts while Kira is already mid-answer, which is the normal case: `#/call` renders the
    // face as soon as a character is on it, and the audio started before the user pressed start.
    audio.onPlaybackLevel(null);
    levels = [];
    await say(0.2);
    expect(levels).toEqual([]);
    const late: number[] = [];
    audio.onPlaybackLevel((level) => late.push(level));
    await vi.advanceTimersByTimeAsync(16);
    expect(late.at(-1)).toBeCloseTo(0.2, 6);
    await end();
    expect(late.at(-1)).toBe(0);
  });
});
