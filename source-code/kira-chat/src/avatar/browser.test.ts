import { SRGBColorSpace } from "three";
import { afterEach, describe, expect, it, vi } from "vitest";
import { browserImageTexture, createCanvasRenderer } from "./browser.ts";

/**
 * The browser-only half of the stage, tested at the two points where it can lie.
 *
 * A renderer that throws in a window with no GL turns the whole avatar screen into a crash page, and a
 * texture loader that never revokes its object URL keeps every diffuse map in memory after the body leaves
 * the stage. Both are answered here rather than in `AvatarStage.test.tsx`, whose fakes deliberately never
 * import this file.
 */
describe("the browser's half of the stage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("reports no 3D rather than throwing when the canvas has no context", () => {
    const canvas = document.createElement("canvas");
    canvas.width = 360;
    canvas.height = 480;
    // jsdom hands back null for `webgl`, which is the same answer a locked-down WebView2 gives, and three
    // raises on it. The caller's contract is a `null` it can show, not an exception it has to guess at.
    expect(canvas.getContext("webgl")).toBeNull();
    expect(createCanvasRenderer(canvas)).toBeNull();
  });

  it("wraps the bytes in the mime the file's own suffix names", () => {
    const seen: string[] = [];
    vi.stubGlobal("URL", fakeUrl(seen));

    browserImageTexture(new ArrayBuffer(8), "toon/スナップセット_01.bmp");
    browserImageTexture(new ArrayBuffer(8), "sp/托特_sph.tga");
    browserImageTexture(new ArrayBuffer(8), "sp/readme.unknown");

    expect(seen).toEqual(["image/bmp", "image/x-tga", "application/octet-stream"]);
  });

  it("gives the texture the model's own name and the colour space it was painted in", () => {
    vi.stubGlobal("URL", fakeUrl([]));

    const texture = browserImageTexture(new ArrayBuffer(8), "toon/default_toon.bmp");
    expect(texture.name).toBe("toon/default_toon.bmp");
    expect(texture.colorSpace).toBe(SRGBColorSpace);
  });

  it("revokes the object URL once the pixels have arrived", async () => {
    const revoked: string[] = [];
    decodesItself();
    vi.stubGlobal("URL", fakeUrl([], revoked));

    browserImageTexture(new ArrayBuffer(8), "toon/default_diffuse.png");
    await pixels();

    expect(revoked).toEqual(["blob:fake/1"]);
  });

  it("revokes the object URL when the picture will not decode either", async () => {
    const revoked: string[] = [];
    decodesItself(false);
    vi.stubGlobal("URL", fakeUrl([], revoked));

    browserImageTexture(new ArrayBuffer(8), "sp/missing_sph.tga");
    await pixels();

    // A leak on the error path is still a leak, and a broken texture reference is exactly the case this
    // app expects from an archive that shipped without its images.
    expect(revoked).toEqual(["blob:fake/1"]);
  });
});

/** An object-URL stand-in that records the mime each blob was wrapped as and each URL given back. */
function fakeUrl(mimes: string[], revoked: string[] = []) {
  return {
    createObjectURL: (blob: Blob) => {
      mimes.push(blob.type);
      return "blob:fake/1";
    },
    revokeObjectURL: (url: string) => {
      revoked.push(url);
    },
  };
}

/**
 * Answer the picture three asks for.
 *
 * `ImageLoader` builds its element with `document.createElementNS`, not `new Image()`, so the global class
 * is not the seam — the `src` setter is. jsdom never decodes anything, which is the same silence a broken
 * texture reference produces in a browser, minus the network: the element answers (or fails) on a
 * microtask after it is given a source.
 */
function decodesItself(decode = true) {
  vi.spyOn(HTMLImageElement.prototype, "src", "set").mockImplementation(function (this: HTMLImageElement) {
    queueMicrotask(() => this.dispatchEvent(new Event(decode ? "load" : "error")));
  });
}

async function pixels() {
  // One microtask for the fake decode, one for the loader's own chain before it reaches the callbacks.
  await Promise.resolve();
  await Promise.resolve();
}
