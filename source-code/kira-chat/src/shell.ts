export const SHELLS = ["chat", "agent"] as const;
export type Shell = (typeof SHELLS)[number];

const SHELL_KEY = "kira.shell";
const SHELL_EVENT = "kira-shell";
const DEFAULT_SHELL: Shell = "chat";

function parse(value: string | null): Shell {
  return value !== null && (SHELLS as readonly string[]).includes(value) ? (value as Shell) : DEFAULT_SHELL;
}

/** Which surface the user prefers. A preference, not a route: two tabs may disagree. */
export function currentShell(): Shell {
  return parse(localStorage.getItem(SHELL_KEY));
}

type Listener = (shell: Shell) => void;
const listeners = new Set<Listener>();

function notify(): void {
  const shell = currentShell();
  for (const fn of listeners) fn(shell);
}

function onStorage(event: StorageEvent): void {
  if (event.key === SHELL_KEY) notify();
}

export function onShell(fn: Listener): () => void {
  listeners.add(fn);
  if (listeners.size === 1) {
    window.addEventListener(SHELL_EVENT, notify);
    window.addEventListener("storage", onStorage);
  }
  return () => {
    listeners.delete(fn);
    if (listeners.size === 0) {
      window.removeEventListener(SHELL_EVENT, notify);
      window.removeEventListener("storage", onStorage);
    }
  };
}

export function navigateShell(shell: Shell): void {
  localStorage.setItem(SHELL_KEY, shell);
  // Dispatched even when nothing changed: a click on the active position still means "paint this".
  window.dispatchEvent(new Event(SHELL_EVENT));
}
