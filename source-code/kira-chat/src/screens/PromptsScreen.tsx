import { useState } from "react";
import type { FormEvent } from "react";
import { Plus, Search, Sparkles, Trash2 } from "lucide-react";

/**
 * A prompt is a starting instruction, not a conversation. Ported from project-Mia's
 * prompt library and one-click automations: the donor kept both in JSON beside the
 * app and substituted {vars} before sending. Kira keeps the same shape with no
 * engine route — a prompt never leaves this browser until its text is sent as a turn.
 */
export type PromptCategory = "Everyday" | "Code" | "Research" | "Automation";
export const PROMPT_CATEGORIES: readonly PromptCategory[] = [
  "Everyday",
  "Code",
  "Research",
  "Automation",
];

export interface Prompt {
  id: string;
  title: string;
  hint: string;
  body: string;
  category: PromptCategory;
  builtin?: boolean;
}

const STORE_KEY = "kira.prompts";
const MAX_CUSTOM = 40;
const MAX_TITLE = 60;
const MAX_BODY = 4000;

export const BUILTIN_PROMPTS: readonly Prompt[] = [
  {
    id: "summarize",
    title: "Summarize",
    hint: "Three sentences, no preamble.",
    body: "Summarize the following in three sentences. No preamble.\n\n",
    category: "Everyday",
    builtin: true,
  },
  {
    id: "translate-es",
    title: "Translate to Spanish",
    hint: "Fluent Spanish; names and code unchanged.",
    body: "Translate the following into fluent Spanish. Keep names, code and numbers unchanged.\n\n",
    category: "Everyday",
    builtin: true,
  },
  {
    id: "eli5",
    title: "Explain like I'm 5",
    hint: "One concrete analogy, no jargon.",
    body: "Explain the following as if I were five, with one concrete analogy.\n\n",
    category: "Everyday",
    builtin: true,
  },
  {
    id: "code-review",
    title: "Code review",
    hint: "Correctness first, then clarity, with lines.",
    body: "Review this code for correctness, then for clarity. Name the file and line for every finding. Do not rewrite it unless I ask.\n\n",
    category: "Code",
    builtin: true,
  },
  {
    id: "rewrite-formal",
    title: "Rewrite formally",
    hint: "Professional language, same facts.",
    body: "Rewrite the following in formal, professional language. Keep the meaning and every fact.\n\n",
    category: "Everyday",
    builtin: true,
  },
  {
    id: "actions",
    title: "Extract action items",
    hint: "Owner and due date when stated.",
    body: "Extract every action item from the following. Give the owner and due date when stated; write unknown when they are not.\n\n",
    category: "Everyday",
    builtin: true,
  },
  {
    id: "summarize-url",
    title: "Summarize a URL",
    hint: "Main points, separate from inference.",
    body: "Fetch and summarize the main points from: {url}\n\nSeparate what the page says from what you infer.",
    category: "Automation",
    builtin: true,
  },
  {
    id: "explain-code",
    title: "Explain code",
    hint: "Line by line, including failure paths.",
    body: "Explain what this code does, line by line. Call out side effects and failure paths.\n\n{code}",
    category: "Automation",
    builtin: true,
  },
  {
    id: "draft-reply",
    title: "Draft a reply",
    hint: "Short, professional, answers every question.",
    body: "Draft a professional reply to this message. Keep it short and answer every question.\n\n{message}",
    category: "Automation",
    builtin: true,
  },
  {
    id: "plan-change",
    title: "Plan a change",
    hint: "Files, tests and rollback before code.",
    body: "Plan this change before touching code:\n\n{goal}\n\nList the files, the tests and the rollback. Do not write code yet.",
    category: "Code",
    builtin: true,
  },
  {
    id: "debug-error",
    title: "Debug an error",
    hint: "Evidence, cause, smallest fix.",
    body: "Find the cause of this error. State the evidence, the likely cause, and the smallest fix. Do not guess silently.\n\n{error}",
    category: "Code",
    builtin: true,
  },
  {
    id: "research-brief",
    title: "Research brief",
    hint: "Answer first, evidence second, unknowns last.",
    body: "Research this question and write a brief:\n\n{question}\n\nAnswer first, then the evidence, then what remains unknown. Label every claim seen, inferred or unknown.",
    category: "Research",
    builtin: true,
  },
];

