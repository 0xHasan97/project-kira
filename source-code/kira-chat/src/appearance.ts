/**
 * Light, dark, or whatever the desktop is already wearing.
 *
 * The shell's seven accents are a separate choice (`theme.ts`): an accent changes one rail, this
 * changes every surface, including the connect gate, the settings sheet and the companion card.
 * Stored under `kira.appearance` and shared between tabs the same way the other two preferences are.
 */
export type Appearance = "system" | "light" | "dark";
export type AppearanceMode = "light" | "dark";

export const APPEARANCES: readonly Appearance[] = [
  "system",
  "light",
  "dark",
] as const;
export const APPEARANCE_LABELS: Record<Appearance, string> = {
  system: "System",
  light: "Light",
  dark: "Dark",
};
export const DEFAULT_APPEARANCE: Appearance = "system";

const KEY = "kira.appearance";
const EVENT = "kira-appearance";

function isAppearance(value: unknown): value is Appearance {
  return value === "system" || value === "light" || value === "dark";
}

export function currentAppearance(): Appearance {
  try {
    const stored = localStorage.getItem(KEY);
    return isAppearance(stored) ? stored : DEFAULT_APPEARANCE;
  } catch {
    return DEFAULT_APPEARANCE;
  }
}

export function setAppearance(appearance: Appearance): void {
  try {
    localStorage.setItem(KEY, appearance);
  } catch {
    // Private mode without storage still gets the paint for this tab.
  }
  window.dispatchEvent(
    new CustomEvent<Appearance>(EVENT, { detail: appearance }),
  );
}

/** The desktop's own answer, or light when the browser cannot say (older WebViews and jsdom). */
export function systemPrefersDark(): boolean {
  try {
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
  } catch {
    return false;
  }
}

export function resolveAppearance(
  appearance: Appearance,
  systemDark: boolean,
): AppearanceMode {
  if (appearance === "system") return systemDark ? "dark" : "light";
  return appearance;
}

export function onAppearance(
  listener: (appearance: Appearance) => void,
): () => void {
  const custom = (event: Event) =>
    listener((event as CustomEvent<Appearance>).detail);
  const storage = (event: StorageEvent) => {
    if (event.key !== KEY) return;
    listener(
      isAppearance(event.newValue) ? event.newValue : DEFAULT_APPEARANCE,
    );
  };
  window.addEventListener(EVENT, custom);
  window.addEventListener("storage", storage);
  return () => {
    window.removeEventListener(EVENT, custom);
    window.removeEventListener("storage", storage);
  };
}
