import { describe, expect, it } from "vitest";
import {
  AUDIO_FRAME_HEADER_BYTES,
  REALTIME_VOICE_PROTOCOL_VERSION,
  AudioFrameKind,
  decodeAudioFrame,
  encodeAudioFrame,
} from "./protocol";

describe("Realtime Voice audio protocol", () => {
  it("round-trips the versioned big-endian header and PCM payload", () => {
    const payload = new Uint8Array([1, 0, 255, 127]).buffer;
    const encoded = encodeAudioFrame(
      AudioFrameKind.InputPcm16,
      42,
      16000,
      1,
      payload,
    );
    const decoded = decodeAudioFrame(encoded);

    expect(encoded.byteLength).toBe(AUDIO_FRAME_HEADER_BYTES + 4);
    expect(decoded).toMatchObject({
      kind: AudioFrameKind.InputPcm16,
      sequence: 42,
      sampleRate: 16000,
      channels: 1,
    });
    expect([...new Uint8Array(decoded.payload)]).toEqual([1, 0, 255, 127]);
  });

  it("rejects protocol version and length mismatches", () => {
    const encoded = encodeAudioFrame(
      AudioFrameKind.OutputPcm16,
      0,
      24000,
      1,
      new ArrayBuffer(2),
    );
    new DataView(encoded).setUint8(2, 99);
    expect(() => decodeAudioFrame(encoded)).toThrow("version");

    const truncated = encoded.slice(0, AUDIO_FRAME_HEADER_BYTES);
    new DataView(truncated).setUint8(2, REALTIME_VOICE_PROTOCOL_VERSION);
    expect(() => decodeAudioFrame(truncated)).toThrow("length");
  });
});
