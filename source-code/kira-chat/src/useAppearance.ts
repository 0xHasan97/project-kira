import { useEffect, useState } from "react";
import {
  currentAppearance,
  onAppearance,
  resolveAppearance,
  systemPrefersDark,
  type Appearance,
  type AppearanceMode,
} from "./appearance.ts";

const THEME_COLOR: Record<AppearanceMode, string> = {
  light: "#f5f5f7",
  dark: "#0f1113",
};

/**
 * The one place a resolved mode is written to the document.
 *
 * `data-mode` is on `<html>` rather than on `.app` because the connect gate and the companion card
 * are siblings of the app, not children of it, and both have to follow the same choice. `color-scheme`
 * is what makes the native select menus, scrollbars and autofill agree with the page.
 */
export function useAppearance(): {
  appearance: Appearance;
  mode: AppearanceMode;
} {
  const [appearance, setAppearance] = useState<Appearance>(() =>
    currentAppearance(),
  );
  const [systemDark, setSystemDark] = useState(() => systemPrefersDark());

  useEffect(() => onAppearance(setAppearance), []);

  useEffect(() => {
    let query: MediaQueryList | null = null;
    try {
      query = window.matchMedia?.("(prefers-color-scheme: dark)") ?? null;
    } catch {
      query = null;
    }
    if (!query) return;
    const onChange = (event: MediaQueryListEvent) =>
      setSystemDark(event.matches);
    setSystemDark(query.matches);
    query.addEventListener?.("change", onChange);
    return () => query.removeEventListener?.("change", onChange);
  }, []);

  const mode = resolveAppearance(appearance, systemDark);

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.mode = mode;
    root.style.colorScheme = mode;
    const meta = document.querySelector<HTMLMetaElement>(
      'meta[name="theme-color"]',
    );
    if (meta) meta.content = THEME_COLOR[mode];
    const status = document.querySelector<HTMLMetaElement>(
      'meta[name="apple-mobile-web-app-status-bar-style"]',
    );
    if (status)
      status.content = mode === "light" ? "default" : "black-translucent";
  }, [mode]);

  return { appearance, mode };
}
