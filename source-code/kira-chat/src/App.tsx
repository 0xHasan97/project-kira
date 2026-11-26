import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { KiraClient } from "./api.ts";
import {
  API_PREFIX,
  API_VERSION,
  CONTRACT_VERSION,
  KiraApiError,
  MODES,
} from "./contracts.ts";
import type { ModelInfo, Mode } from "./contracts.ts";
import { ConfirmProvider } from "./confirm.tsx";
import { initialRoute, navigate, onRoute } from "./hash-route.ts";
import type { Route } from "./hash-route.ts";
import { answersToday } from "./keying.ts";
import { ChatScreen } from "./screens/ChatScreen.tsx";
import { AgentPanel } from "./screens/AgentPanel.tsx";
import { ImagesScreen } from "./screens/ImagesScreen.tsx";
import { MemoryScreen } from "./screens/MemoryScreen.tsx";
import { ModelsScreen } from "./screens/ModelsScreen.tsx";
import { OverviewScreen } from "./screens/OverviewScreen.tsx";
import { PairScreen } from "./screens/PairScreen.tsx";
import { PromptsScreen } from "./screens/PromptsScreen.tsx";
import { ProvidersScreen } from "./screens/ProvidersScreen.tsx";
import { RemoteScreen } from "./screens/RemoteScreen.tsx";
import { SessionsScreen } from "./screens/SessionsScreen.tsx";
import { SkillsScreen } from "./screens/SkillsScreen.tsx";
import { ToolsScreen } from "./screens/ToolsScreen.tsx";
import { currentShell, onShell, type Shell } from "./shell.ts";
import { ShellSwitch } from "./shell-switch.tsx";
import { currentTheme, onTheme, type Theme } from "./theme.ts";
import { currentLook, onLook, type Look } from "./look.ts";
import { setAppearance, type Appearance } from "./appearance.ts";
import { useAppearance } from "./useAppearance.ts";
import { OptionsPanel } from "./options-panel.tsx";
import { useChat } from "./useChat.ts";
import { CommandPalette } from "./command-palette.tsx";
import { ScreenBoundary } from "./screen-boundary.tsx";
import type { PaletteCommand } from "./command-palette.tsx";
import { downloadTranscript } from "./export.ts";
import {
  Activity,
  BookOpen,
  Boxes,
  BrainCircuit,
  Command as CommandIcon,
  Cpu,
  Download,
  History,
  Image as ImageIcon,
  LogOut,
  Menu as MenuIcon,
  MessageSquare,
  Monitor,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Phone,
  Radio,
  RefreshCw,
  Sparkles,
  ScanFace,
  Server,
  Smartphone,
  Sun,
  Wrench,
} from "lucide-react";

export const TOKEN_KEY = "kira.token";
export const BASE_KEY = "kira.base";
const SIDEBAR_KEY = "kira.sidebar";

/** One button is enough: system, light, dark, back to system. The settings sheet is the explicit list. */
const NEXT_APPEARANCE: Record<Appearance, Appearance> = {
  system: "light",
  light: "dark",
  dark: "system",
};
const APPEARANCE_ICON = { system: Monitor, light: Sun, dark: Moon } as const;

const NAV_ICONS = {
  chat: MessageSquare,
  call: Phone,
  images: ImageIcon,
  studio: Boxes,
  prompts: Sparkles,
  overview: Activity,
  providers: Server,
  models: Cpu,
  sessions: History,
  tools: Wrench,
  skills: BookOpen,
  memory: BrainCircuit,
  avatar: ScanFace,
  remote: Radio,
  pair: Smartphone,
  companion: ScanFace,
} as const;

function NavIcon({ route }: { route: Route }) {
  const Icon = NAV_ICONS[route];
  return <Icon size={15} aria-hidden="true" />;
}

const NAV_LABELS: Record<Route, string> = {
  chat: "Chat",
  call: "Call",
  images: "Images",
  studio: "Studio",
  prompts: "Prompts",
  overview: "Overview",
  providers: "Providers",
  models: "Models",
  sessions: "Sessions",
  tools: "Tools",
  skills: "Skills",
  memory: "Memory",
  avatar: "Avatar",
  remote: "Remote",
  pair: "Pair a device",
  companion: "Companion",
};

