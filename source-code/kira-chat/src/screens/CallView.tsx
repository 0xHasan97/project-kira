/**
 * The call surface: pure presentation over a `CallState`.
 *
 * Every action comes off `call`, so this file has no socket, no media and nothing to await — which is
 * what lets the view be tested with a fixture. The one judgement it does make is whether a call is
 * worth starting at all, and that comes from the engine's own `/v1/kira/voice` answer rather than from
 * a guess about what is installed.
 */
import { useState } from "react";
import type { FormEvent, ReactNode } from "react";
import type { VoiceStatus } from "../contracts.ts";
import type { CallState } from "../voice/useCall.ts";

const PHASE_LABEL: Record<string, string> = {
  idle: "not connected",
  connecting: "connecting",
  listening: "listening",
  thinking: "thinking",
  speaking: "speaking",
  ended: "call ended",
  error: "needs attention",
};

/**
 * `stage` is whatever the caller makes of the active character — an `AvatarStage`, or nothing when the
 * library has none. The view takes it on faith and says so when it is absent, because a call with no body
 * on it is still a call: the mouth that moves is a bonus on top of the answer, not a condition of it.
 */
export function CallView({
  call,
  status,
  stage,
}: {
  call: CallState;
  status: VoiceStatus | null;
  stage?: ReactNode;
}) {
  const [draft, setDraft] = useState("");
  const live = call.phase === "connecting" || call.phase === "listening" || call.phase === "thinking" || call.phase === "speaking";
  // An "off" stack cannot carry a conversation in either direction; anything else can, even partly —
  // a call with no speech engine still takes typed turns, so it must not be greyed out.
  const cannotStart = status !== null && status.stt.mode === "off" && status.tts.mode === "off";

  function submit(event: FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text) return;
    call.say(text);
    setDraft("");
  }

  return (
    <section className="call">
      <header className="call-head">
        <h2>Call</h2>
        <span className="call-phase mono" data-phase={call.phase}>{PHASE_LABEL[call.phase] ?? call.phase}</span>
        <span className="spacer" />
        <button type="button" onClick={() => void call.start()} disabled={cannotStart}>
          start call
        </button>
      </header>

      <div className="call-body">
        <div className="call-stage">
          {stage ?? (
            <p className="muted small">
              Kira has no face on this call — no character is on stage, so the answer has a voice and no
              mouth. The library is under #/avatar.
            </p>
          )}
          <video ref={call.videoRef} className="call-self" muted playsInline hidden={!call.camera} />
          {!call.camera && <div className="call-self-empty">camera off</div>}
          <div className="call-meter" aria-label="microphone level">
            <span style={{ width: `${Math.round(call.level * 100)}%` }} />
          </div>
          <div className="call-controls">
            <button type="button" onClick={call.toggleMute} aria-pressed={call.muted}>{call.muted ? "unmute" : "mute"}</button>
            <button type="button" onClick={() => void call.toggleCamera()} aria-pressed={call.camera}>{call.camera ? "camera off" : "camera on"}</button>
            <button type="button" onClick={call.look} disabled={!call.camera || !live}>look</button>
            <button type="button" onClick={call.end} disabled={!live}>end call</button>
          </div>
          {status && (
            <dl className="call-stack">
              <dt>listen</dt><dd>{status.stt.detail}</dd>
              <dt>speak</dt><dd>{status.tts.detail}</dd>
              <dt>see</dt><dd>{status.vision ? `frames → ${status.vision.provider} · ${status.vision.model}` : "frames stay on this device"}</dd>
            </dl>
          )}
        </div>

        <div className="call-transcript">
          {call.entries.map((entry) => (
            <article key={entry.id} className={`call-msg call-${entry.role}`}>{entry.text}</article>
          ))}
          {call.live && <article className="call-msg call-assistant call-live">{call.live}</article>}
          {call.error && <p className="call-error">{call.error}</p>}
        </div>
      </div>

      <form className="call-typed" onSubmit={submit}>
        <input aria-label="typed message" value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="type instead" />
        <button type="submit" disabled={!live}>send</button>
      </form>
      {call.chain.length > 0 && (
        <p className="call-chain mono">
          {call.chain
            .filter((record) => record.event === "served")
            .map((record) => `${record.provider} · ${record.model}`)
            .join(" ")}
        </p>
      )}
    </section>
  );
}
