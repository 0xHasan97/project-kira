export const ROUTES = [
  "chat",
  "call",
  "images",
  "studio",
  "prompts",
  "overview",
  "providers",
  "models",
  "sessions",
  "tools",
  "skills",
  "memory",
  "avatar",
  "remote",
  "pair",
  "companion",
] as const;
export type Route = (typeof ROUTES)[number];

/**
 * Everything the rail offers. `pair` is absent on purpose: it is the page a phone lands on from a
 * pairing link, not a section of this desktop's navigation. `companion` is absent for the same reason
 * in the other direction — it is a different window, and the app that hosts it has no use for it.
 */
export const RAIL_ROUTES: readonly Route[] = ROUTES.filter(
  (route) => route !== "pair" && route !== "companion",
);

const DEFAULT_ROUTE: Route = "chat";

function parse(hash: string): Route {
  const name = hash.replace(/^#\//, "").split("?")[0];
  return (ROUTES as readonly string[]).includes(name)
    ? (name as Route)
    : DEFAULT_ROUTE;
}

export function currentRoute(): Route {
  return parse(window.location.hash);
}

/**
 * The companion window boots on `/chat/?companion=1` and has no hash yet when the page first runs.
 * Without this, the very first paint of the card is the app — a rail, a model picker and a transcript
 * squeezed into a 320-pixel frameless window, which is what shows if the token injection is refused.
 */
export function isCompanionWindow(): boolean {
  return new URLSearchParams(window.location.search).get("companion") === "1";
}

export function initialRoute(): Route {
  return window.location.hash === "" && isCompanionWindow()
    ? "companion"
    : currentRoute();
}

type Listener = (route: Route) => void;
const listeners = new Set<Listener>();

export function onRoute(fn: Listener): () => void {
  listeners.add(fn);
  if (listeners.size === 1) {
    window.addEventListener("hashchange", notify);
  }
  return () => {
    listeners.delete(fn);
    if (listeners.size === 0) {
      window.removeEventListener("hashchange", notify);
    }
  };
}

function notify() {
  const route = currentRoute();
  for (const fn of listeners) fn(route);
}

/**
 * Consume the bearer token the launcher put in the fragment, then erase it.
 *
 * `run_kira.py` opens `/chat/#/chat?token=...`; a fragment is never sent to the engine or written to
 * its access log. This runs before React mounts, so the app reads the token from storage as usual.
 */
export function takeLaunchToken(): string {
  const query = window.location.hash.split("?")[1] ?? "";
  const token = new URLSearchParams(query).get("token")?.trim() ?? "";
  if (!token) return "";
  const url = new URL(window.location.href);
  url.hash = `#/${currentRoute()}`;
  window.history.replaceState(null, "", url);
  return token;
}

export function navigate(route: Route): void {
  const wanted = `#/${route}`;
  if (window.location.hash === wanted) {
    // Same route: no hashchange event will come, but the caller still wants a refresh.
    for (const fn of listeners) fn(route);
    return;
  }
  window.location.hash = wanted;
}
