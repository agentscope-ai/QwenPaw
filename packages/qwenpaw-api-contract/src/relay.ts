export const RELAY_PROTOCOL_VERSION = 1 as const;

export type RelayFrameType =
  | "hello"
  | "open"
  | "data"
  | "end"
  | "result_meta"
  | "cancel"
  | "error"
  | "ping"
  | "pong"
  | "session_event"
  | "event_ack"
  | "resume";

export interface RelayFrameHeader {
  v: typeof RELAY_PROTOCOL_VERSION;
  type: RelayFrameType;
  stream_id?: string;
  request_id?: string;
  sequence?: number;
  metadata?: Record<string, unknown>;
}

export interface RelayFrame {
  header: RelayFrameHeader;
  payload: Uint8Array;
}

export const RELAY_OPERATIONS = [
  "agent.list",
  "agent.get",
  "session.list",
  "session.get",
  "session.create",
  "session.update",
  "session.archive",
  "session.delete",
  "message.send",
  "run.cancel",
  "approval.resolve",
  "attachment.upload.begin",
  "attachment.upload.chunk",
  "attachment.upload.complete",
  "attachment.download",
] as const;

export type RelayOperation = (typeof RELAY_OPERATIONS)[number];

const HEADER_PREFIX_BYTES = 4;
const MAX_HEADER_BYTES = 64 * 1024;
const frameTypes = new Set<RelayFrameType>([
  "hello",
  "open",
  "data",
  "end",
  "result_meta",
  "cancel",
  "error",
  "ping",
  "pong",
  "session_event",
  "event_ack",
  "resume",
]);
const streamFrameTypes = new Set<RelayFrameType>([
  "open",
  "data",
  "end",
  "result_meta",
  "cancel",
  "error",
]);

export function encodeRelayFrame(frame: RelayFrame): Uint8Array {
  assertRelayHeader(frame.header);
  const header = new TextEncoder().encode(
    stableJson(frame.header as unknown as Record<string, unknown>),
  );
  if (header.byteLength > MAX_HEADER_BYTES) {
    throw new Error("Relay frame header is too large");
  }
  const wire = new Uint8Array(
    HEADER_PREFIX_BYTES + header.byteLength + frame.payload.byteLength,
  );
  new DataView(wire.buffer).setUint32(0, header.byteLength, false);
  wire.set(header, HEADER_PREFIX_BYTES);
  wire.set(frame.payload, HEADER_PREFIX_BYTES + header.byteLength);
  return wire;
}

export function decodeRelayFrame(value: ArrayBuffer | Uint8Array): RelayFrame {
  const wire = value instanceof Uint8Array ? value : new Uint8Array(value);
  if (wire.byteLength < HEADER_PREFIX_BYTES) {
    throw new Error("Relay frame is missing its header length");
  }
  const headerLength = new DataView(
    wire.buffer,
    wire.byteOffset,
    wire.byteLength,
  ).getUint32(0, false);
  if (headerLength <= 0 || headerLength > MAX_HEADER_BYTES) {
    throw new Error("Relay frame header length is invalid");
  }
  const headerEnd = HEADER_PREFIX_BYTES + headerLength;
  if (wire.byteLength < headerEnd) {
    throw new Error("Relay frame header is truncated");
  }
  let header: unknown;
  try {
    header = JSON.parse(
      new TextDecoder().decode(wire.subarray(HEADER_PREFIX_BYTES, headerEnd)),
    );
  } catch {
    throw new Error("Relay frame header is not valid JSON");
  }
  assertRelayHeader(header);
  return {
    header,
    payload: wire.slice(headerEnd),
  };
}

export function assertRelayHeader(
  value: unknown,
): asserts value is RelayFrameHeader {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Relay frame header must be an object");
  }
  const header = value as Record<string, unknown>;
  if (header.v !== RELAY_PROTOCOL_VERSION) {
    throw new Error(`Unsupported Relay protocol version: ${String(header.v)}`);
  }
  if (
    typeof header.type !== "string" ||
    !frameTypes.has(header.type as RelayFrameType)
  ) {
    throw new Error("Relay frame type is unsupported");
  }
  if (
    header.sequence !== undefined &&
    (!Number.isSafeInteger(header.sequence) || Number(header.sequence) < 0)
  ) {
    throw new Error("Frame sequence must be a non-negative integer");
  }
  if (
    header.metadata !== undefined &&
    (!header.metadata ||
      typeof header.metadata !== "object" ||
      Array.isArray(header.metadata))
  ) {
    throw new Error("Relay frame metadata must be an object");
  }
  const frameType = header.type as RelayFrameType;
  if (streamFrameTypes.has(frameType) && !nonEmptyString(header.stream_id)) {
    throw new Error(`${frameType} frame requires stream_id`);
  }
  if (frameType === "open") {
    const metadata = (header.metadata ?? {}) as Record<string, unknown>;
    if (!nonEmptyString(header.request_id)) {
      throw new Error("Open frame requires request_id");
    }
    if (
      !nonEmptyString(metadata.operation_id) ||
      !isRelayOperation(metadata.operation_id)
    ) {
      throw new Error("Open frame operation_id is unsupported");
    }
    if (
      !Number.isSafeInteger(metadata.schema_version) ||
      Number(metadata.schema_version) < 1
    ) {
      throw new Error("Open frame schema_version is invalid");
    }
  }
  if (frameType === "session_event") {
    const metadata = (header.metadata ?? {}) as Record<string, unknown>;
    const missing = ["session_id", "event_id", "event_type"].filter(
      (key) => !nonEmptyString(metadata[key]),
    );
    if (!Number.isSafeInteger(metadata.session_revision)) {
      missing.push("session_revision");
    }
    if (!Number.isSafeInteger(header.sequence)) missing.push("sequence");
    if (missing.length > 0) {
      throw new Error(`Session event is missing: ${missing.join(", ")}`);
    }
  }
  if (
    frameType === "event_ack" &&
    (!Number.isSafeInteger(header.sequence) ||
      !nonEmptyString(
        (header.metadata as Record<string, unknown> | undefined)?.session_id,
      ))
  ) {
    throw new Error("Event acknowledgement requires session_id and sequence");
  }
}

export function isRelayOperation(value: string): value is RelayOperation {
  return (RELAY_OPERATIONS as readonly string[]).includes(value);
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function stableJson(value: Record<string, unknown>): string {
  const keys = Object.keys(value).sort();
  const sorted: Record<string, unknown> = {};
  keys.forEach((key) => {
    sorted[key] = value[key];
  });
  return JSON.stringify(sorted);
}
