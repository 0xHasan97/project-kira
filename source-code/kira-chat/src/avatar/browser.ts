/**
 * The two answers only a browser can give: pixels for a file, and a GL context for a scene.
 *
 * They sit behind one small module so `AvatarStage.tsx` — and with it `#/call` and `#/avatar` — can be
 * rendered in jsdom, where a canvas has no GL and a `.png` has no decoder. A test hands the component its
 * own fakes and never imports this file; the page hands it these.
 *
 * `createCanvasRenderer` fails to `null` rather than upward. A window with no 3D — a locked-down WebView2,
 * a blacklisted driver, a phone with the context budget spent — still gets the library, the walk, the pick
 * and the voice, and it is told in one line that the face cannot be drawn here. Pretending otherwise would
 * trade a working app for a stack trace.
 */

import { SRGBColorSpace, TextureLoader, WebGLRenderer } from "three";
import type { Texture } from "three";
import type { StageRenderer } from "./stage.ts";
import type { StageHost } from "./load.ts";

/** The mime a blob needs so an `<img>` will open it; the suffix is what the model's material named. */
const MIME: Record<string, string> = {
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  bmp: "image/bmp",
  webp: "image/webp",
  avif: "image/avif",
  gif: "image/gif",
  tga: "image/x-tga",
  dds: "image/vnd-ms.dds",
};

function mimeOf(relative: string): string {
  const suffix = relative.split(".").pop()?.toLowerCase() ?? "";
  return MIME[suffix] ?? "application/octet-stream";
}

/**
 * The page's answer to "here are the bytes of a texture".
 *
 * An object URL, not a data URL: a 2048×2048 diffuse map is 4 MB and base64 would make the string larger
 * than the file, in a page that has to keep every one of them alive while the body is on stage. The URL is
 * revoked the moment the image decodes — and on failure, because a leak on the error path is still a leak.
 *
 * The texture is returned before its pixels exist, which is how three has always worked: the material
 * updates when the image does.
 */
export function browserImageTexture(bytes: ArrayBuffer, relative: string): Texture {
  const url = URL.createObjectURL(new Blob([bytes], { type: mimeOf(relative) }));
  const release = () => URL.revokeObjectURL(url);
  const texture = new TextureLoader().load(url, release, undefined, release);
  // Diffuse maps are authored in sRGB; without this the face is drawn as if it were linear and reads as a
  // washed-out photocopy on every machine that colour-manages.
  texture.colorSpace = SRGBColorSpace;
  texture.name = relative;
  return texture;
}

export const browserStageHost: StageHost = { imageTexture: browserImageTexture };

/** The portrait the pane is drawn at: 3:4, matching the stage camera's aspect. */
export const STAGE_WIDTH = 360;
export const STAGE_HEIGHT = 480;

/**
 * Draw this scene into that canvas, or say this window cannot.
 *
 * The canvas carries its own size, so no layout is measured and nothing has to be re-fit when the pane
 * rescales: CSS makes it fit the column, and the drawing buffer stays 3:4 the way the camera expects.
 */
export function createCanvasRenderer(canvas: HTMLCanvasElement): StageRenderer | null {
  let renderer: WebGLRenderer;
  try {
    renderer = new WebGLRenderer({ canvas, antialias: true, alpha: true });
    renderer.setClearColor(0x000000, 0);
    renderer.outputColorSpace = SRGBColorSpace;
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    renderer.setSize(canvas.width || STAGE_WIDTH, canvas.height || STAGE_HEIGHT, false);
  } catch {
    // three throws when no context is available. That is an environment, not a bug in the body.
    return null;
  }
  return {
    draw: (scene, camera) => renderer.render(scene, camera),
    dispose: () => renderer.dispose(),
  };
}