// The three heavy surfaces and the companion card carry Three.js. A static import put that whole
// renderer in the first bundle even when the reader only ever opened chat; a lazy route keeps it out
// until the stage is actually asked for. The loaders are also the preload map: a pointer over a rail
// button starts the chunk before the click, so the split costs no visible delay.
const loadAvatarScreen = () =>
  import("./screens/AvatarScreen.tsx").then((module) => ({ default: module.AvatarScreen }));
const loadCallScreen = () =>
  import("./screens/CallScreen.tsx").then((module) => ({ default: module.CallScreen }));
const loadStudioScreen = () =>
  import("./screens/StudioScreen.tsx").then((module) => ({ default: module.StudioScreen }));
const loadCompanionScreen = () =>
  import("./screens/CompanionScreen.tsx").then((module) => ({ default: module.CompanionScreen }));

const AvatarScreen = lazy(loadAvatarScreen);
const CallScreen = lazy(loadCallScreen);
const StudioScreen = lazy(loadStudioScreen);
const CompanionScreen = lazy(loadCompanionScreen);

const PRELOAD_ROUTE: Partial<Record<Route, () => Promise<unknown>>> = {
  avatar: loadAvatarScreen,
  call: loadCallScreen,
  studio: loadStudioScreen,
};

function preloadRoute(route: Route): void {
  void PRELOAD_ROUTE[route]?.();
}

/**
 * What sits on the bottom bar at phone width. The rest of the rail is one tap away behind Menu, and
 * it is the same `<nav>` — a second list of routes would be a second thing to keep in step.
 */
const PHONE_ROUTES: readonly Route[] = [
  "chat",
  "call",
  "sessions",
  "overview",
  "avatar",
];

/**
 * The rail reads as two jobs rather than one long list of fourteen peers: what you make, and what
 * you configure. A group label is not a route; it is the same button list with headings between.
 */
const NAV_GROUPS: readonly { label: string; items: readonly Route[] }[] = [
  { label: "Create", items: ["chat", "prompts", "call", "images", "studio", "overview"] },
  {
    label: "Workspace",
    items: [
      "providers",
      "models",
      "sessions",
      "tools",
      "skills",
      "memory",
      "avatar",
      "remote",
    ],
  },
];

