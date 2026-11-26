export type Caption = "s" | "m" | "l" | "xl";
export type Scale = "s" | "m" | "l";
export type Density = "compact" | "cozy";

export interface Look {
  glass: boolean;
  motion: boolean;
  caption: Caption;
  scale: Scale;
  density: Density;
}

export const DEFAULT_LOOK: Look = { glass: true, motion: true, caption: "m", scale: "m", density: "compact" };

const LOOK_KEY = "kira.look";
const LOOK_EVENT = "kira-look";

function oneOf<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return typeof value === "string" && (allowed as readonly string[]).includes(value) ? (value as T) : fallback;
}

function bool(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

/** One JSON value, merged over the defaults, so a partial or corrupt payload still yields a complete Look. */
export function currentLook(): Look {
  const raw = localStorage.getItem(LOOK_KEY);
  if (!raw) return DEFAULT_LOOK;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return DEFAULT_LOOK;
  }
  if (typeof parsed !== "object" || parsed === null) return DEFAULT_LOOK;
  const value = parsed as Record<string, unknown>;
  return {
    glass: bool(value.glass, DEFAULT_LOOK.glass),
    motion: bool(value.motion, DEFAULT_LOOK.motion),
    caption: oneOf(value.caption, ["s", "m", "l", "xl"] as const, DEFAULT_LOOK.caption),
    scale: oneOf(value.scale, ["s", "m", "l"] as const, DEFAULT_LOOK.scale),
    density: oneOf(value.density, ["compact", "cozy"] as const, DEFAULT_LOOK.density),
  };
}

type Listener = (look: Look) => void;
const listeners = new Set<Listener>();

function notify(): void {
  const look = currentLook();
  for (const fn of listeners) fn(look);
}

function onStorage(event: StorageEvent): void {
  if (event.key === LOOK_KEY) notify();
}

export function onLook(fn: Listener): () => void {
  listeners.add(fn);
  if (listeners.size === 1) {
    window.addEventListener(LOOK_EVENT, notify);
    window.addEventListener("storage", onStorage);
  }
  return () => {
    listeners.delete(fn);
    if (listeners.size === 0) {
      window.removeEventListener(LOOK_EVENT, notify);
      window.removeEventListener("storage", onStorage);
    }
  };
}

export function setLook(patch: Partial<Look>): void {
  localStorage.setItem(LOOK_KEY, JSON.stringify({ ...currentLook(), ...patch }));
  window.dispatchEvent(new Event(LOOK_EVENT));
}
