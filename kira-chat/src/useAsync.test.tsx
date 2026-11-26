import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useAsync } from "./useAsync.ts";

describe("useAsync", () => {
  it("goes loading -> ready and keeps the data", async () => {
    const load = vi.fn(async () => ({ n: 1 }));
    const { result } = renderHook(() => useAsync(load, []));
    expect(result.current.kind).toBe("loading");
    await waitFor(() => expect(result.current.kind).toBe("ready"));
    expect(result.current.data).toEqual({ n: 1 });
    expect(result.current.error).toBeNull();
  });

  it("surfaces the rejection instead of an empty screen", async () => {
    const { result } = renderHook(() => useAsync(async () => { throw new Error("engine down"); }, []));
    await waitFor(() => expect(result.current.kind).toBe("error"));
    expect((result.current.error as Error).message).toBe("engine down");
    expect(result.current.data).toBeNull();
  });

  it("re-loads when a dependency changes, and refresh() reloads on demand", async () => {
    let n = 0;
    const load = vi.fn(async () => ++n);
    const { result, rerender } = renderHook(({ month }: { month: string }) => useAsync(load, [month]), {
      initialProps: { month: "2026-10" },
    });
    await waitFor(() => expect(result.current.data).toBe(1));
    rerender({ month: "2026-09" });
    await waitFor(() => expect(result.current.data).toBe(2));
    act(() => result.current.refresh());
    await waitFor(() => expect(result.current.data).toBe(3));
    expect(load).toHaveBeenCalledTimes(3);
  });

  it("ignores a response that lands after the screen moved on", async () => {
    // One handle per call: the rerender starts a second request, so a single shared `release`
    // would resolve the current one and prove nothing about the stale one.
    const resolvers: ((value: number) => void)[] = [];
    const load = vi.fn(() => new Promise<number>((resolve) => { resolvers.push(resolve); }));
    const { result, rerender } = renderHook(({ k }: { k: number }) => useAsync(load, [k]), {
      initialProps: { k: 1 },
    });
    rerender({ k: 2 });
    await act(async () => { resolvers[0](1); });
    expect(result.current.kind).toBe("loading");
    await act(async () => { resolvers[1](2); });
    expect(result.current.kind).toBe("ready");
    expect(result.current.data).toBe(2);
  });
});
