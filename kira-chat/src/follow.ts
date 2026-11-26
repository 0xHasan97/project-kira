import { useCallback, useEffect, useRef, type RefObject } from "react";

// Within a thumb-flick of the end counts as the end: a token landing mid-read must not yank the
// page back down, and a reader who is looking at the last line should not have to chase it.
const SLACK = 96;

export interface ScrollBox {
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
}

export function atBottom(box: ScrollBox): boolean {
  return box.scrollHeight - box.scrollTop - box.clientHeight <= SLACK;
}

/** Keeps a growing thread pinned to its newest line until the reader scrolls up to read. */
export function useFollow(ref: RefObject<HTMLElement | null>, signal: unknown): () => void {
  const following = useRef(true);

  useEffect(() => {
    const box = ref.current;
    if (!box) return;
    const onScroll = () => {
      following.current = atBottom(box);
    };
    box.addEventListener("scroll", onScroll, { passive: true });
    return () => box.removeEventListener("scroll", onScroll);
  }, [ref]);

  useEffect(() => {
    const box = ref.current;
    if (box && following.current) box.scrollTop = box.scrollHeight;
  }, [ref, signal]);

  // Sending is a deliberate move to the conversation's end, whatever the reader was reading.
  return useCallback(() => {
    following.current = true;
    const box = ref.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [ref]);
}
