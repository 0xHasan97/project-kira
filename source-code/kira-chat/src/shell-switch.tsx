import { navigateShell, SHELLS, type Shell } from "./shell.ts";

/** Two positions, one component: both arrangements mount this in their own top-left slot. */
export function ShellSwitch({
  shell,
  connected,
  onSwitch,
}: {
  shell: Shell;
  connected: boolean;
  onSwitch?: () => void;
}) {
  return (
    <div className="shell-switch" role="group" aria-label="surface">
      <span className={`dot ${connected ? "on" : "off"}`} />
      {SHELLS.map((s) => (
        <button
          type="button"
          key={s}
          aria-pressed={s === shell}
          onClick={() => {
            navigateShell(s);
            onSwitch?.();
          }}
        >
          {s === "chat" ? "Chat" : "Agent"}
        </button>
      ))}
    </div>
  );
}
