import { useEffect, useRef, useState } from "react";
import {
  Activity,
  Monitor,
  Moon,
  Palette,
  Route,
  Sparkles,
  Sun,
  X,
} from "lucide-react";
import { MODES } from "./contracts.ts";
import type { HealthResponse, Mode, ModelInfo } from "./contracts.ts";
import { keyBadge } from "./keying.ts";
import { setLook, type Caption, type Look } from "./look.ts";
import { APPEARANCE_LABELS, APPEARANCES, setAppearance } from "./appearance.ts";
import { useAppearance } from "./useAppearance.ts";
import type { Shell } from "./shell.ts";
import { navigateTheme, THEMES, type Theme } from "./theme.ts";

const TABS = [
  { id: "theme", label: "Theme", icon: Palette },
  { id: "mode", label: "Mode", icon: Route },
  { id: "look", label: "Look", icon: Sparkles },
  { id: "status", label: "Status", icon: Activity },
] as const;
type Tab = (typeof TABS)[number]["id"];

const CAPTIONS: Caption[] = ["s", "m", "l", "xl"];
const CAPTION_LABELS: Record<Caption, string> = {
  s: "S",
  m: "M",
  l: "L",
  xl: "XL",
};

export interface OptionsPanelProps {
  open: boolean;
  onClose(): void;
  shell: Shell;
  theme: Theme;
  look: Look;
  mode: Mode;
  setMode(mode: Mode): void;
  models: ModelInfo[];
  model: string;
  setModel(model: string): void;
  health: HealthResponse | null;
  sessionId: string | null;
  sessionCount: number;
  onRefresh(): void;
  onDisconnect(): void;
}

/**
 * MYRAA's overlay panel, carrying the options Kira actually has. The pattern is the donor's
 * (SettingsPanel.tsx: section list with icons, mono group headings over a divided glass list,
 * role="switch" toggles, a role="radio" segmented control, a mono status pill); the contents are ours.
 */
export function OptionsPanel(props: OptionsPanelProps) {
  const { open, onClose } = props;
  const [tab, setTab] = useState<Tab>("theme");
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    panelRef.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const cooling = props.health
    ? Object.values(props.health.providers).filter(
        (state) => state.cooling_s > 0,
      ).length
    : 0;

  return (
    <div
      className="options-backdrop"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        className="options-panel"
        role="dialog"
        aria-modal="true"
        aria-label="settings"
        tabIndex={-1}
        ref={panelRef}
      >
        <header className="options-head">
          <span className="options-badge">K</span>
          <div>
            <h2>Kira</h2>
            <p className="status-pill">
              <span
                className={`dot ${props.sessionId || props.sessionCount > 0 ? "on" : "off"}`}
              />
              {cooling > 0
                ? `${cooling} provider${cooling === 1 ? "" : "s"} cooling`
                : "Local engine"}
            </p>
          </div>
          <span className="spacer" />
          <button
            type="button"
            className="icon-button"
            aria-label="close settings"
            onClick={onClose}
          >
            <X size={16} />
          </button>
        </header>

        <div
          className="options-tabs"
          role="tablist"
          aria-label="settings sections"
        >
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              role="tab"
              id={`options-tab-${id}`}
              aria-selected={tab === id}
              aria-controls={`options-tabpanel-${id}`}
              className={tab === id ? "active" : ""}
              onClick={() => setTab(id)}
            >
              <Icon size={14} />
              {label}
            </button>
          ))}
        </div>

        <div
          className="options-body"
          role="tabpanel"
          id={`options-tabpanel-${tab}`}
          aria-labelledby={`options-tab-${tab}`}
        >
          {tab === "theme" && <ThemeTab theme={props.theme} />}
          {tab === "mode" && <ModeTab {...props} />}
          {tab === "look" && <LookTab look={props.look} shell={props.shell} />}
          {tab === "status" && <StatusTab {...props} />}
        </div>

        <footer className="options-foot">
          <button type="button" onClick={props.onRefresh}>
            refresh
          </button>
          <button type="button" className="danger" onClick={props.onDisconnect}>
            disconnect
          </button>
        </footer>
      </div>
    </div>
  );
}

function Group({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="options-group">
      <h3>{title}</h3>
      {hint && <p className="options-hint">{hint}</p>}
      {children}
    </section>
  );
}

const APPEARANCE_ICONS = { system: Monitor, light: Sun, dark: Moon } as const;

