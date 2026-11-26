import { useState } from "react";
import type { KiraClient } from "../api.ts";
import type { SkillInfo, SkillsResponse } from "../contracts.ts";
import { useAsync } from "../useAsync.ts";

const EMPTY: SkillsResponse = { skills: [], files: [], discovery: "inline" };
const KINDS = ["all", "persona", "method"] as const;

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function matches(skill: SkillInfo, needle: string): boolean {
  if (!needle) return true;
  return skill.name.toLowerCase().includes(needle) || skill.description.toLowerCase().includes(needle);
}

/** One line, in the engine's words, about how a model reaches a method this turn. */
function discoveryLine(response: SkillsResponse): string {
  const methods = response.skills.filter((skill) => skill.kind === "method").length;
  if (methods === 0) {
    return "no method is installed, so the model has nothing to pull and use_skill is not registered";
  }
  if (response.discovery === "search") {
    return `${methods} methods are installed — too many to name on every turn, so the model finds one with the search_skills tool and loads it by the exact name it was given`;
  }
  return `the ${methods} method${methods === 1 ? "" : "s"} are listed in the use_skill tool, so the model can pick one by name without searching`;
}

export function SkillsScreen({
  client,
  connected,
  onUse,
  pull = 0,
}: {
  client: KiraClient;
  connected: boolean;
  /** Personas only: a method is loaded by the model through `use_skill`, not pinned to a turn. */
  onUse: (name: string) => void;
  pull?: number;
}) {
  const pack = useAsync(() => (connected ? client.skills() : Promise.resolve(EMPTY)), [connected, pull]);
  const [needle, setNeedle] = useState("");
  const [kind, setKind] = useState<(typeof KINDS)[number]>("all");

  const data = pack.kind === "ready" ? pack.data : EMPTY;
  const wanted = data.skills.filter(
    (skill) => (kind === "all" || skill.kind === kind) && matches(skill, needle.toLowerCase()),
  );
  const refusals = data.files.filter((file) => file.status !== "loaded");

  return (
    <section className="screen" aria-label="skills">
      <h2>Skills</h2>

      {pack.kind === "loading" ? <p className="muted">reading the skill pack…</p> : null}
      {pack.kind === "error" ? (
        <p className="error" role="alert">
          cannot read the skill pack: {messageOf(pack.error)}
        </p>
      ) : null}

      {pack.kind === "ready" && (
        <>
          {data.skills.length > 0 && (
            <div className="filters">
              <input
                aria-label="search skills"
                placeholder="search skills"
                value={needle}
                onChange={(event) => setNeedle(event.target.value)}
              />
              <select
                aria-label="kind"
                value={kind}
                onChange={(event) => setKind(event.target.value as (typeof KINDS)[number])}
              >
                {KINDS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </div>
          )}

          <p className="muted small">
            {data.skills.length} loaded
            {refusals.length > 0 ? ` · ${refusals.length} file(s) refused` : ""} · {discoveryLine(data)}.
          </p>

          <table className="grid">
            <thead>
              <tr><th>skill</th><th>kind</th><th>source</th><th>size</th><th /></tr>
            </thead>
            <tbody>
              {wanted.map((skill) => (
                <tr key={`${skill.source}:${skill.name}`}>
                  <td>
                    <div className="mono">{skill.name}</div>
                    <div className="muted small">{skill.description}</div>
                  </td>
                  <td>{skill.kind}</td>
                  <td className="muted mono">{skill.source}</td>
                  <td className="muted mono">{skill.body_bytes} B</td>
                  <td>
                    {skill.kind === "persona" ? (
                      <button type="button" onClick={() => onUse(skill.name)}>
                        {`use ${skill.name}`}
                      </button>
                    ) : (
                      <span className="muted small">the model loads it</span>
                    )}
                  </td>
                </tr>
              ))}
              {data.skills.length === 0 && (
                <tr>
                  <td colSpan={5} className="empty">
                    no skills loaded — put a Markdown file with frontmatter at name.md or
                    skills/&lt;name&gt;/SKILL.md under data_dir/skills and restart the engine, or run
                    kira-engine skills install PATH with a pack.
                  </td>
                </tr>
              )}
              {data.skills.length > 0 && wanted.length === 0 && (
                <tr>
                  <td colSpan={5} className="empty">
                    nothing in these {data.skills.length} skills matches {needle ? `“${needle}”` : "that filter"}
                    {kind === "all" ? "" : ` as a ${kind}`}.
                  </td>
                </tr>
              )}
            </tbody>
          </table>

          <h3>files</h3>
          {data.files.length === 0 ? (
            <p className="empty">no skill files found.</p>
          ) : (
            <>
              <p className="muted small">
                {data.files.length - refusals.length} of {data.files.length} files read. A file that loaded
                needs no line here; the ones that did not are below.
              </p>
              {refusals.length > 0 && (
                <ul className="work-list">
                  {refusals.map((file) => (
                    <li key={`${file.source}:${file.file}`}>
                      <span className="mono">{file.file}</span> — {file.status}
                      {file.reason ? <span className="muted">: {file.reason}</span> : null}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}

          <p className="muted small">
            A persona is pinned to a turn and becomes its first instruction; a method is a procedure the
            model can pull on demand with the use_skill tool. A bad file is reported here and never stops
            the engine.
          </p>
        </>
      )}
    </section>
  );
}
