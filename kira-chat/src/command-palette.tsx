import { useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";

export interface PaletteCommand {
  id: string;
  label: string;
  hint: string;
  group: "Do" | "Go";
  keywords?: string;
  run(): void;
}

export interface CommandPaletteProps {
  open: boolean;
  commands: readonly PaletteCommand[];
  onClose(): void;
}

const GROUPS = ["Do", "Go"] as const;
const GROUP_LABEL = { Do: "Actions", Go: "Go to" } as const;

/**
 * A keyboard-first index of the whole app. It closes before running because almost every command
 * moves the route or opens a sheet, and a palette left over either one would cover the result.
 */
export function CommandPalette({ open, commands, onClose }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActive(0);
    input.current?.focus();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  if (!open) return null;

  const needle = query.trim().toLowerCase();
  const matches = commands.filter((command) =>
    `${command.label} ${command.hint} ${command.keywords ?? ""}`
      .toLowerCase()
      .includes(needle),
  );
  const selected = Math.min(active, Math.max(matches.length - 1, 0));

  function run(command: PaletteCommand | undefined) {
    if (!command) return;
    onClose();
    command.run();
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive(matches.length ? (selected + 1) % matches.length : 0);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive(matches.length ? (selected - 1 + matches.length) % matches.length : 0);
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      run(matches[selected]);
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
    }
  }

  return (
    <div
      className="palette-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="palette-card"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
      >
        <div className="palette-search">
          <Search size={16} aria-hidden="true" />
          <input
            ref={input}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setActive(0);
            }}
            onKeyDown={onKeyDown}
            aria-label="Search commands"
            placeholder="Search routes and actions…"
            autoComplete="off"
            spellCheck={false}
          />
          <kbd>esc</kbd>
        </div>
        <div className="palette-body">
          {matches.length === 0 && (
            <p className="palette-empty">No route or action matches “{query.trim()}”.</p>
          )}
          {GROUPS.map((group) => {
            const rows = matches.filter((command) => command.group === group);
            if (rows.length === 0) return null;
            return (
              <div className="palette-group" key={group}>
                <p className="palette-group-label">{GROUP_LABEL[group]}</p>
                {rows.map((command) => {
                  const index = matches.indexOf(command);
                  return (
                    <button
                      key={command.id}
                      type="button"
                      className="palette-item"
                      aria-current={index === selected ? "true" : undefined}
                      onMouseEnter={() => setActive(index)}
                      onClick={() => run(command)}
                    >
                      <span className="palette-label">{command.label}</span>
                      <span className="palette-hint">{command.hint}</span>
                    </button>
                  );
                })}
              </div>
            );
          })}
        </div>
        <footer className="palette-foot">
          <span><kbd>↑</kbd><kbd>↓</kbd> move</span>
          <span><kbd>↵</kbd> open</span>
          <span><kbd>esc</kbd> close</span>
        </footer>
      </div>
    </div>
  );
}
