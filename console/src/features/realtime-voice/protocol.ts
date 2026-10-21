export const REALTIME_VOICE_PROTOCOL_VERSION = 2;
export const AUDIO_FRAME_HEADER_BYTES = 18;
export const MAX_AUDIO_PAYLOAD_BYTES = 256 * 1024;

const MAGIC_0 = "Q".charCodeAt(0);
const MAGIC_1 = "V".charCodeAt(0);

export const AudioFrameKind = {
  InputPcm16: 1,
  OutputPcm16: 2,
} as const;

export type AudioFrameKind =
  (typeof AudioFrameKind)[keyof typeof AudioFrameKind];

export interface DecodedAudioFrame {
  kind: AudioFrameKind;
  sequence: number;
  sampleRate: number;
  channels: number;
  payload: ArrayBuffer;
}

export interface RealtimeVoiceEvent {
  type: string;
  generation?: number;
  event_id?: string;
  input_id?: string;
  run_id?: string;
  status?: string;
  input_ids?: string[];
  revision?: number;
  text?: string;
  code?: string;
  message?: string;
  recoverable?: boolean;
  reason?: string;
  correlation_id?: string;
  response_origin?: "provider_auto" | "application";
  [key: string]: unknown;
}

export function encodeAudioFrame(
  kind: AudioFrameKind,
  sequence: number,
  sampleRate: number,
  channels: number,
  payload: ArrayBuffer,
): ArrayBuffer {
  if (payload.byteLength > MAX_AUDIO_PAYLOAD_BYTES) {
    throw new Error("Audio frame payload exceeds the protocol limit");
  }
  const frame = new ArrayBuffer(AUDIO_FRAME_HEADER_BYTES + payload.byteLength);
  const view = new DataView(frame);
  view.setUint8(0, MAGIC_0);
  view.setUint8(1, MAGIC_1);
  view.setUint8(2, REALTIME_VOICE_PROTOCOL_VERSION);
  view.setUint8(3, kind);
  view.setUint32(4, sequence, false);
  view.setUint32(8, sampleRate, false);
  view.setUint16(12, channels, false);
  view.setUint32(14, payload.byteLength, false);
  new Uint8Array(frame, AUDIO_FRAME_HEADER_BYTES).set(new Uint8Array(payload));
  return frame;
}

export function decodeAudioFrame(frame: ArrayBuffer): DecodedAudioFrame {
  if (frame.byteLength < AUDIO_FRAME_HEADER_BYTES) {
    throw new Error("Audio frame header is truncated");
  }
  const view = new DataView(frame);
  if (view.getUint8(0) !== MAGIC_0 || view.getUint8(1) !== MAGIC_1) {
    throw new Error("Audio frame magic is invalid");
  }
  if (view.getUint8(2) !== REALTIME_VOICE_PROTOCOL_VERSION) {
    throw new Error("Realtime Voice protocol version is unsupported");
  }
  const length = view.getUint32(14, false);
  if (length > MAX_AUDIO_PAYLOAD_BYTES) {
    throw new Error("Audio frame payload exceeds the protocol limit");
  }
  if (frame.byteLength !== AUDIO_FRAME_HEADER_BYTES + length) {
    throw new Error("Audio frame payload length is invalid");
  }
  const kind = view.getUint8(3);
  const sampleRate = view.getUint32(8, false);
  const channels = view.getUint16(12, false);
  if (
    !Object.values(AudioFrameKind).includes(kind as AudioFrameKind) ||
    sampleRate < 8000 ||
    sampleRate > 192000 ||
    channels < 1 ||
    channels > 8
  ) {
    throw new Error("Audio frame media metadata is invalid");
  }
  return {
    kind: kind as AudioFrameKind,
    sequence: view.getUint32(4, false),
    sampleRate,
    channels,
    payload: frame.slice(AUDIO_FRAME_HEADER_BYTES),
  };
}
