export const THEMES = ["violet", "crimson", "emerald", "celestial", "gold", "rose", "charcoal"] as const; // donor order, App.tsx:522
export type Theme = (typeof THEMES)[number];

const THEME_KEY = "kira.theme";
const THEME_EVENT = "kira-theme";
const DEFAULT_THEME: Theme = "charcoal"; // App.tsx:305

function parse(value: string | null): Theme {
  return value !== null && (THEMES as readonly string[]).includes(value) ? (value as Theme) : DEFAULT_THEME;
}

export function currentTheme(): Theme {
  return parse(localStorage.getItem(THEME_KEY));
}

type Listener = (theme: Theme) => void;
const listeners = new Set<Listener>();

function notify(): void {
  const theme = currentTheme();
  for (const fn of listeners) fn(theme);
}

function onStorage(event: StorageEvent): void {
  if (event.key === THEME_KEY) notify();
}

export function onTheme(fn: Listener): () => void {
  listeners.add(fn);
  if (listeners.size === 1) {
    window.addEventListener(THEME_EVENT, notify);
    window.addEventListener("storage", onStorage);
  }
  return () => {
    listeners.delete(fn);
    if (listeners.size === 0) {
      window.removeEventListener(THEME_EVENT, notify);
      window.removeEventListener("storage", onStorage);
    }
  };
}

export function navigateTheme(theme: Theme): void {
  localStorage.setItem(THEME_KEY, theme);
  window.dispatchEvent(new Event(THEME_EVENT));
}
