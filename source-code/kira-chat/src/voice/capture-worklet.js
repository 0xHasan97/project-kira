/**
 * Mic capture, in the audio thread.
 *
 * `/v1/voice` wants 16 kHz mono PCM in 100 ms packets, so 1600 samples per post. This runs as a
 * worklet because the main thread cannot promise a callback every 128 samples; the buffer is filled
 * across quanta, so a packet is exactly 100 ms however the browser chunks the input.
 */
class KiraCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Float32Array(1600);
    this.offset = 0;
  }
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;
    for (let index = 0; index < channel.length; index += 1) {
      this.buffer[this.offset] = channel[index];
      this.offset += 1;
      if (this.offset === this.buffer.length) {
        const out = new Int16Array(this.buffer.length);
        for (let at = 0; at < out.length; at += 1) {
          out[at] = Math.max(-32768, Math.min(32767, Math.round(this.buffer[at] * 32767)));
        }
        // Transfer, do not copy: a call posts ten of these every second.
        this.port.postMessage(out, [out.buffer]);
        this.offset = 0;
      }
    }
    return true;
  }
}
registerProcessor("kira-capture", KiraCapture);
