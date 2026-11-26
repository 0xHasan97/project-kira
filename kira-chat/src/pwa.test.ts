import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const root = process.cwd();
const html = readFileSync(resolve(root, "index.html"), "utf8");
const manifest = JSON.parse(
  readFileSync(resolve(root, "public/manifest.webmanifest"), "utf8"),
);

function meta(name: string): string {
  // Prettier wraps long tag attributes onto their own lines; flatten before matching.
  const found = html
    .replace(/\s+/g, " ")
    .match(new RegExp(`<meta name="${name}" content="([^"]*)"`));
  expect(found, `index.html has no <meta name="${name}">`).not.toBeNull();
  return found![1]!;
}

function png(
  directory: string,
  name: string,
): { width: number; height: number; signature: string } {
  const bytes = readFileSync(join(directory, name));
  return {
    signature: bytes.subarray(0, 8).toString("latin1"),
    width: bytes.readUInt32BE(16),
    height: bytes.readUInt32BE(20),
  };
}

function icons(into: string): void {
  execFileSync(
    process.execPath,
    [resolve(root, "scripts/make-icons.mjs"), "--out", into],
    {
      cwd: root,
      stdio: "pipe",
    },
  );
}

describe("the installable bundle", () => {
  it("links a manifest, from the bundle's own directory", () => {
    expect(html).toContain('<link rel="manifest" href="manifest.webmanifest"');
  });

  it("declares an app that opens on the chat route, inside /chat/", () => {
    expect(manifest.name).toBe("Kira");
    expect(manifest.short_name).toBe("Kira");
    expect(manifest.start_url).toBe("/chat/#/chat");
    expect(manifest.scope).toBe("/chat/");
    expect(manifest.display).toBe("standalone");
    expect(manifest.theme_color).toBe("#0f1113");
    expect(manifest.background_color).toBe("#0f1113");
  });

  it("names the three icons Android needs, including one the launcher may mask", () => {
    const icons = manifest.icons as {
      src: string;
      sizes: string;
      purpose?: string;
    }[];
    expect(icons.map((icon) => icon.sizes)).toEqual([
      "192x192",
      "512x512",
      "512x512",
    ]);
    expect(icons.map((icon) => icon.src)).toEqual([
      "icons/icon-192.png",
      "icons/icon-512.png",
      "icons/icon-maskable-512.png",
    ]);
    expect(icons[2]!.purpose).toBe("maskable");
  });

  it("lets a phone page reach the notch and paint the status bar to match", () => {
    expect(meta("viewport")).toContain("viewport-fit=cover");
    expect(meta("theme-color")).toBe("#0f1113");
    expect(meta("apple-mobile-web-app-capable")).toBe("yes");
    expect(meta("apple-mobile-web-app-title")).toBe("Kira");
    expect(html).toContain(
      '<link rel="apple-touch-icon" href="icons/icon-180.png"',
    );
  });
});

describe("icons, generated from code", () => {
  const one = mkdtempSync(join(tmpdir(), "kira-icons-"));
  const two = mkdtempSync(join(tmpdir(), "kira-icons-"));

  it("writes the four files the manifest and iOS ask for, at the right sizes", () => {
    icons(one);
    expect(png(one, "icon-192.png")).toMatchObject({
      signature: "\x89PNG\r\n\x1a\n",
      width: 192,
      height: 192,
    });
    expect(png(one, "icon-512.png")).toMatchObject({ width: 512, height: 512 });
    expect(png(one, "icon-maskable-512.png")).toMatchObject({
      width: 512,
      height: 512,
    });
    expect(png(one, "icon-180.png")).toMatchObject({ width: 180, height: 180 });
  });

  it("is deterministic, so a rebuild is not a new binary every time", () => {
    icons(two);
    for (const name of [
      "icon-192.png",
      "icon-512.png",
      "icon-maskable-512.png",
      "icon-180.png",
    ]) {
      expect(
        readFileSync(join(two, name)).equals(readFileSync(join(one, name))),
        name,
      ).toBe(true);
    }
  });
});
