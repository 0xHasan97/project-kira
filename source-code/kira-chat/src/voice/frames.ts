/**
 * The webcam cadence.
 *
 * A call does not stream video: it takes one small JPEG every few seconds and hands it to the next
 * spoken turn. That is what keeps a vision call affordable, and it is why the interval lives here as
 * one constant the engine, the spec and the tests all agree on rather than a number in two places.
 */
export const FRAME_INTERVAL_MS = 4000;

/** Small on purpose: a frame is a glance at the room for a model, not a photo to keep. */
export const FRAME_WIDTH = 320;
export const FRAME_HEIGHT = 240;
export const FRAME_QUALITY = 0.6;

export function frameDue(lastSentAt: number, now: number, hidden = false, interval = FRAME_INTERVAL_MS): boolean {
  return !hidden && now - lastSentAt >= interval;
}

/**
 * The next frame as base64 JPEG, or null when there is nothing to draw yet.
 *
 * A video element reports zero size until the first frame decodes, so calling this too eagerly is
 * normal and returns null instead of a black rectangle the model would describe as a dark room.
 */
export function jpegFromVideo(video: HTMLVideoElement, canvas: HTMLCanvasElement): string | null {
  if (!video.videoWidth || !video.videoHeight) return null;
  canvas.width = FRAME_WIDTH;
  canvas.height = FRAME_HEIGHT;
  const context = canvas.getContext("2d");
  if (!context) return null;
  context.drawImage(video, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", FRAME_QUALITY).split(",", 2)[1] ?? null;
}
