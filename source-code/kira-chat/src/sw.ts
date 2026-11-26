/** The parts of a worker host this module needs: a browser has them, a test can fake them. */
export interface WorkerHost {
  serviceWorker?: { register(url: string, options?: { scope?: string }): Promise<unknown> };
  isSecureContext?: boolean;
}

/**
 * A worker only exists in a secure context. Loopback is one; a plain-HTTP tunnel is not, and there
 * the app has to keep working without any of this.
 */
export function canRegister(host: WorkerHost): boolean {
  return typeof host.serviceWorker?.register === "function" && host.isSecureContext !== false;
}

/**
 * Registers the shell worker. Never throws: a worker is an improvement, and a refused registration
 * must leave a usable app behind, not a blank one.
 */
export async function registerShellWorker(host: WorkerHost = navigator): Promise<unknown> {
  if (!canRegister(host)) return null;
  try {
    return await host.serviceWorker!.register("/chat/sw.js", { scope: "/chat/" });
  } catch {
    return null;
  }
}
