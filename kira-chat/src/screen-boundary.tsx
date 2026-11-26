import { Component } from "react";
import type { ReactNode } from "react";

/**
 * A screen is a route chunk now. A chunk that never arrived — the engine went away before the route
 * was visited, or a build changed under an old tab — used to reject the lazy import and take the whole
 * shell down with it. Catching it here keeps the rail and the composer alive and says what happened.
 */
export class ScreenBoundary extends Component<
  { children: ReactNode },
  { problem: string | null }
> {
  state = { problem: null as string | null };

  static getDerivedStateFromError(error: unknown) {
    return { problem: error instanceof Error ? error.message : String(error) };
  }

  render() {
    if (this.state.problem !== null) {
      return (
        <section className="screen" role="alert">
          <p className="error">This screen could not load: {this.state.problem}</p>
          <p className="muted">
            A route is fetched separately. If the engine stopped before this screen was cached,
            start it again and reload.
          </p>
          <button type="button" onClick={() => window.location.reload()}>
            reload
          </button>
        </section>
      );
    }
    return this.props.children;
  }
}
