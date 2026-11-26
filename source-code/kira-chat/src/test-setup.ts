import { afterEach, vi } from "vitest";
import { cleanup, configure } from "@testing-library/react";

// One second is testing-library's default, and it is a wall clock: with 37 jsdom environments being
// built on the same machine, a two-hop fake fetch can sit behind a starved timer long enough to lose
// a write that always arrives. The providers cap write failed roughly one run in two for that reason
// alone — never in isolation. The budget is not what these tests are about.
configure({ asyncUtilTimeout: 5000 });

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