function ThemeTab({ theme }: { theme: Theme }) {
  const { appearance } = useAppearance();
  return (
    <>
      <Group
        title="Appearance"
        hint="Light, dark, or the desktop's own setting. This repaints every screen, including the agent workspace and the connect gate."
      >
        <div
          className="segmented appearance-picker"
          role="group"
          aria-label="appearance"
        >
          {APPEARANCES.map((option) => {
            const Icon = APPEARANCE_ICONS[option];
            return (
              <button
                key={option}
                type="button"
                role="radio"
                aria-checked={appearance === option}
                onClick={() => setAppearance(option)}
              >
                <Icon size={14} aria-hidden="true" />
                {APPEARANCE_LABELS[option]}
              </button>
            );
          })}
        </div>
      </Group>
      <Group
        title="Accent"
        hint="Seven rail accents for the chat shell. The agent workspace keeps its neutral green."
      >
        <div className="tiles" role="group" aria-label="theme">
          {THEMES.map((name) => (
            <button
              key={name}
              type="button"
              role="radio"
              aria-checked={name === theme}
              className={`tile tile-${name}`}
              onClick={() => navigateTheme(name)}
            >
              {name}
            </button>
          ))}
        </div>
      </Group>
    </>
  );
}

function ModeTab({
  mode,
  setMode,
  models,
  model,
  setModel,
}: OptionsPanelProps) {
  return (
    <>
      <Group
        title="Routing mode"
        hint="A tier filter over your own providers. Never a hidden catalogue."
      >
        <div className="segmented" role="group" aria-label="routing mode">
          {MODES.map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={m === mode}
              onClick={() => setMode(m)}
            >
              {m}
            </button>
          ))}
        </div>
      </Group>
      <Group title="Model" hint={`${models.length} configured`}>
        <div className="tiles" role="group" aria-label="model">
          {models.map((m) => (
            <button
              key={`${m.provider}-${m.id}`}
              type="button"
              role="radio"
              aria-checked={m.id === model}
              aria-label={`use model ${m.id} ${m.provider} ${m.tier}`}
              className="tile"
              onClick={() => setModel(m.id)}
            >
              <strong>{m.id}</strong>
              <span>
                {m.provider} · {m.tier}
              </span>
            </button>
          ))}
          {models.length === 0 && <p className="empty">no models configured</p>}
        </div>
      </Group>
    </>
  );
}

function LookTab({ look, shell }: { look: Look; shell: Shell }) {
  return (
    <>
      <Group title="Caption size" hint="How large the streamed answer reads.">
        <div className="segmented" role="group" aria-label="caption size">
          {CAPTIONS.map((size) => (
            <button
              key={size}
              type="button"
              role="radio"
              aria-checked={look.caption === size}
              onClick={() => setLook({ caption: size })}
            >
              {CAPTION_LABELS[size]}
            </button>
          ))}
        </div>
      </Group>
      <Group title="Surface">
        <div className="rows">
          <ToggleRow
            label="glass"
            description="Frosted sheets behind answers, dialogs and panels."
            checked={look.glass}
            onChange={(glass) => setLook({ glass })}
          />
          <ToggleRow
            label="animations"
            description="Motion and transitions. Off follows your system's reduced-motion setting."
            checked={look.motion}
            onChange={(motion) => setLook({ motion })}
          />
          {shell === "agent" && (
            <ToggleRow
              label="cozy density"
              description="15px base instead of the workspace's 13px."
              checked={look.density === "cozy"}
              onChange={(cozy) =>
                setLook({ density: cozy ? "cozy" : "compact" })
              }
            />
          )}
        </div>
      </Group>
    </>
  );
}

function ToggleRow({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange(checked: boolean): void;
}) {
  return (
    <div className="row">
      <div>
        <div className="row-label">{label}</div>
        <div className="row-hint">{description}</div>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
      >
        <span />
      </button>
    </div>
  );
}

function StatusTab({ health, sessionId, sessionCount }: OptionsPanelProps) {
  return (
    <>
      <Group
        title="Session"
        hint="The engine owns history; this is the session it is appending to."
      >
        <div className="rows">
          <div className="row">
            <div>
              <div className="row-label">
                {sessionId ? sessionId.slice(0, 8) : "no session yet"}
              </div>
              <div className="row-hint">
                {sessionCount} stored session{sessionCount === 1 ? "" : "s"}
              </div>
            </div>
          </div>
        </div>
      </Group>
      <Group title="Providers" hint="Key presence and the router's ledger.">
        <div className="rows">
          {!health && <p className="empty">not read yet</p>}
          {health?.configured.map((provider) => {
            const state = health.providers[provider.name];
            const badge = keyBadge(provider);
            return (
              <div className="row" key={provider.name}>
                <div>
                  <div className="row-label mono">{provider.name}</div>
                  <div className="row-hint">
                    {state
                      ? `${state.successes}✓ ${state.failures}✗${state.cooling_s ? ` · ${state.cooling_s}s` : ""}`
                      : "idle"}
                  </div>
                </div>
                <span className={`pill ${badge.ok ? "pill-ok" : "pill-warn"}`}>
                  {badge.text}
                </span>
              </div>
            );
          })}
        </div>
      </Group>
    </>
  );
}
