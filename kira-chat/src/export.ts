/** A conversation as a portable Markdown file: no engine route, no extra dependency. */

export interface TranscriptTurn {
  role: string;
  content: string;
  provider?: string | null;
  model?: string | null;
}

function speaker(role: string): string {
  if (role === "user") return "You";
  if (role === "assistant") return "Kira";
  if (role === "tool") return "Tool";
  return role;
}

/**
 * The same transcript the screen shows, with the routing evidence a reader would otherwise lose in a
 * screenshot. Timestamps are the export time, not a per-turn guess: the wire does not carry one for
 * every live entry, and inventing one would be worse than saying when the file was written.
 */
export function transcriptMarkdown(
  sessionId: string | null,
  turns: readonly TranscriptTurn[],
  exportedAt: Date = new Date(),
): string {
  const lines = [
    "# Kira conversation",
    "",
    `- Session: ${sessionId ? `\`${sessionId}\`` : "not saved yet"}`,
    `- Exported: ${exportedAt.toISOString()}`,
    `- Turns: ${turns.length}`,
    "",
  ];
  if (turns.length === 0) {
    lines.push("_No turns in this conversation._", "");
    return lines.join("\n");
  }
  turns.forEach((turn, index) => {
    lines.push(`## ${speaker(turn.role)}`, "");
    if (turn.role === "assistant" && (turn.provider || turn.model)) {
      lines.push(`_${[turn.provider, turn.model].filter(Boolean).join(" / ")}_`, "");
    }
    lines.push(turn.content.trim() || "_No text stored._", "");
    if (index < turns.length - 1) lines.push("---", "");
  });
  return lines.join("\n").trimEnd() + "\n";
}

function day(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export function transcriptFilename(
  sessionId: string | null,
  when: Date = new Date(),
): string {
  const safe = (sessionId ?? "chat")
    .replace(/[^a-zA-Z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48) || "chat";
  return `kira-${safe}-${day(when)}.md`;
}

/**
 * Save through a blob URL. The data-URL fallback is for the few webviews that do not implement
 * `createObjectURL`; a transcript is small, so the length limit there is not a practical concern.
 */
export function downloadTranscript(
  sessionId: string | null,
  turns: readonly TranscriptTurn[],
): void {
  const text = transcriptMarkdown(sessionId, turns);
  const filename = transcriptFilename(sessionId);
  const anchor = document.createElement("a");
  anchor.download = filename;
  anchor.rel = "noopener";
  let url: string | null = null;
  if (typeof URL.createObjectURL === "function") {
    const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
    url = URL.createObjectURL(blob);
    anchor.href = url;
  } else {
    anchor.href = `data:text/markdown;charset=utf-8,${encodeURIComponent(text)}`;
  }
  anchor.style.display = "none";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  if (url !== null) window.setTimeout(() => URL.revokeObjectURL(url!), 0);
}
