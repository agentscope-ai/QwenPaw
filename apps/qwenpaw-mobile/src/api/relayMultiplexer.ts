import {
  decodeRelayFrame,
  encodeRelayFrame,
  type RelayOperation,
} from "@qwenpaw/api-contract";

export interface RelaySocket {
  binaryType: string;
  close(): void;
  send(data: ArrayBuffer | Uint8Array): void;
  addEventListener(
    type: "close" | "error" | "message" | "open",
    listener: (event: { data?: unknown }) => void,
  ): void;
}

interface PendingRequest {
  chunks: Uint8Array[];
  reject(error: Error): void;
  resolve(value: Uint8Array): void;
}

export class RelayMultiplexer {
  private readonly pending = new Map<string, PendingRequest>();
  private closed = false;

  constructor(
    private readonly socket: RelaySocket,
    private readonly createId: () => string = relayRequestId,
    private readonly onClose: () => void = () => undefined,
  ) {
    socket.binaryType = "arraybuffer";
    socket.addEventListener("message", (event) => this.receive(event.data));
    socket.addEventListener("close", () => this.failAll("安全中转已断开"));
    socket.addEventListener("error", () => this.failAll("安全中转连接失败"));
  }

  request(operation: RelayOperation, payload: Uint8Array): Promise<Uint8Array> {
    if (this.closed) {
      return Promise.reject(new Error("安全中转已断开"));
    }
    const streamId = this.createId();
    const requestId = this.createId();
    return new Promise((resolve, reject) => {
      this.pending.set(streamId, { chunks: [], reject, resolve });
      this.socket.send(
        encodeRelayFrame({
          header: {
            v: 1,
            type: "open",
            stream_id: streamId,
            request_id: requestId,
            metadata: { operation_id: operation, schema_version: 1 },
          },
          payload: new Uint8Array(),
        }),
      );
      if (payload.byteLength > 0) {
        this.socket.send(
          encodeRelayFrame({
            header: { v: 1, type: "data", stream_id: streamId },
            payload,
          }),
        );
      }
      this.socket.send(
        encodeRelayFrame({
          header: { v: 1, type: "end", stream_id: streamId },
          payload: new Uint8Array(),
        }),
      );
    });
  }

  close(): void {
    this.socket.close();
    this.failAll("安全中转已关闭");
  }

  private receive(value: unknown): void {
    if (!(value instanceof ArrayBuffer) && !(value instanceof Uint8Array)) {
      this.failAll("安全中转返回了无效数据");
      return;
    }
    const frame = decodeRelayFrame(value);
    const streamId = frame.header.stream_id;
    if (!streamId) return;
    const pending = this.pending.get(streamId);
    if (!pending) return;
    if (frame.header.type === "data") {
      pending.chunks.push(frame.payload);
      return;
    }
    if (frame.header.type === "error") {
      this.pending.delete(streamId);
      pending.reject(
        new Error(String(frame.header.metadata?.code ?? "RELAY_ERROR")),
      );
      return;
    }
    if (frame.header.type === "end") {
      this.pending.delete(streamId);
      pending.resolve(joinBytes(pending.chunks));
    }
  }

  private failAll(message: string): void {
    if (this.closed) return;
    this.closed = true;
    for (const pending of this.pending.values()) {
      pending.reject(new Error(message));
    }
    this.pending.clear();
    this.onClose();
  }
}

function relayRequestId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function joinBytes(chunks: Uint8Array[]): Uint8Array {
  const result = new Uint8Array(
    chunks.reduce((total, chunk) => total + chunk.byteLength, 0),
  );
  let offset = 0;
  for (const chunk of chunks) {
    result.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return result;
}
