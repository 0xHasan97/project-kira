/**
 * Incremental `text/event-stream` reader.
 *
 * Network chunks arrive at arbitrary byte boundaries, so a frame can be split across
 * two reads and a single read can carry several frames. This buffers until it sees a
 * blank line, which is the only place a frame is guaranteed to end.
 */
export class SseBuffer {
  private pending = "";

  push(text: string): string[] {
    this.pending += text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    const frames: string[] = [];
    let index = this.pending.indexOf("\n\n");
    while (index !== -1) {
      frames.push(...this.parseFrame(this.pending.slice(0, index)));
      this.pending = this.pending.slice(index + 2);
      index = this.pending.indexOf("\n\n");
    }
    return frames;
  }

  /** Bytes left over when the stream closed mid-frame; surfaced so a truncation is visible. */
  remainder(): string {
    return this.pending;
  }

  private parseFrame(frame: string): string[] {
    const dataLines: string[] = [];
    for (const line of frame.split("\n")) {
      if (!line || line.startsWith(":")) continue;
      if (!line.startsWith("data:")) continue;
      const value = line.slice(5).startsWith(" ") ? line.slice(6) : line.slice(5);
      dataLines.push(value);
    }
    if (dataLines.length === 0) return [];
    const joined = dataLines.join("\n");
    return joined === "[DONE]" ? [] : [joined];
  }
}