export default function App() {
  // A fresh browser tab has no token, and the engine refuses every authenticated route without one.
  // The gate below is where the launcher's printed token is typed; the desktop window skips it by
  // writing the token into localStorage before the page loads, and a paired phone enters through
  // `#/pair`, which sits before the gate.
  const [base, setBase] = useState(
    () => localStorage.getItem(BASE_KEY) ?? "http://127.0.0.1:8901",
  );
  const [token, setToken] = useState(
    () => localStorage.getItem(TOKEN_KEY) ?? "",
  );
  const [draftToken, setDraftToken] = useState("");
  const [connected, setConnected] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);
  const [engineIssue, setEngineIssue] = useState<string | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [model, setModel] = useState("");
  const [mode, setMode] = useState<Mode>("AUTO");
  const [route, setRoute] = useState<Route>(() => initialRoute());
  const [shell, setShell] = useState<Shell>(() => currentShell());
  const [theme, setTheme] = useState<Theme>(() => currentTheme());
  const [look, setLookState] = useState<Look>(() => currentLook());
  const { appearance, mode: appearanceMode } = useAppearance();
  const [panelOpen, setPanelOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem(SIDEBAR_KEY) === "collapsed",
  );
  const [focusSession, setFocusSession] = useState<string | null>(null);
  // The rail's refresh is the only re-read a screen gets for changes this tab did not make — a phone
  // pairing, its chat landing in Sessions, a key stored from the CLI. `useAsync` reads on mount and on
  // its own deps, so the counter is what the screens listen to.
  const [pull, setPull] = useState(0);

  const client = useMemo(
    () => new KiraClient({ baseUrl: base, token }),
    [base, token],
  );

  // The turn lives above the surface branch: switching Chat ↔ Agent mid-answer must not unmount it.
  const chat = useChat({
    client,
    model,
    mode,
    connected,
    watching: route === "chat" || shell === "agent",
  });

  // Two providers can serve the same id, and the router — not the picker — chooses between them by
  // mode, priority, key, budget and cooldown. One option per id keeps the value an id (what the API
  // takes) while the label names every provider that can answer it.
  const modelChoices = useMemo(() => {
    const byId = new Map<string, ModelInfo[]>();
    for (const entry of models) {
      const rows = byId.get(entry.id);
      if (rows) rows.push(entry);
      else byId.set(entry.id, [entry]);
    }
    return [...byId.values()].map((rows) => {
      const first = rows[0]!;
      const cw = first.context_window;
      return {
        id: first.id,
        providers: rows.map((row) => row.provider),
        tiers: [...new Set(rows.map((row) => row.tier))],
        answers: rows.some((row) => answersToday(row)),
        contextWindow: cw,
        contextWindowText: cw ? `${(cw / 1024).toFixed(0)}k` : "—",
      };
    });
  }, [models]);

  useEffect(() => onRoute(setRoute), []);
  useEffect(() => onShell(setShell), []);
  useEffect(() => onTheme(setTheme), []);
  useEffect(() => onLook(setLookState), []);

  // A route change is the end of a menu: the sheet is glued to the bottom bar it covers.
  useEffect(() => {
    setMenuOpen(false);
  }, [route]);

  // A sheet that only a route can close is a trap for the keyboard a tablet still has.
  useEffect(() => {
    if (!menuOpen) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setMenuOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  function toggleSidebar() {
    setCollapsed((prev) => {
      localStorage.setItem(SIDEBAR_KEY, prev ? "expanded" : "collapsed");
      return !prev;
    });
  }

  const refresh = useCallback(async () => {
    setPull((n) => n + 1);
    try {
      const probe = await client.healthz();
      if (
        probe.api_version !== API_VERSION ||
        probe.contract_version !== CONTRACT_VERSION
      ) {
        // This string has to survive the connect gate: a bundle in an old tab is the one case where
        // `contract_version` disagreement is the *engine's* truth about *us*, and the gate is gone by then.
        const issue =
          `this page speaks ${API_PREFIX} contract v${CONTRACT_VERSION}, ` +
          `the engine speaks /v${probe.api_version} contract v${probe.contract_version} — ` +
          "start it with `python run_kira.py --rebuild` to serve this bundle again";
        setConnected(false);
        setConnectError(issue);
        setEngineIssue(issue);
        return;
      }
      setConnected(true);
      setConnectError(null);
      setEngineIssue(null);
      const catalogue = await client.models();
      setModels(catalogue.data);
      // No default pin. A picker that always names a model made cross-provider failover unreachable,
      // because AUTO holds the named provider first but the rest behind it — the engine decides, and an
      // empty `model` is how the client says so. A choice the user made (or a Models screen "use")
      // is a value the catalogue recognises, so it survives this read untouched.
      if (model && !catalogue.data.some((m) => m.id === model)) setModel("");
    } catch (error) {
      setConnected(false);
      // A refusal from the engine is one message; no answer at all is another. The second is what a
      // phone shows when the service worker served the shell and the engine is not running - and a
      // cached copy that will not say so reads as a broken app rather than an unreachable one.
      setConnectError(
        error instanceof KiraApiError
          ? messageOf(error)
          : `no answer from the engine at ${base} (${messageOf(error)})`,
      );
      // A token the engine refuses is not a connection to keep: leaving the shell mounted hides
      // the one screen that can replace it. The URL survives; only the token is dropped.
      if (error instanceof KiraApiError && error.body.code === "unauthorized") {
        localStorage.removeItem(TOKEN_KEY);
        setToken("");
      }
    }
  }, [client, model, base]);

  // Screens take a `() => void` re-read, so the one floating promise lives here, not at each call site.
  const voidRefresh = useCallback(() => {
    void refresh();
  }, [refresh]);

  function useInChat(id: string) {
    setModel(id);
    navigate("chat");
  }

  // App state rather than a ref: the transcript has to reopen when the same trouble row is clicked
  // again, and only a re-render carries that. See Task 18 Step 6 and the note on a repeat click.
  function openSessionTranscript(sessionId: string) {
    setFocusSession(sessionId);
    navigate("sessions");
  }

  useEffect(() => {
    if (token) void refresh();
  }, [token, refresh]);

  // Ctrl/Cmd+K is the one shortcut that has to work from a composer too, so it is captured at the
  // window: a palette reachable only from an empty page would be a feature nobody finds.
  useEffect(() => {
    if (!token) return;
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [token]);

  function connect(event: FormEvent) {
    event.preventDefault();
    const value = draftToken.trim();
    if (!value) return;
    localStorage.setItem(TOKEN_KEY, value);
    localStorage.setItem(BASE_KEY, base.trim());
    setToken(value);
    setDraftToken("");
  }

  if (route === "companion") {
    // The desktop card is a window of its own: no rail, no model picker, no options panel. It is
    // reached by `--companion`, never by the navigation, and it answers for itself when there is no
    // token to draw with, so it sits outside the gate as much as outside the shell.
    return (
      <ScreenBoundary>
        <Suspense fallback={<main className="gate"><p className="muted">loading…</p></main>}>
          <CompanionScreen
            client={client}
            connected={connected}
            token={token}
            pull={pull}
          />
        </Suspense>
      </ScreenBoundary>
    );
  }

  if (route === "pair") {
    // Before the gate on purpose: a phone arrives here with no token at all, and the code is the
    // only credential it has. The token it buys is stored like the owner's and leaves by the same
    // disconnect button.
    return (
      <PairScreen
        onPaired={(value) => {
          localStorage.setItem(TOKEN_KEY, value);
          localStorage.setItem(BASE_KEY, base.trim());
          setToken(value);
          navigate("chat");
        }}
      />
    );
  }

  if (!token) {
    return (
      <main className="gate">
        <form onSubmit={connect} className="gate-card">
          <h1>Connect to Kira</h1>
          <p className="muted">
            The engine runs on loopback and speaks with the bearer token it
            printed on first run.
          </p>
          <label>
            Engine URL
            <input
              name="engine_url"
              value={base}
              onChange={(e) => setBase(e.target.value)}
              placeholder="http://127.0.0.1:8901"
            />
          </label>
          <label>
            Bearer token
            <input
              name="engine_token"
              value={draftToken}
              onChange={(e) => setDraftToken(e.target.value)}
              type="password"
              autoFocus
              placeholder="kira token"
            />
          </label>
          <button type="submit">Connect</button>
          {connectError && <p className="error">{connectError}</p>}
        </form>
      </main>
    );
  }

  // A revision disagreement is the louder claim, but an engine that never answered belongs on the
  // shell too: the gate is gone once a token is stored, and offline is exactly when the reason matters.
  const shellIssue = engineIssue ?? (connected ? null : connectError);
  const AppearanceIcon = APPEARANCE_ICON[appearance];
  // Chat mode is a surface, not a single route: it keeps its own header and hides the workspace rail
  // on Providers, Models and Sessions too, so opening one of them does not silently turn the app back
  // into the agent workspace. The navigation stays behind the drawer in every chat-route case.
  const focusedChat = shell === "chat";

  const routingPicker = (
    <select
      name="routing_mode"
      value={mode}
      onChange={(e) => setMode(e.target.value as Mode)}
      aria-label="routing mode"
    >
      {MODES.map((m) => (
        <option key={m} value={m}>
          {m}
        </option>
      ))}
    </select>
  );
  const modelPicker = (
    <select
      name="model"
      value={model}
      onChange={(e) => setModel(e.target.value)}
      aria-label="model"
    >
      {modelChoices.length === 0 && (
        <option value="">no models configured</option>
      )}
      {modelChoices.length > 0 && (
        <option value="">
          {mode === "AUTO"
            ? "Auto · the router picks"
            : "Auto · only this lane"}
        </option>
      )}
      {modelChoices.map((choice) => (
        <option key={choice.id} value={choice.id}>
          {choice.id} · {choice.providers.join(", ")} · {choice.tiers.join("/")}
          {choice.answers ? "" : " · no key"}
        </option>
      ))}
    </select>
  );
  const appearanceButton = (
    <button
      type="button"
      className="bar-appearance"
      aria-label={`change appearance (currently ${appearance})`}
      title={`Appearance: ${appearance}`}
      onClick={() => setAppearance(NEXT_APPEARANCE[appearance])}
    >
      <AppearanceIcon size={15} aria-hidden="true" />
    </button>
  );
  const settingsButton = (
    <button
      type="button"
      aria-expanded={panelOpen}
      onClick={() => setPanelOpen((open) => !open)}
    >
      settings
    </button>
  );
  const versionBadge = (
    <span className="muted mono">
      {API_PREFIX} · v{CONTRACT_VERSION}
    </span>
  );

  const exportConversation = () => {
    const turns = chat.entries.map((entry) => ({
      role: entry.role,
      content: entry.content,
      provider: entry.turn?.provider ?? null,
      model: entry.turn?.model ?? null,
    }));
    // A turn still streaming is not in `entries` yet. Exporting the thread mid-answer should not
    // silently drop the words on screen, so the live text is appended as the answer it will become.
    if (chat.live?.text) {
      turns.push({
        role: "assistant",
        content: chat.live.text,
        provider: chat.live.provider,
        model: chat.live.model,
      });
    }
    downloadTranscript(chat.sessionId, turns);
  };

  // Built per render on purpose: the actions close over the current appearance and chat sitting, and
  // a stale command that starts a previous chat would be worse than a few array allocations.
  const paletteCommands: PaletteCommand[] = [
    {
      id: "new-chat",
      label: "New chat",
      hint: "Start a fresh conversation",
      group: "Do",
      keywords: "conversation session",
      run: () => {
        chat.newChat();
        navigate("chat");
      },
    },
    {
      id: "cycle-appearance",
      label: "Cycle appearance",
      hint: `Currently ${appearance}`,
      group: "Do",
      keywords: "theme dark light system",
      run: () => setAppearance(NEXT_APPEARANCE[appearance]),
    },
    {
      id: "settings",
      label: "Open settings",
      hint: "Theme, model, routing and shortcuts",
      group: "Do",
      keywords: "options panel preferences",
      run: () => setPanelOpen(true),
    },
    {
      id: "refresh",
      label: "Refresh from the engine",
      hint: "Re-read every screen",
      group: "Do",
      keywords: "reload sync pull",
      run: () => void refresh(),
    },
    ...NAV_GROUPS.flatMap((group) =>
      group.items.map<PaletteCommand>((item) => ({
        id: `go-${item}`,
        label: `Go to ${NAV_LABELS[item]}`,
        hint: group.label,
        group: "Go",
        run: () => navigate(item),
      })),
    ),
  ];

  return (
    <div
      className="app"
      data-shell={shell}
      data-theme={theme}
      data-mode={appearanceMode}
      data-glass={look.glass ? "on" : "off"}
      data-motion={look.motion ? "on" : "off"}
      data-caption={look.caption}
      data-scale={look.scale}
      data-density={look.density}
      data-sidebar={collapsed ? "collapsed" : "expanded"}
      data-chat-focus={focusedChat ? "on" : "off"}
    >
      <ConfirmProvider>
        {menuOpen && (
          <button
            type="button"
            className="rail-scrim"
            aria-label="close menu"
            onClick={() => setMenuOpen(false)}
          />
        )}
        <nav
          id="kira-rail"
          className="rail"
          aria-label="Kira sections"
          data-open={menuOpen ? "on" : "off"}
        >
          <div className="rail-brand">
            {!focusedChat && (
              <ShellSwitch
                shell={shell}
                connected={connected}
                onSwitch={() => setMenuOpen(false)}
              />
            )}
            <strong>{focusedChat ? "Sections" : "Kira"}</strong>
            {shell === "agent" && (
              <button
                type="button"
                className="sidebar-toggle"
                aria-pressed={collapsed}
                aria-label={collapsed ? "expand sidebar" : "collapse sidebar"}
                onClick={toggleSidebar}
              >
                {collapsed ? (
                  <PanelLeftOpen size={15} />
                ) : (
                  <PanelLeftClose size={15} />
                )}
              </button>
            )}
          </div>
          {NAV_GROUPS.map((group) => (
            <div className="nav-group" key={group.label}>
              <p className="nav-group-label">{group.label}</p>
              {group.items.map((item) => (
                <button
                  key={item}
                  type="button"
                  aria-label={NAV_LABELS[item]}
                  className={item === route ? "rail-active" : ""}
                  aria-current={item === route ? "page" : undefined}
                  onPointerEnter={() => preloadRoute(item)}
                  onFocus={() => preloadRoute(item)}
                  onClick={() => {
                    setMenuOpen(false);
                    navigate(item);
                  }}
                >
                  <NavIcon route={item} />
                  <span className="rail-label">{NAV_LABELS[item]}</span>
                </button>
              ))}
            </div>
          ))}
          <span className="spacer" />
          <button
            type="button"
            aria-label="refresh"
            onClick={() => void refresh()}
          >
            <RefreshCw size={15} aria-hidden="true" />
            <span className="rail-label">refresh</span>
          </button>
          <button
            type="button"
            aria-label="disconnect"
            onClick={() => {
              localStorage.removeItem(TOKEN_KEY);
              setToken("");
              setConnected(false);
            }}
          >
            <LogOut size={15} aria-hidden="true" />
            <span className="rail-label">disconnect</span>
          </button>
        </nav>
        <div className="pane">
          {shellIssue && (
            <p className="error engine-issue" role="alert">
              {shellIssue}
            </p>
          )}
          {focusedChat ? (
            <header className="chat-bar">
              <button
                type="button"
                className="chat-menu"
                aria-label="open sections"
                aria-expanded={menuOpen}
                aria-controls="kira-rail"
                onClick={() => setMenuOpen((open) => !open)}
              >
                <MenuIcon size={17} aria-hidden="true" />
              </button>
              <div className="chat-brand">
                <strong>Kira</strong>
              </div>
              <ShellSwitch
                shell={shell}
                connected={connected}
                onSwitch={() => setMenuOpen(false)}
              />
              <span className="spacer" />
              <div className="chat-pickers">
                {routingPicker}
                {modelPicker}
              </div>
              <button
                type="button"
                className="bar-appearance bar-command"
                aria-label="open command palette"
                title="Command palette (Ctrl K)"
                onClick={() => setPaletteOpen(true)}
              >
                <CommandIcon size={15} aria-hidden="true" />
              </button>
              {chat.entries.length > 0 && (
                <button
                  type="button"
                  className="bar-appearance bar-export"
                  aria-label="export conversation"
                  title="Export this conversation as Markdown"
                  onClick={exportConversation}
                >
                  <Download size={15} aria-hidden="true" />
                </button>
              )}
              {appearanceButton}
              {settingsButton}
              {versionBadge}
            </header>
          ) : (
            <header className="bar">
              {/* The screen below owns the page title. Repeating it here put two identical h2-sized
                  words on one screen and made the workspace look like a frame inside a frame. */}
              <div className="bar-context">
                <span className="bar-eyebrow">Agent workspace</span>
              </div>
              {routingPicker}
              {modelPicker}
              <span className="spacer" />
              {appearanceButton}
              {settingsButton}
              {versionBadge}
            </header>
          )}
          <ScreenBoundary key={route}>
          <Suspense
            fallback={
              <section className="screen route-loading" role="status">
                <p className="muted">loading…</p>
              </section>
            }
          >
          {route === "chat" ? (
            <ChatScreen
              chat={chat}
              shell={shell}
              models={models}
              mode={mode}
              model={model}
              modelChoices={modelChoices}
            />
          ) : route === "call" ? (
            // Its own `useCall`, deliberately not shared with `useChat`: a call answers out loud and
            // needs a socket per turn, and one turn cannot be in two places at once. Chat keeps its
            // history; the call writes to the engine, and the Sessions screen is where they meet.
            <CallScreen
              client={client}
              token={token}
              model={model}
              mode={mode}
            />
          ) : route === "images" ? (
            <ImagesScreen client={client} connected={connected} pull={pull} />
          ) : route === "studio" ? (
            <StudioScreen
              client={client}
              connected={connected}
              pull={pull}
              onChanged={voidRefresh}
            />
          ) : route === "overview" ? (
            <OverviewScreen
              client={client}
              pull={pull}
              onOpenSession={openSessionTranscript}
            />
          ) : route === "models" ? (
            <ModelsScreen
              client={client}
              models={models}
              pull={pull}
              onUse={useInChat}
            />
          ) : route === "providers" ? (
            <ProvidersScreen
              client={client}
              pull={pull}
              onChanged={voidRefresh}
            />
          ) : route === "tools" ? (
            <ToolsScreen client={client} connected={connected} pull={pull} />
          ) : route === "prompts" ? (
            <PromptsScreen
              onUse={(text) => {
                chat.setPrompt(text);
                navigate("chat");
              }}
            />
          ) : route === "skills" ? (
            <SkillsScreen
              client={client}
              connected={connected}
              onUse={(name) => {
                chat.setSkill(name);
                navigate("chat");
              }}
            />
          ) : route === "memory" ? (
            <MemoryScreen client={client} connected={connected} pull={pull} />
          ) : route === "avatar" ? (
            // No `onUse` and no chat coupling: a pick is the engine's own state, so the stage and the
            // call read it from the same route rather than from anything this screen holds.
            <AvatarScreen client={client} connected={connected} pull={pull} />
          ) : route === "remote" ? (
            <RemoteScreen client={client} connected={connected} pull={pull} />
          ) : (
            <SessionsScreen
              client={client}
              focusId={focusSession}
              onChanged={voidRefresh}
              pull={pull}
            />
          )}
          </Suspense>
          </ScreenBoundary>
        </div>
        {shell === "agent" && (
          <AgentPanel
            chat={chat}
            model={model}
            mode={mode}
            client={client}
            modelChoices={modelChoices}
          />
        )}
        <nav className="phone-bar" aria-label="Kira sections on a phone">
          {PHONE_ROUTES.map((item) => (
            <button
              key={item}
              type="button"
              aria-label={NAV_LABELS[item]}
              className={item === route ? "rail-active" : ""}
              aria-current={item === route ? "page" : undefined}
              onClick={() => navigate(item)}
            >
              <NavIcon route={item} />
              <span>{NAV_LABELS[item]}</span>
            </button>
          ))}
          <button
            type="button"
            aria-label="Menu"
            aria-expanded={menuOpen}
            aria-controls="kira-rail"
            onClick={() => setMenuOpen((open) => !open)}
          >
            <MenuIcon size={15} aria-hidden="true" />
            <span>Menu</span>
          </button>
        </nav>
        <CommandPalette
          open={paletteOpen}
          commands={paletteCommands}
          onClose={() => setPaletteOpen(false)}
        />
        <OptionsPanel
          open={panelOpen}
          onClose={() => setPanelOpen(false)}
          shell={shell}
          theme={theme}
          look={look}
          mode={mode}
          setMode={setMode}
          models={models}
          model={model}
          setModel={setModel}
          health={chat.health}
          sessionId={chat.sessionId}
          sessionCount={chat.sessions.length}
          onRefresh={voidRefresh}
          onDisconnect={() => {
            localStorage.removeItem(TOKEN_KEY);
            setToken("");
            setConnected(false);
            setPanelOpen(false);
          }}
        />
      </ConfirmProvider>
    </div>
  );
}

function messageOf(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}
