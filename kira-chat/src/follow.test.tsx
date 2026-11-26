import { fireEvent, render, screen } from "@testing-library/react";
import { useRef } from "react";
import { describe, expect, it } from "vitest";
import { atBottom, useFollow } from "./follow.ts";

function Box({ signal }: { signal: unknown }) {
  const ref = useRef<HTMLDivElement>(null);
  useFollow(ref, signal);
  return <div data-testid="thread" ref={ref} />;
}

/** jsdom lays nothing out, so the scroll geometry a real thread reports is spelled out here. */
function measure(element: HTMLElement, scrollHeight: number, clientHeight: number) {
  Object.defineProperty(element, "scrollHeight", { value: scrollHeight, configurable: true });
  Object.defineProperty(element, "clientHeight", { value: clientHeight, configurable: true });
}

describe("atBottom", () => {
  it("counts a box within a glance of the end as being at the end", () => {
    // 500 - 200 - 96: exactly one slack above the end.
    expect(atBottom({ scrollTop: 204, scrollHeight: 500, clientHeight: 200 })).toBe(true);
    expect(atBottom({ scrollTop: 203, scrollHeight: 500, clientHeight: 200 })).toBe(false);
  });

  it("treats a box shorter than its view as already at the end", () => {
    expect(atBottom({ scrollTop: 0, scrollHeight: 120, clientHeight: 200 })).toBe(true);
  });
});

describe("useFollow", () => {
  it("keeps the newest turn in view as the thread grows", () => {
    const view = render(<Box signal="a" />);
    const thread = screen.getByTestId("thread");
    measure(thread, 900, 300);

    view.rerender(<Box signal="b" />);

    expect(thread.scrollTop).toBe(900);
  });

  it("leaves the reader alone once they scroll back through the transcript", () => {
    const view = render(<Box signal="a" />);
    const thread = screen.getByTestId("thread");
    measure(thread, 900, 300);
    thread.scrollTop = 0;

    fireEvent.scroll(thread);
    view.rerender(<Box signal="b" />);

    expect(thread.scrollTop).toBe(0);
  });

  it("follows again when the reader comes back to the bottom", () => {
    const view = render(<Box signal="a" />);
    const thread = screen.getByTestId("thread");
    measure(thread, 900, 300);
    thread.scrollTop = 0;
    fireEvent.scroll(thread);

    thread.scrollTop = 700;
    fireEvent.scroll(thread);
    view.rerender(<Box signal="b" />);

    expect(thread.scrollTop).toBe(900);
  });
});
