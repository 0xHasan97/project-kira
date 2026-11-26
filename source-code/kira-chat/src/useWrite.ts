import { useState } from "react";
import { KiraApiError } from "./contracts.ts";
import type { ConfirmRequest } from "./confirm.tsx";
import { useConfirm } from "./confirm.tsx";

export type WriteAct = (secret: string) => Promise<unknown>;

export interface RunOptions {
  /** Words the human must type in full before the dialog will submit. Never sent to the engine. */
  phrase?: string;
  /** False for a write whose answer the screen renders itself, so a re-read would only shuffle cells. */
  reread?: boolean;
}

/**
 * The one place a write is confirmed, sent, re-read and — on a refused secret — asked again.
 * A screen owns its own data; this owns the dialog around it.
 */
export function useWrite(refresh: () => void) {
  const ask = useConfirm();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function run(
    summary: string,
    detail: string,
    danger: boolean,
    act: WriteAct,
    options: RunOptions = {},
  ): Promise<void> {
    const reread = options.reread ?? true;
    let request: ConfirmRequest = { summary, detail, danger, phrase: options.phrase };
    for (;;) {
      const secret = await ask(request);
      if (!secret) return;
      setBusy(true);
      setNote(null);
      try {
        await act(secret);
        if (reread) refresh();
        return;
      } catch (error) {
        if (!(error instanceof KiraApiError) || error.httpStatus !== 401) {
          setNote(error instanceof Error ? error.message : String(error));
          return;
        }
        // The spec's refusal clause: a mistyped secret re-opens the dialog with the reason instead of
        // leaving a bare 401 in a table cell, which reads as a broken button. Every pass needs a fresh
        // keystroke, so this cannot spin without a human in the loop, and nothing is remembered.
        request = { ...request, detail: `${detail} — the engine refused that secret; type it again` };
      } finally {
        setBusy(false);
      }
    }
  }

  /**
   * A write that needs no typed secret: the engine token in the header is the whole gate. It keeps
   * the same busy/note/refresh contract so a screen does not need a second set of states.
   */
  async function quick(act: () => Promise<unknown>, options: { reread?: boolean } = {}): Promise<boolean> {
    setBusy(true);
    setNote(null);
    try {
      await act();
      if (options.reread ?? true) refresh();
      return true;
    } catch (error) {
      setNote(error instanceof Error ? error.message : String(error));
      return false;
    } finally {
      setBusy(false);
    }
  }

  return { busy, note, run, quick };
}
