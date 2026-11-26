import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { KiraClient } from "../api.ts";
import { fakeEngine } from "../fake-engine.ts";
import { SkillsScreen } from "./SkillsScreen.tsx";

const SKILLS = {
  skills: [
    { name: "concise", description: "Answer in the fewest words that are still true.", kind: "persona", source: "builtin", body_bytes: 120 },
    { name: "debug", description: "Reproduce, observe, narrow, fix, prove.", kind: "method", source: "user", body_bytes: 300 },
  ],
  files: [
    { file: "concise.md", name: "concise", status: "loaded", reason: "", source: "builtin" },
    { file: "debug.md", name: "debug", status: "loaded", reason: "", source: "user" },
    { file: "broken.md", name: "broken", status: "skipped", reason: "frontmatter is not closed with a second ---", source: "user" },
  ],
  discovery: "inline",
};

function mount(skills: unknown = SKILLS, onUse = vi.fn()) {
  const engine = fakeEngine({ skills });
  const client = new KiraClient({ baseUrl: "http://127.0.0.1:8901", token: "t", fetch: engine.fetch });
  render(<SkillsScreen client={client} connected onUse={onUse} />);
  return { engine, onUse };
}

describe("SkillsScreen", () => {
  it("lists each skill with its kind and source", async () => {
    mount();
    expect(await screen.findByText("concise")).toBeTruthy();
    expect(await screen.findByText("Answer in the fewest words that are still true.")).toBeTruthy();
    expect(screen.getByText("debug")).toBeTruthy();
    expect(screen.getByText("Reproduce, observe, narrow, fix, prove.")).toBeTruthy();
  });

  it("offers use for a persona and not for a method, because the model loads a method itself", async () => {
    const { onUse } = mount();
    const use = await screen.findByRole("button", { name: /use concise/i });
    expect(screen.queryByRole("button", { name: /use debug/i })).toBeNull();
    fireEvent.click(use);
    expect(onUse).toHaveBeenCalledWith("concise");
  });

  it("shows why a file was skipped instead of hiding it", async () => {
    mount();
    expect(await screen.findByText(/broken\.md/)).toBeTruthy();
    expect(screen.getByText(/frontmatter is not closed/)).toBeTruthy();
  });

  it("narrows the pack when a search is typed, because an imported one is hundreds of rows wide", async () => {
    mount();
    fireEvent.change(await screen.findByLabelText("search skills"), { target: { value: "reproduce" } });
    expect(screen.getByText("debug")).toBeTruthy();
    expect(screen.queryByText("concise")).toBeNull();
  });

  it("filters by kind", async () => {
    mount();
    fireEvent.change(await screen.findByLabelText("kind"), { target: { value: "persona" } });
    expect(screen.getByText("concise")).toBeTruthy();
    expect(screen.queryByText("debug")).toBeNull();
  });

  it("says that nothing matches instead of showing an empty table", async () => {
    mount();
    fireEvent.change(await screen.findByLabelText("search skills"), { target: { value: "vector" } });
    expect(await screen.findByText(/nothing in these 2 skills matches/)).toBeTruthy();
  });

  it("names search_skills as the way in once the pack is past the inline limit", async () => {
    mount({ ...SKILLS, discovery: "search" });
    expect(await screen.findByText(/search_skills/)).toBeTruthy();
  });

  it("lists only the files that did not load, and counts the ones that did", async () => {
    mount();
    expect(await screen.findByText(/2 of 3 files read/)).toBeTruthy();
    expect(screen.getByText(/broken\.md/)).toBeTruthy();
    expect(screen.queryByText(/concise\.md/)).toBeNull();
  });

  it("says where to put a pack when the directory is empty", async () => {
    mount({ skills: [], files: [], discovery: "none" });
    expect(await screen.findByText(/data_dir\/skills/)).toBeTruthy();
  });

  it("reports a read failure instead of an empty pack", async () => {
    const engine = fakeEngine({ skillsError: true });
    const client = new KiraClient({ baseUrl: "http://127.0.0.1:8901", token: "t", fetch: engine.fetch });
    render(<SkillsScreen client={client} connected onUse={vi.fn()} />);
    expect(await screen.findByRole("alert")).toBeTruthy();
  });
});
