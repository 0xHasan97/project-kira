/**
 * The card: Kira's face on the desktop, in a window with no chrome.
 *
 * This is what `/chat/#/companion` renders inside the second window that
 * `kira-engine desktop --companion` opens. It is deliberately not a smaller version of the app: no
 * rail, no model picker, no explanation. One body, its name, and the two controls that only mean
 * something from a window floating over your work — go click-through, and get out of the way.
 *
 * Two bargains hold it together, both borrowed from the app window.
 *
 * **Everything native arrives as a seam.** `readBridge()` is the only line that reaches for
 * `window.pywebview`, so a browser tab open on the same URL says "this control belongs to the desktop
 * window" instead of throwing, and the suite hands in a fake.
 *
 * **The card wears the same skin.** It is wrapped in the `.app` element carrying the app window's
 * theme, because every token the palette defines lives there — and the one thing this window must
 * not inherit is `.app`'s opaque background, which styles.css strips for `html[data-window="companion"]`.
 */
import { useEffect, useRef, useState } from "react";
import type { ChangeEvent } from "react";
import type { KiraClient } from "../api.ts";
import { AvatarStage } from "../avatar/AvatarStage.tsx";
import type { CharacterList, CharacterProfile } from "../contracts.ts";
import { currentRoute } from "../hash-route.ts";
import { currentTheme, onTheme } from "../theme.ts";
import type { Theme } from "../theme.ts";
import { useAsync } from "../useAsync.ts";
import { useAppearance } from "../useAppearance.ts";

const TOKEN_KEY = "kira.token";
const EMPTY: CharacterList = { characters: [], active: null };

/** What the desktop window publishes as `window.pywebview.api`. */
export interface CompanionBridge {
  set_click_through(
    enabled: boolean,
  ): Promise<{ ok: boolean; click_through?: boolean; error?: string }>;
  get_state(): Promise<{ click_through: boolean; supported: boolean }>;
}

