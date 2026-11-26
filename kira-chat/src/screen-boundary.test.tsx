import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ScreenBoundary } from "./screen-boundary.tsx";

function Bomb(): never {
  throw new Error("the chunk never arrived");
}

describe("ScreenBoundary", () => {
  afterEach(() => vi.restoreAllMocks());

  it("names the failure and keeps a reload within reach", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ScreenBoundary>
        <Bomb />
      </ScreenBoundary>,
    );
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("the chunk never arrived");
    expect(screen.getByRole("button", { name: "reload" })).toBeTruthy();
  });

  it("passes a screen that loads through untouched", () => {
    render(
      <ScreenBoundary>
        <p>the stage is here</p>
      </ScreenBoundary>,
    );
    expect(screen.getByText("the stage is here")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