/** `{name}` placeholders, in first-appearance order, with duplicates removed. */
export function variablesIn(body: string): string[] {
  const found: string[] = [];
  for (const match of body.matchAll(/\{([a-zA-Z][a-zA-Z0-9_]*)\}/g)) {
    if (!found.includes(match[1])) found.push(match[1]);
  }
  return found;
}

export function fillPrompt(body: string, values: Record<string, string>): string {
  return body.replace(/\{([a-zA-Z][a-zA-Z0-9_]*)\}/g, (whole, name: string) => {
    const value = values[name]?.trim();
    return value ? value : whole;
  });
}

function readCustom(): Prompt[] {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((row): row is Record<string, unknown> => !!row && typeof row === "object")
      .map((row) => ({
        id: String(row.id ?? ""),
        title: String(row.title ?? "").slice(0, MAX_TITLE),
        hint: String(row.hint ?? "Saved prompt").slice(0, 120),
        body: String(row.body ?? "").slice(0, MAX_BODY),
        category: PROMPT_CATEGORIES.includes(row.category as PromptCategory)
          ? (row.category as PromptCategory)
          : "Everyday",
      }))
      .filter((row) => row.id && row.title.trim() && row.body.trim())
      .slice(0, MAX_CUSTOM);
  } catch {
    return [];
  }
}

function rememberCustom(prompts: Prompt[]): void {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(prompts));
  } catch {
    // A full or disabled store costs the save, not the prompt already on screen.
  }
}

function PromptCard({
  prompt,
  onUse,
  onDelete,
}: {
  prompt: Prompt;
  onUse: (text: string) => void;
  onDelete?: () => void;
}) {
  const variables = variablesIn(prompt.body);
  const [values, setValues] = useState<Record<string, string>>({});
  const ready = variables.every((name) => (values[name] ?? "").trim().length > 0);

  return (
    <article className="prompt-card">
      <header className="prompt-head">
        <span className="prompt-tag">{prompt.category}</span>
        {onDelete ? (
          <button
            type="button"
            className="prompt-delete"
            aria-label={`delete ${prompt.title}`}
            title="delete this prompt"
            onClick={onDelete}
          >
            <Trash2 size={13} aria-hidden="true" />
          </button>
        ) : null}
      </header>
      <h3>{prompt.title}</h3>
      <p className="prompt-hint">{prompt.hint}</p>
      {variables.length > 0 && (
        <div className="prompt-values">
          {variables.map((name) => (
            <label key={name}>
              <span>{name}</span>
              {name === "code" || name === "diff" ? (
                <textarea
                  aria-label={`${prompt.title} ${name}`}
                  rows={3}
                  value={values[name] ?? ""}
                  onChange={(event) =>
                    setValues((current) => ({ ...current, [name]: event.target.value }))
                  }
                />
              ) : (
                <input
                  aria-label={`${prompt.title} ${name}`}
                  value={values[name] ?? ""}
                  onChange={(event) =>
                    setValues((current) => ({ ...current, [name]: event.target.value }))
                  }
                />
              )}
            </label>
          ))}
        </div>
      )}
      <div className="prompt-actions">
        <button
          type="button"
          aria-label={`use ${prompt.title}`}
          disabled={!ready}
          onClick={() => onUse(fillPrompt(prompt.body, values))}
        >
          use
        </button>
      </div>
    </article>
  );
}