/** The bridge when this page is the card, and null when it is a tab in an ordinary browser. */
export function readBridge(): CompanionBridge | null {
  const api = (
    window as unknown as { pywebview?: { api?: Partial<CompanionBridge> } }
  ).pywebview?.api;
  return typeof api?.set_click_through === "function" &&
    typeof api.get_state === "function"
    ? (api as CompanionBridge)
    : null;
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function CompanionScreen({
  client,
  connected,
  token = localStorage.getItem(TOKEN_KEY) ?? "",
  pull = 0,
  bridge,
}: {
  client: KiraClient;
  connected: boolean;
  token?: string;
  pull?: number;
  /** `undefined` asks the window, `null` says there is no window to ask - which is a browser tab. */
  bridge?: CompanionBridge | null;
}) {
  const api = bridge === undefined ? readBridge() : bridge;
  // The query the window was created with names this card, but only the hash means the boot
  // navigation has arrived. Between the two the document is seconds from being replaced.
  const onTarget = currentRoute() === "companion";
  const [clickThrough, setClickThrough] = useState(false);
  const [supported, setSupported] = useState(onTarget && api !== null);
  const [note, setNote] = useState<string | null>(null);
  const [theme, setTheme] = useState<Theme>(() => currentTheme());
  const { mode } = useAppearance();
  // This pane has no audio to measure, so the mouth sits at silence: the card is a pet on the desktop,
  // and the call screen is where a speaking Kira has her own window and her own analyser.
  const silence = useRef(0);

  // The window is frameless and asked to be transparent; the transparent client area only shows
  // through where the page paints nothing, and this attribute is what switches that on in styles.css.
  useEffect(() => {
    document.documentElement.dataset.window = "companion";
  }, []);

  // A pick on the Avatar screen writes `kira.theme` in the app window, and both windows read the same
  // localStorage but a `storage` event never crosses into this one; a card in the wrong colours is a
  // card that looks broken. So the card follows the same preference module the app does.
  useEffect(() => onTheme(setTheme), []);

  // A card reopened after a reboot may still be click-through, so the switch starts where the window
  // left it. A rejected read means there is no window to ask, which is the same answer as no bridge.
  useEffect(() => {
    // Nothing is asked of a document the boot navigation is about to throw away: the answer arrives at
    // a page that no longer exists and pywebview raises in its own thread, which is what the live run showed.
    if (!onTarget) return;
    if (!api) {
      setSupported(false);
      return;
    }
    let cancelled = false;
    api
      .get_state()
      .then((state) => {
        if (cancelled) return;
        setSupported(state.supported);
        setClickThrough(state.click_through);
      })
      .catch(() => {
        if (!cancelled) setSupported(false);
      });
    return () => {
      cancelled = true;
    };
  }, [api, onTarget]);

  const library = useAsync(
    () => (connected ? client.characters() : Promise.resolve(EMPTY)),
    [connected, pull],
  );
  const activeId = library.kind === "ready" ? library.data.active : null;
  const detail = useAsync(
    () =>
      connected && activeId
        ? client.character(activeId)
        : Promise.resolve(null),
    [connected, activeId, pull],
  );
  const onStage: CharacterProfile | null =
    detail.kind === "ready" ? detail.data : null;

  // The body on stage is the engine's state, and the app window is where it changes. Two windows share
  // no re-render, so the card re-reads when it comes back to the front — the moment the user has just
  // alt-tabbed over to look at it, which is when a stale pet is noticeable.
  useEffect(() => {
    function wake() {
      library.refresh();
      detail.refresh();
    }
    window.addEventListener("focus", wake);
    return () => window.removeEventListener("focus", wake);
  }, [library.refresh, detail.refresh]);

  function toggle(event: ChangeEvent<HTMLInputElement>) {
    const wanted = event.target.checked;
    if (!api) return;
    api
      .set_click_through(wanted)
      .then((reply) => {
        if (reply.ok) {
          setClickThrough(reply.click_through === true);
          setSupported(true);
          setNote(null);
          return;
        }
        // The switch follows the window, not the wish: the style word is what the page reports.
        setClickThrough(false);
        setNote(reply.error ?? "the window would not answer");
      })
      .catch((error: unknown) => {
        setClickThrough(false);
        setNote(messageOf(error));
      });
  }

  const card = (
    <section className="companion" aria-label="Kira companion">
      {onStage ? (
        <>
          <AvatarStage
            source={client}
            profile={onStage}
            playbackLevel={silence}
            moods={false}
          />
          <p className="companion-name">{onStage.display_name}</p>
        </>
      ) : (
        <p className="companion-hint">
          {library.kind === "loading" || detail.kind === "loading"
            ? "reading the stage…"
            : "no character on stage - pick one on the Avatar screen in the Kira window"}
        </p>
      )}

      <div className="companion-bar">
        <label className="companion-switch">
          <input
            type="checkbox"
            aria-label="click through"
            checked={clickThrough}
            disabled={!supported}
            onChange={toggle}
          />
          <span>click through</span>
        </label>
        <button type="button" aria-label="hide" onClick={() => window.close()}>
          hide
        </button>
      </div>

      {!supported && (
        <p className="muted companion-hint">
          click through only works in the desktop window
        </p>
      )}
      {note && (
        <p className="error" role="alert">
          {note}
        </p>
      )}
    </section>
  );

  if (!token) {
    // No token field here on purpose: the engine's token is typed once, in the app window, and both
    // windows read the same localStorage. A second gate would be a second place to leak it.
    return (
      <div
        className="app companion-window"
        data-shell="chat"
        data-theme={theme}
        data-mode={mode}
      >
        <p className="companion-hint">
          no engine token yet - connect in the Kira window
        </p>
      </div>
    );
  }

  // `data-shell="chat"` is not the Chat mode: it is where the palette tokens are declared, and the one
  // the card can wear without the agent's sidebar geometry. The theme is the app window's choice, read
  // live, so a card on the desktop is the same colour as the Kira in the window behind it.
  return (
    <div
      className="app companion-window"
      data-shell="chat"
      data-theme={theme}
      data-mode={mode}
    >
      {card}
    </div>
  );
}
