/**
 * The face on the screen: one character, loaded, drawn, and moving.
 *
 * Everything that needs a GPU or an image decoder arrives as a seam (`StageSeams`), which is the same
 * bargain `load.ts` and `useCall.ts` made: the suite renders this component in jsdom with fakes and
 * proves the clock, the mouth, the mood and the cleanup, while the page passes the real three.js answers
 * from `browser.ts`. Nothing here constructs a `WebGLRenderer` by hand.
 *
 * Two rules hold it together.
 *
 * **One body, one loop.** The character is loaded when it is asked for and disposed when it is replaced or
 * the pane goes away — including the case where the load finishes *after* the unmount, which a call that
 * ends mid-answer really does hit.
 *
 * **Silence is a value.** The mouth reads `playbackLevel`, and the audio module reports 0 when a sentence
 * ends or the user talks over it, so nothing here has to decide when Kira stopped speaking.
 */
import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import type { CharacterProfile } from "../contracts.ts";
import { loadCharacter } from "./load.ts";
import type { LoadedCharacter, MeshSource, StageHost } from "./load.ts";
import { MOOD_KEYS } from "./pmx.ts";
import { createStage } from "./stage.ts";
import type { Mood, Stage, StageRenderer } from "./stage.ts";
import { STAGE_HEIGHT, STAGE_WIDTH, browserStageHost, createCanvasRenderer } from "./browser.ts";

/** What this component cannot do itself, so the caller owns it. */
export interface StageSeams {
  load: (source: MeshSource, profile: CharacterProfile, host: StageHost) => Promise<LoadedCharacter>;
  host: StageHost;
  /** null means this window has no 3D, which is a fact to show rather than an error to throw. */
  renderer: (canvas: HTMLCanvasElement) => StageRenderer | null;
}

export const browserSeams: StageSeams = { load: loadCharacter, host: browserStageHost, renderer: createCanvasRenderer };

type Status = "loading" | "drawing" | "no-3d" | "failed";

/** The four moods, in the words a user picks them with. The morph names are the model's. */
const MOOD_LABEL: Record<Mood, string> = { 笑い: "happy", 怒り: "stern", 悲しむ: "sad", びっくり: "surprised" };

function messageOf(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

export function AvatarStage({
  source,
  profile,
  playbackLevel,
  seams = browserSeams,
  moods = true,
}: {
  source: MeshSource;
  profile: CharacterProfile;
  playbackLevel: RefObject<number>;
  seams?: StageSeams;
  /** False for a window too small to show the row: an invisible button that still moves the face is a trap. */
  moods?: boolean;
}) {
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const stage = useRef<Stage | null>(null);
  const mood = useRef<Mood | null>(null);
  const pointer = useRef<{ x: number; y: number } | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  const [notes, setNotes] = useState<string[]>([]);
  const [picked, setPicked] = useState<Mood | null>(null);

  useEffect(() => {
    let cancelled = false;
    let live: Stage | null = null;
    let frame = 0;
    setStatus("loading");
    setNotes([]);

    void (async () => {
      let loaded: LoadedCharacter;
      try {
        loaded = await seams.load(source, profile, seams.host);
      } catch (reason) {
        if (!cancelled) {
          setNotes([messageOf(reason)]);
          setStatus("failed");
        }
        return;
      }
      // The pane moved on — a route change, a new pick, an ended call. The bytes are here, and they go
      // straight back, because a body nobody is drawing is 45 MB of GPU held for nothing.
      if (cancelled) {
        loaded.dispose();
        return;
      }
      const host = canvas.current ? seams.renderer(canvas.current) : null;
      if (host === null) {
        loaded.dispose();
        setStatus("no-3d");
        return;
      }
      const rig = createStage(loaded, host);
      rig.setMood(mood.current);
      live = rig;
      stage.current = rig;
      setNotes([...loaded.findings, ...rig.findings]);
      setStatus("drawing");

      // The frame's own clock, not a fresh `performance.now()` read: the timestamp the browser hands a
      // `requestAnimationFrame` callback is the one every other animation on the page agrees with, and it
      // is what a test can drive. The first frame is 0 s, so a body starts at rest rather than mid-breath.
      let started: number | null = null;
      const tick = (now: number) => {
        frame = requestAnimationFrame(tick);
        started ??= now;
        rig.frame({
          t: (now - started) / 1000,
          level: playbackLevel.current ?? 0,
          pointer: pointer.current,
        });
      };
      frame = requestAnimationFrame(tick);
    })();

    return () => {
      cancelled = true;
      if (frame) cancelAnimationFrame(frame);
      stage.current = null;
      live?.dispose();
    };
  }, [source, profile, playbackLevel, seams]);

  function choose(next: Mood | null) {
    mood.current = next;
    setPicked(next);
    stage.current?.setMood(next);
  }

  function follow(event: { currentTarget: HTMLCanvasElement; clientX: number; clientY: number }) {
    const box = event.currentTarget.getBoundingClientRect();
    if (!box.width || !box.height) return;
    pointer.current = {
      x: ((event.clientX - box.left) / box.width) * 2 - 1,
      y: ((event.clientY - box.top) / box.height) * 2 - 1,
    };
  }

  return (
    <div className="avatar-stage" data-status={status}>
      <canvas
        ref={canvas}
        width={STAGE_WIDTH}
        height={STAGE_HEIGHT}
        hidden={status !== "drawing"}
        aria-label={`${profile.display_name} on stage`}
        onPointerMove={follow}
        onPointerLeave={() => {
          pointer.current = null;
        }}
      />
      {status === "loading" ? <p className="muted small">putting {profile.display_name} on the stage…</p> : null}
      {status === "no-3d" ? (
        <p className="muted small">
          This window cannot draw 3D, so {profile.display_name} is measured and voiced but not shown. The
          library, the walk and the pick all still work here.
        </p>
      ) : null}
      {status === "failed" ? (
        <p className="error" role="alert">{`cannot put ${profile.display_name} on stage: ${notes[0]}`}</p>
      ) : null}
      {status === "drawing" && moods ? (
        <div className="stage-moods" role="group" aria-label="mood">
          <button type="button" aria-pressed={picked === null} onClick={() => choose(null)}>
            neutral
          </button>
          {MOOD_KEYS.map((key) => (
            <button key={key} type="button" title={key} aria-pressed={picked === key} onClick={() => choose(key)}>
              {MOOD_LABEL[key]}
            </button>
          ))}
        </div>
      ) : null}
      {status === "drawing" && notes.length > 0 ? (
        <ul className="stage-notes small muted">
          {notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