export function PromptsScreen({ onUse }: { onUse: (text: string) => void }) {
  const [custom, setCustom] = useState<Prompt[]>(readCustom);
  const [needle, setNeedle] = useState("");
  const [category, setCategory] = useState<PromptCategory | "all">("all");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [newCategory, setNewCategory] = useState<PromptCategory>("Everyday");
  const [formOpen, setFormOpen] = useState(false);

  const all = [...custom, ...BUILTIN_PROMPTS];
  const wanted = all.filter((prompt) => {
    if (category !== "all" && prompt.category !== category) return false;
    const q = needle.trim().toLowerCase();
    if (!q) return true;
    return [prompt.title, prompt.hint, prompt.body].some((text) =>
      text.toLowerCase().includes(q),
    );
  });

  function save(event: FormEvent) {
    event.preventDefault();
    const cleanTitle = title.trim();
    const cleanBody = body.trim();
    if (!cleanTitle || !cleanBody) return;
    const prompt: Prompt = {
      id: `custom-${Date.now().toString(36)}`,
      title: cleanTitle.slice(0, MAX_TITLE),
      hint: "Saved prompt",
      body: cleanBody.slice(0, MAX_BODY),
      category: newCategory,
    };
    const next = [prompt, ...custom].slice(0, MAX_CUSTOM);
    setCustom(next);
    rememberCustom(next);
    setTitle("");
    setBody("");
    setCategory(newCategory);
    setFormOpen(false);
  }

  function remove(id: string) {
    const next = custom.filter((prompt) => prompt.id !== id);
    setCustom(next);
    rememberCustom(next);
  }

  return (
    <section className="screen" aria-label="prompts">
      <h2>Prompts</h2>
      <p className="muted small">
        Saved instructions that start a turn. A prompt with {"{braces}"} asks for the missing
        value first; nothing is sent until you press use.
      </p>

      <div className="filters">
        <label className="prompt-search">
          <Search size={14} aria-hidden="true" />
          <input
            aria-label="search prompts"
            placeholder="search prompts"
            value={needle}
            onChange={(event) => setNeedle(event.target.value)}
          />
        </label>
        <select
          aria-label="prompt category"
          value={category}
          onChange={(event) => setCategory(event.target.value as PromptCategory | "all")}
        >
          <option value="all">all prompts</option>
          {PROMPT_CATEGORIES.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
        <button type="button" onClick={() => setFormOpen((open) => !open)}>
          <Plus size={14} aria-hidden="true" />
          new prompt
        </button>
      </div>

      {formOpen && (
        <form className="prompt-new" onSubmit={save}>
          <h3>New prompt</h3>
          <div className="prompt-new-row">
            <label>
              <span>title</span>
              <input
                aria-label="prompt title"
                maxLength={MAX_TITLE}
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="e.g. Meeting notes"
                autoFocus
              />
            </label>
            <label>
              <span>category</span>
              <select
                aria-label="new prompt category"
                value={newCategory}
                onChange={(event) => setNewCategory(event.target.value as PromptCategory)}
              >
                {PROMPT_CATEGORIES.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label>
            <span>instruction</span>
            <textarea
              aria-label="prompt instruction"
              rows={4}
              maxLength={MAX_BODY}
              value={body}
              onChange={(event) => setBody(event.target.value)}
              placeholder="Write the turn you want Kira to start. Use {name} for a value to fill in."
            />
          </label>
          <div className="prompt-new-actions">
            <button type="button" className="ghost" onClick={() => setFormOpen(false)}>
              cancel
            </button>
            <button type="submit" disabled={!title.trim() || !body.trim()}>
              save prompt
            </button>
          </div>
        </form>
      )}

      <p className="muted small">
        <Sparkles size={13} aria-hidden="true" /> {wanted.length} of {all.length} prompts
        {custom.length > 0 ? ` · ${custom.length} saved here` : ""}
      </p>

      <div className="prompt-grid">
        {wanted.map((prompt) => (
          <PromptCard
            key={prompt.id}
            prompt={prompt}
            onUse={onUse}
            onDelete={prompt.builtin ? undefined : () => remove(prompt.id)}
          />
        ))}
      </div>

      {wanted.length === 0 && (
        <p className="empty">
          nothing matches {needle.trim() ? `“${needle.trim()}”` : "that filter"} — clear the
          search or save a new prompt above.
        </p>
      )}
    </section>
  );
}
