import { getApiUrl } from "../../api/config";
import type { RealtimeVoiceBootstrap } from "../../api/modules/realtimeVoice";
import {
  AudioFrameKind,
  decodeAudioFrame,
  encodeAudioFrame,
  type RealtimeVoiceEvent,
} from "./protocol";

interface RealtimeVoiceClientCallbacks {
  onEvent: (event: RealtimeVoiceEvent) => void;
  onAudio: (pcm16: ArrayBuffer, sampleRate: number) => void;
  onClose: (event: CloseEvent) => void;
}

const CONNECT_TIMEOUT_MS = 10_000;
const MAX_BUFFERED_AUDIO_BYTES = 64 * 1024;

function websocketUrl(bootstrap: RealtimeVoiceBootstrap): string {
  const apiUrl = new URL(getApiUrl("/"), window.location.href);
  const endpoint = bootstrap.ws_url.startsWith("/api/")
    ? new URL(bootstrap.ws_url, apiUrl.origin)
    : new URL(bootstrap.ws_url, apiUrl);
  endpoint.protocol = endpoint.protocol === "https:" ? "wss:" : "ws:";
  endpoint.searchParams.set("token", bootstrap.token);
  return endpoint.toString();
}

export class RealtimeVoiceClient {
  private socket: WebSocket | null = null;
  private inputSequence = 0;
  private outputSequence: number | null = null;
  private readonly bootstrap: RealtimeVoiceBootstrap;
  private readonly callbacks: RealtimeVoiceClientCallbacks;

  constructor(
    bootstrap: RealtimeVoiceBootstrap,
    callbacks: RealtimeVoiceClientCallbacks,
  ) {
    this.bootstrap = bootstrap;
    this.callbacks = callbacks;
  }

  connect(): Promise<void> {
    const socket = new WebSocket(websocketUrl(this.bootstrap));
    socket.binaryType = "arraybuffer";
    this.socket = socket;
    socket.onmessage = (message) => {
      try {
        if (message.data instanceof ArrayBuffer) {
          const frame = decodeAudioFrame(message.data);
          if (frame.kind !== AudioFrameKind.OutputPcm16) {
            throw new Error("Unexpected audio frame direction");
          }
          const expected =
            this.outputSequence === null ? 0 : (this.outputSequence + 1) >>> 0;
          if (frame.sequence !== expected) {
            throw new Error("Realtime Voice audio sequence is not contiguous");
          }
          this.outputSequence = frame.sequence;
          this.callbacks.onAudio(frame.payload, frame.sampleRate);
          return;
        }
        const event = JSON.parse(String(message.data)) as RealtimeVoiceEvent;
        if (!event || typeof event.type !== "string") {
          throw new Error("Realtime Voice event is invalid");
        }
        this.callbacks.onEvent(event);
      } catch (reason) {
        this.callbacks.onEvent({
          type: "error",
          code: "protocol_error",
          message:
            reason instanceof Error
              ? reason.message
              : "Realtime Voice protocol error",
          recoverable: false,
        });
        socket.close(1003, "Invalid Realtime Voice message");
      }
    };
    return new Promise((resolve, reject) => {
      let settled = false;
      const timer = window.setTimeout(() => {
        if (settled) return;
        settled = true;
        socket.close();
        reject(new Error("Realtime Voice WebSocket connection timed out"));
      }, CONNECT_TIMEOUT_MS);
      socket.onopen = () => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timer);
        resolve();
      };
      socket.onclose = (event) => {
        this.callbacks.onClose(event);
        if (settled) return;
        settled = true;
        window.clearTimeout(timer);
        reject(new Error("Realtime Voice WebSocket closed before connecting"));
      };
      socket.addEventListener(
        "error",
        () => {
          if (settled) return;
          settled = true;
          window.clearTimeout(timer);
          reject(new Error("Realtime Voice WebSocket failed to connect"));
        },
        { once: true },
      );
    });
  }

  sendAudio(pcm16: ArrayBuffer): boolean {
    if (
      this.socket?.readyState !== WebSocket.OPEN ||
      this.socket.bufferedAmount > MAX_BUFFERED_AUDIO_BYTES
    ) {
      return false;
    }
    this.socket.send(
      encodeAudioFrame(
        AudioFrameKind.InputPcm16,
        this.inputSequence,
        this.bootstrap.media.input_sample_rate,
        this.bootstrap.media.channels,
        pcm16,
      ),
    );
    this.inputSequence = (this.inputSequence + 1) >>> 0;
    return true;
  }

  observeAgentRun(): boolean {
    return this.sendJson({ type: "agent.observe" });
  }

  interrupt(): void {
    this.sendJson({ type: "interrupt" });
  }

  playbackFeedback(
    outputId: string,
    status: "drained" | "interrupted" | "failed",
  ): boolean {
    return this.sendJson({
      type: "output.playback",
      output_id: outputId,
      generation: this.bootstrap.generation,
      status,
    });
  }

  stop(): void {
    this.sendJson({ type: "stop" });
  }

  close(): void {
    const socket = this.socket;
    this.socket = null;
    if (socket && socket.readyState < WebSocket.CLOSING) socket.close(1000);
  }

  private sendJson(payload: Record<string, unknown>): boolean {
    if (this.socket?.readyState !== WebSocket.OPEN) return false;
    this.socket.send(JSON.stringify(payload));
    return true;
  }
}
