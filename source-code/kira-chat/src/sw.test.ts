import { describe, expect, it, vi } from "vitest";
import { canRegister, registerShellWorker } from "./sw.ts";
import type { WorkerHost } from "./sw.ts";

function host(overrides: Partial<WorkerHost> = {}) {
  const register = vi.fn(async () => ({ scope: "/chat/" }));
  const container: WorkerHost = { serviceWorker: { register }, isSecureContext: true, ...overrides };
  return { container, register };
}

describe("shell worker registration", () => {
  it("registers the worker under /chat/ with a scope that covers the app", async () => {
    const { container, register } = host();
    await registerShellWorker(container);
    expect(register).toHaveBeenCalledTimes(1);
    expect(register).toHaveBeenCalledWith("/chat/sw.js", { scope: "/chat/" });
  });

  it("does nothing in a browser without service workers", async () => {
    expect(canRegister({ isSecureContext: true })).toBe(false);
    expect(await registerShellWorker({ isSecureContext: true })).toBeNull();
  });

  it("does nothing in an insecure context, where a worker cannot run at all", async () => {
    const { container, register } = host({ isSecureContext: false });
    expect(await registerShellWorker(container)).toBeNull();
    expect(register).not.toHaveBeenCalled();
  });

  it("treats a refused registration as no worker rather than a crashed app", async () => {
    const { container, register } = host();
    register.mockRejectedValueOnce(new Error("SecurityError"));
    await expect(registerShellWorker(container)).resolves.toBeNull();
  });
});
