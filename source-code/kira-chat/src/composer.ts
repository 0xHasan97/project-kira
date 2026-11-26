export interface KeyPress {
  key: string;
  shiftKey?: boolean;
  ctrlKey?: boolean;
  metaKey?: boolean;
  /** True while an input method is mid-composition: Enter there picks a candidate, it does not send. */
  isComposing?: boolean;
}

/** Enter sends. Shift+Enter is a new line, and the old Ctrl/Cmd+Enter still works for muscle memory. */
export function wantsSend(event: KeyPress): boolean {
  if (event.key !== "Enter" || event.isComposing) return false;
  if (event.ctrlKey || event.metaKey) return true;
  return !event.shiftKey;
}

/** Grow to the text, stop at the cap, and only then scroll — a 20-line prompt must not push the thread off-screen. */
export function autosize(box: { scrollHeight: number; style: { height: string; overflowY: string } }, max = 180): void {
  box.style.height = `${Math.min(box.scrollHeight, max)}px`;
  box.style.overflowY = box.scrollHeight > max ? "auto" : "hidden";
}

/** The live turn's age, short enough for a composer footer: 4s, 1m 05s, 1h 04m. */
export function elapsed(since: number, now: number): string {
  const seconds = Math.max(0, Math.floor((now - since) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${String(seconds % 60).padStart(2, "0")}s`;
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
}
