import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  RealtimeVoiceApiError,
  realtimeVoiceApi,
  type RealtimeVoiceBootstrap,
  type RealtimeVoiceCapabilities,
  type RealtimeVoiceMedia,
  type VoiceAdmissionMode,
} from "../../api/modules/realtimeVoice";
import { RealtimeAudioCapture } from "./audioCapture";
import { RealtimeAudioPlayback } from "./audioPlayback";
import { RealtimeVoiceClient } from "./client";
import { REALTIME_VOICE_PROTOCOL_VERSION } from "./protocol";

export type RealtimeVoiceStatus =
  | "idle"
  | "connecting"
  | "listening"
  | "user_speaking"
  | "agent_working"
  | "assistant_speaking"
  | "reconnecting"
  | "error";

export type RealtimeVoiceConnectionState =
  | "idle"
  | "connecting"
  | "ready"
  | "reconnecting"
  | "error";
export type RealtimeVoiceInputState = "idle" | "listening" | "speaking";
export type RealtimeVoiceAgentState = "idle" | "working";
export type RealtimeVoiceOutputState =
  | "idle"
  | "speaking"
  | "interrupted"
  | "failed";
export type RealtimeVoicePendingInputState =
  | "idle"
  | "classifying"
  | "waiting"
  | "needs_confirmation";

export interface RealtimeVoiceState {
  connection: RealtimeVoiceConnectionState;
  input: RealtimeVoiceInputState;
  agent: RealtimeVoiceAgentState;
  output: RealtimeVoiceOutputState;
}

const INITIAL_VOICE_STATE: RealtimeVoiceState = {
  connection: "idle",
  input: "idle",
  agent: "idle",
  output: "idle",
};

export function deriveRealtimeVoiceStatus(
  state: RealtimeVoiceState,
): RealtimeVoiceStatus {
  if (state.connection === "error") return "error";
  if (state.connection === "connecting") return "connecting";
  if (state.connection === "reconnecting") return "reconnecting";
  if (state.output === "speaking") return "assistant_speaking";
  if (state.input === "speaking") return "user_speaking";
  if (state.agent === "working") return "agent_working";
  if (state.connection === "ready") return "listening";
  return "idle";
}

const ACTIVE_STATUSES = new Set<RealtimeVoiceStatus>([
  "connecting",
  "listening",
  "user_speaking",
  "agent_working",
  "assistant_speaking",
  "reconnecting",
]);

export function isRealtimeVoiceActive(status: RealtimeVoiceStatus): boolean {
  return ACTIVE_STATUSES.has(status);
}

export function isRealtimeVoiceReady(
  capabilities: RealtimeVoiceCapabilities | null,
): boolean {
  return Boolean(
    capabilities?.effective_model &&
      capabilities.credential_configured &&
      !capabilities.configuration_error,
  );
}

interface ConflictState {
  sessionId: string;
  agentId?: string;
  chatId?: string;
}

interface UseRealtimeVoiceOptions {
  enabled?: boolean;
  chatId?: string;
  onChatCreated: (chatId: string) => void;
  onAgentRunStarted: () => void;
  onTimelineChanged?: (messages: unknown[]) => void;
}

const RECONNECT_LIMIT = 3;
const RECONNECT_WINDOW_MS = 30_000;
const MAX_PRE_READY_AUDIO_FRAMES = 50;
const ADMISSION_MODE_STORAGE_KEY = "qwenpaw.realtimeVoice.admissionMode";

function releaseBootstrap(bootstrap: RealtimeVoiceBootstrap | null) {
  if (!bootstrap) return;
  // Never let cleanup of an old lease fail a newer connection. Unclaimed
  // bootstraps also expire server-side if the network is unavailable.
  void realtimeVoiceApi.endSession(bootstrap).catch(() => undefined);
}

function loadAdmissionMode(): VoiceAdmissionMode {
  try {
    return window.localStorage.getItem(ADMISSION_MODE_STORAGE_KEY) === "steer"
      ? "steer"
      : "queue";
  } catch {
    return "queue";
  }
}

export function useRealtimeVoice({
  enabled = true,
  chatId,
  onChatCreated,
  onAgentRunStarted,
  onTimelineChanged,
}: UseRealtimeVoiceOptions) {
  const { t } = useTranslation();
  const [capabilities, setCapabilities] =
    useState<RealtimeVoiceCapabilities | null>(null);
  const [voiceState, setVoiceState] =
    useState<RealtimeVoiceState>(INITIAL_VOICE_STATE);
  const [muted, setMutedState] = useState(false);
  const [inputTranscript, setInputTranscript] = useState("");
  const [pendingInputState, setPendingInputState] =
    useState<RealtimeVoicePendingInputState>("idle");
  const [pendingInputError, setPendingInputError] = useState<string | null>(
    null,
  );
  const [assistantTranscript, setAssistantTranscript] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<ConflictState | null>(null);
  const [inputDevices, setInputDevices] = useState<MediaDeviceInfo[]>([]);
  const [inputDeviceId, setInputDeviceIdState] = useState("");
  const [admissionMode, setAdmissionModeState] =
    useState<VoiceAdmissionMode>(loadAdmissionMode);

  const capabilitiesRef = useRef<RealtimeVoiceCapabilities | null>(null);
  const clientRef = useRef<RealtimeVoiceClient | null>(null);
  const captureRef = useRef<RealtimeAudioCapture | null>(null);
  const playbackRef = useRef<RealtimeAudioPlayback | null>(null);
  const bootstrapRef = useRef<RealtimeVoiceBootstrap | null>(null);
  const mediaRef = useRef<RealtimeVoiceMedia | null>(null);
  const manualStopRef = useRef(false);
  const startGenerationRef = useRef(0);
  const reconnectStartedRef = useRef(0);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const restartingDeviceRef = useRef<number | null>(null);
  const providerReadyRef = useRef(false);
  const preReadyAudioRef = useRef<ArrayBuffer[]>([]);
  const currentRunIdRef = useRef<string | null>(null);
  const acceptOutputAudioRef = useRef(false);
  const hasPendingInputRef = useRef(false);
  const pendingInputTextRef = useRef("");
  const inputPreviewPrefixRef = useRef("");
  const inputDeviceIdRef = useRef("");
  const mutedRef = useRef(muted);
  mutedRef.current = muted;
  const connectBootstrapRef = useRef<
    | ((bootstrap: RealtimeVoiceBootstrap, generation: number) => Promise<void>)
    | null
  >(null);
  const scheduleReconnectRef = useRef<
    ((bootstrap: RealtimeVoiceBootstrap) => void) | null
  >(null);
  const agentRunStartedRef = useRef(onAgentRunStarted);
  agentRunStartedRef.current = onAgentRunStarted;
  const timelineChangedRef = useRef(onTimelineChanged);
  timelineChangedRef.current = onTimelineChanged;
  const chatCreatedRef = useRef(onChatCreated);
  chatCreatedRef.current = onChatCreated;

  const updateVoiceState = useCallback(
    (patch: Partial<RealtimeVoiceState>) =>
      setVoiceState((current) => ({ ...current, ...patch })),
    [],
  );

  const isCurrentGeneration = useCallback(
    (generation: number) =>
      generation === startGenerationRef.current && !manualStopRef.current,
    [],
  );

  const loadCapabilities = useCallback(async () => {
    const loaded = await realtimeVoiceApi.getCapabilities();
    capabilitiesRef.current = loaded;
    setCapabilities(loaded);
    return loaded;
  }, []);

  useEffect(() => {
    if (!enabled) return;
    void loadCapabilities().catch((reason) => {
      setError(reason instanceof Error ? reason.message : String(reason));
    });
  }, [enabled, loadCapabilities]);

  const cleanupMedia = useCallback(async () => {
    const capture = captureRef.current;
    const playback = playbackRef.current;
    captureRef.current = null;
    playbackRef.current = null;
    providerReadyRef.current = false;
    acceptOutputAudioRef.current = false;
    preReadyAudioRef.current = [];
    await Promise.all([capture?.stop(), playback?.close()]);
  }, []);

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    reconnectTimerRef.current = null;
  }, []);

  const fail = useCallback(
    async (message: string) => {
      startGenerationRef.current += 1;
      manualStopRef.current = true;
      clearReconnectTimer();
      clientRef.current?.close();
      clientRef.current = null;
      releaseBootstrap(bootstrapRef.current);
      bootstrapRef.current = null;
      setVoiceState({ ...INITIAL_VOICE_STATE, connection: "error" });
      setError(message);
      await cleanupMedia();
    },
    [cleanupMedia, clearReconnectTimer],
  );

  const forwardAudio = useCallback((pcm16: ArrayBuffer) => {
    if (providerReadyRef.current) {
      // Drop live frames under transport backpressure instead of allowing
      // stale audio to grow without bound.
      clientRef.current?.sendAudio(pcm16);
      return;
    }
    const buffered = preReadyAudioRef.current;
    buffered.push(pcm16);
    if (buffered.length > MAX_PRE_READY_AUDIO_FRAMES) buffered.shift();
  }, []);

  const restartCapture = useCallback(async () => {
    const generation = startGenerationRef.current;
    if (
      restartingDeviceRef.current === generation ||
      manualStopRef.current ||
      !mediaRef.current
    ) {
      return;
    }
    restartingDeviceRef.current = generation;
    let capture: RealtimeAudioCapture | null = null;
    try {
      await captureRef.current?.stop();
      if (!isCurrentGeneration(generation)) return;
      capture = new RealtimeAudioCapture(
        mediaRef.current.input_sample_rate,
        inputDeviceIdRef.current || undefined,
      );
      capture.setMuted(mutedRef.current);
      captureRef.current = capture;
      await capture.start(
        (pcm) => {
          if (isCurrentGeneration(generation) && captureRef.current === capture)
            forwardAudio(pcm);
        },
        () => {
          if (isCurrentGeneration(generation) && captureRef.current === capture)
            void restartCapture();
        },
      );
      if (!isCurrentGeneration(generation)) await capture.stop();
    } catch {
      if (isCurrentGeneration(generation))
        await fail("The selected microphone is no longer available.");
      else await capture?.stop();
    } finally {
      if (restartingDeviceRef.current === generation)
        restartingDeviceRef.current = null;
    }
  }, [fail, forwardAudio, isCurrentGeneration]);

  const refreshInputDevices = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    try {
      const devices = (await navigator.mediaDevices.enumerateDevices()).filter(
        (device) => device.kind === "audioinput",
      );
      setInputDevices(devices);
      const selected = inputDeviceIdRef.current;
      if (selected && !devices.some((device) => device.deviceId === selected)) {
        inputDeviceIdRef.current = "";
        setInputDeviceIdState("");
        if (captureRef.current) await restartCapture();
      }
    } catch {
      // Device enumeration is optional; capture can continue on the default.
    }
  }, [restartCapture]);

  useEffect(() => {
    const onDeviceChange = () => void refreshInputDevices();
    navigator.mediaDevices?.addEventListener("devicechange", onDeviceChange);
    return () =>
      navigator.mediaDevices?.removeEventListener(
        "devicechange",
        onDeviceChange,
      );
  }, [refreshInputDevices]);

  const connectBootstrap = useCallback(
    async (bootstrap: RealtimeVoiceBootstrap, generation: number) => {
      if (!isCurrentGeneration(generation)) {
        releaseBootstrap(bootstrap);
        return;
      }
      if (bootstrap.protocol_version !== REALTIME_VOICE_PROTOCOL_VERSION) {
        throw new Error("Realtime Voice protocol version does not match.");
      }
      bootstrapRef.current = bootstrap;
      mediaRef.current = bootstrap.media;
      providerReadyRef.current = false;
      acceptOutputAudioRef.current = false;
      let opened = false;
      const ownsConnection = () =>
        isCurrentGeneration(generation) && clientRef.current === client;
      const client = new RealtimeVoiceClient(bootstrap, {
        onAudio: (pcm16, sampleRate) => {
          if (!ownsConnection() || !acceptOutputAudioRef.current) return;
          void playbackRef.current?.enqueue(pcm16, sampleRate).catch(() => {
            if (ownsConnection())
              void fail("Audio playback was blocked by the browser.");
          });
        },
        onEvent: (event) => {
          if (!ownsConnection()) return;
          if (
            typeof event.generation === "number" &&
            event.generation !== bootstrap.generation
          ) {
            return;
          }
          const eventRunId =
            typeof event.run_id === "string" ? event.run_id : null;
          const isStaleRun = Boolean(
            eventRunId &&
              currentRunIdRef.current &&
              eventRunId !== currentRunIdRef.current,
          );
          switch (event.type) {
            case "session.ready": {
              providerReadyRef.current = true;
              const queuedAudio = preReadyAudioRef.current.splice(0);
              for (let index = 0; index < queuedAudio.length; index += 1) {
                if (!client.sendAudio(queuedAudio[index])) {
                  preReadyAudioRef.current.push(...queuedAudio.slice(index));
                  break;
                }
              }
              reconnectAttemptsRef.current = 0;
              reconnectStartedRef.current = 0;
              setError(null);
              updateVoiceState({
                connection: "ready",
                input: "listening",
                output: "idle",
              });
              break;
            }
            case "speech.started":
              acceptOutputAudioRef.current = false;
              if (mutedRef.current) {
                updateVoiceState({ input: "listening" });
                break;
              }
              playbackRef.current?.interrupt();
              inputPreviewPrefixRef.current = hasPendingInputRef.current
                ? pendingInputTextRef.current
                : "";
              setInputTranscript(inputPreviewPrefixRef.current);
              setAssistantTranscript("");
              updateVoiceState({ input: "speaking", output: "interrupted" });
              break;
            case "speech.stopped":
              updateVoiceState({ input: "listening" });
              break;
            case "output.begin":
              if (typeof event.output_id !== "string") break;
              playbackRef.current?.begin(
                event.output_id,
                (outputId, status) => {
                  if (!ownsConnection()) return;
                  client.playbackFeedback(outputId, status);
                  acceptOutputAudioRef.current = false;
                  updateVoiceState({
                    output: status === "drained" ? "idle" : status,
                  });
                },
              );
              break;
            case "output.started":
              if (isStaleRun) break;
              if (!playbackRef.current?.isActive(String(event.output_id || "")))
                break;
              acceptOutputAudioRef.current = true;
              setError(null);
              setAssistantTranscript("");
              updateVoiceState({ output: "speaking" });
              break;
            case "output.stopped":
              if (isStaleRun) break;
              // Provider generation ending is not browser playback completion.
              break;
            case "output.sealed":
              if (typeof event.output_id === "string")
                playbackRef.current?.seal(event.output_id);
              break;
            case "presentation.rejected":
              setError(
                t(
                  event.task_admitted
                    ? "realtimeVoice.speechBusyAdmitted"
                    : event.code === "voice_output_unavailable"
                    ? "realtimeVoice.speechUnavailable"
                    : "realtimeVoice.speechBusyRetry",
                ),
              );
              break;
            case "input_transcript.partial":
              setInputTranscript(
                inputPreviewPrefixRef.current + String(event.text || ""),
              );
              break;
            case "input_transcript.final": {
              const text = String(event.text || "").trim();
              setInputTranscript(inputPreviewPrefixRef.current + text);
              break;
            }
            case "input_turn.pending": {
              const state = String(event.state || "classifying");
              hasPendingInputRef.current = true;
              pendingInputTextRef.current = String(event.text || "").trim();
              setInputTranscript(pendingInputTextRef.current);
              setPendingInputState(
                state === "waiting" || state === "needs_confirmation"
                  ? state
                  : "classifying",
              );
              setPendingInputError(
                typeof event.error === "string" && event.error
                  ? event.error
                  : null,
              );
              break;
            }
            case "input_turn.committed":
              hasPendingInputRef.current = false;
              pendingInputTextRef.current = "";
              setPendingInputState("idle");
              setPendingInputError(null);
              break;
            case "input_turn.rejected":
              hasPendingInputRef.current = false;
              pendingInputTextRef.current = "";
              setPendingInputState("idle");
              setPendingInputError(null);
              setError(
                String(event.message || "The request could not be accepted."),
              );
              break;
            case "output_transcript.partial":
              setAssistantTranscript(
                (current) => current + String(event.text || ""),
              );
              break;
            case "output_transcript.final":
              setAssistantTranscript(String(event.text || "").trim());
              break;
            case "agent.input.accepted": {
              if (eventRunId) currentRunIdRef.current = eventRunId;
              updateVoiceState({ agent: "working" });
              break;
            }
            case "agent.input.consumed": {
              if (isStaleRun) break;
              updateVoiceState({ agent: "working" });
              break;
            }
            case "agent.run.started": {
              if (eventRunId) currentRunIdRef.current = eventRunId;
              updateVoiceState({ agent: "working" });
              if (event.status === "started") {
                agentRunStartedRef.current();
              }
              break;
            }
            case "agent.run.completed":
              if (isStaleRun) break;
              updateVoiceState({ agent: "idle" });
              break;
            case "chat.history.updated":
              timelineChangedRef.current?.(
                Array.isArray(event.messages) ? event.messages : [],
              );
              break;
            case "agent.task.updated":
              if (
                event.status === "accepted" ||
                event.status === "queued" ||
                event.status === "processing"
              ) {
                updateVoiceState({ agent: "working" });
              }
              break;
            case "session.closed":
              if (event.reason === "max_duration") {
                void fail(
                  "Realtime Voice reached the configured session duration.",
                );
              }
              break;
            case "error":
              if (event.source === "presentation") {
                playbackRef.current?.interrupt();
                setError(t("realtimeVoice.speechUnavailable"));
                updateVoiceState({ output: "failed" });
                break;
              }
              if (event.recoverable && event.source === "provider") {
                setError(
                  String(event.message || "Realtime voice request failed."),
                );
                updateVoiceState({ output: "failed" });
                break;
              }
              if (event.recoverable) {
                setError(
                  String(event.message || "Realtime Voice disconnected."),
                );
                client.close();
              } else {
                void fail(String(event.message || "Realtime Voice failed."));
              }
              break;
          }
        },
        onClose: () => {
          if (!ownsConnection()) return;
          providerReadyRef.current = false;
          acceptOutputAudioRef.current = false;
          clientRef.current = null;
          if (!opened) return;
          const current = bootstrapRef.current;
          if (!current) return;
          if (!reconnectStartedRef.current) {
            reconnectStartedRef.current = Date.now();
          }
          scheduleReconnectRef.current?.(current);
        },
      });
      clientRef.current = client;
      try {
        await client.connect();
        if (!ownsConnection()) {
          client.close();
          releaseBootstrap(bootstrap);
          return;
        }
        opened = true;
      } catch (reason) {
        if (clientRef.current === client) clientRef.current = null;
        client.close();
        releaseBootstrap(bootstrap);
        throw reason;
      }
    },
    [fail, isCurrentGeneration, updateVoiceState, t],
  );
  connectBootstrapRef.current = connectBootstrap;

  const scheduleReconnect = useCallback(
    (current: RealtimeVoiceBootstrap) => {
      const generation = startGenerationRef.current;
      if (manualStopRef.current) return;
      const elapsed = Date.now() - reconnectStartedRef.current;
      if (
        elapsed >= RECONNECT_WINDOW_MS ||
        reconnectAttemptsRef.current >= RECONNECT_LIMIT
      ) {
        void fail("Realtime Voice could not reconnect within 30 seconds.");
        return;
      }
      reconnectAttemptsRef.current += 1;
      updateVoiceState({ connection: "reconnecting", output: "idle" });
      const delay = 500 * 2 ** (reconnectAttemptsRef.current - 1);
      reconnectTimerRef.current = setTimeout(async () => {
        if (!isCurrentGeneration(generation)) return;
        let resumeFrom = current;
        try {
          const next = await realtimeVoiceApi.createSession({
            chat_id: current.chat_id,
            previous_session_id: current.session_id,
            admission_mode: admissionMode,
          });
          resumeFrom = next;
          if (!isCurrentGeneration(generation)) {
            releaseBootstrap(next);
            return;
          }
          await connectBootstrapRef.current?.(next, generation);
        } catch (reason) {
          if (!isCurrentGeneration(generation)) return;
          setError(reason instanceof Error ? reason.message : String(reason));
          scheduleReconnectRef.current?.(resumeFrom);
        }
      }, delay);
    },
    [admissionMode, fail, isCurrentGeneration, updateVoiceState],
  );
  scheduleReconnectRef.current = scheduleReconnect;

  const begin = useCallback(
    async (replaceSessionId?: string) => {
      if (!enabled) return;
      const startGeneration = startGenerationRef.current + 1;
      startGenerationRef.current = startGeneration;
      manualStopRef.current = false;
      clearReconnectTimer();
      clientRef.current?.close();
      clientRef.current = null;
      releaseBootstrap(bootstrapRef.current);
      bootstrapRef.current = null;
      void cleanupMedia();
      setError(null);
      setConflict(null);
      setVoiceState({ ...INITIAL_VOICE_STATE, connection: "connecting" });
      currentRunIdRef.current = null;
      hasPendingInputRef.current = false;
      pendingInputTextRef.current = "";
      inputPreviewPrefixRef.current = "";
      setPendingInputState("idle");
      setPendingInputError(null);
      reconnectStartedRef.current = 0;
      reconnectAttemptsRef.current = 0;
      providerReadyRef.current = false;
      acceptOutputAudioRef.current = false;
      preReadyAudioRef.current = [];

      let playback: RealtimeAudioPlayback | null = null;
      let capture: RealtimeAudioCapture | null = null;
      try {
        const loaded =
          capabilitiesRef.current ?? capabilities ?? (await loadCapabilities());
        if (!isCurrentGeneration(startGeneration)) return;
        const providerId = loaded.effective_model?.provider_id;
        const provider = loaded.providers.find(
          (item) => item.id === providerId,
        );
        if (!provider)
          throw new Error("Realtime Voice provider is unavailable.");
        playback = new RealtimeAudioPlayback();
        capture = new RealtimeAudioCapture(
          provider.media.input_sample_rate,
          inputDeviceIdRef.current || undefined,
        );
        capture.setMuted(mutedRef.current);
        playbackRef.current = playback;
        captureRef.current = capture;

        // Both calls begin directly inside the click handler before bootstrap.
        const playbackReady = playback.unlock();
        const captureReady = capture.start(
          (pcm) => {
            if (
              isCurrentGeneration(startGeneration) &&
              captureRef.current === capture
            )
              forwardAudio(pcm);
          },
          () => {
            if (
              isCurrentGeneration(startGeneration) &&
              captureRef.current === capture
            )
              void restartCapture();
          },
        );
        await Promise.all([playbackReady, captureReady]);
        if (
          startGeneration !== startGenerationRef.current ||
          manualStopRef.current
        ) {
          await Promise.all([capture.stop(), playback.close()]);
          return;
        }
        void refreshInputDevices();
        const bootstrap = await realtimeVoiceApi.createSession({
          ...(chatId ? { chat_id: chatId } : {}),
          ...(replaceSessionId ? { replace_session_id: replaceSessionId } : {}),
          admission_mode: admissionMode,
        });
        if (
          startGeneration !== startGenerationRef.current ||
          manualStopRef.current
        ) {
          releaseBootstrap(bootstrap);
          await Promise.all([capture.stop(), playback.close()]);
          return;
        }
        if (!chatId) chatCreatedRef.current(bootstrap.chat_id);
        await connectBootstrap(bootstrap, startGeneration);
      } catch (reason) {
        if (startGeneration !== startGenerationRef.current) {
          await Promise.all([capture?.stop(), playback?.close()]);
          return;
        }
        await cleanupMedia();
        if (
          reason instanceof RealtimeVoiceApiError &&
          reason.code === "live_session_conflict"
        ) {
          setVoiceState(INITIAL_VOICE_STATE);
          setConflict({
            sessionId: String(reason.details.session_id || ""),
            agentId: String(reason.details.agent_id || "") || undefined,
            chatId: String(reason.details.chat_id || "") || undefined,
          });
          return;
        }
        setVoiceState({ ...INITIAL_VOICE_STATE, connection: "error" });
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    },
    [
      capabilities,
      chatId,
      cleanupMedia,
      clearReconnectTimer,
      connectBootstrap,
      enabled,
      forwardAudio,
      loadCapabilities,
      isCurrentGeneration,
      refreshInputDevices,
      restartCapture,
      admissionMode,
    ],
  );

  const stop = useCallback(async () => {
    startGenerationRef.current += 1;
    manualStopRef.current = true;
    clearReconnectTimer();
    clientRef.current?.stop();
    clientRef.current?.close();
    clientRef.current = null;
    releaseBootstrap(bootstrapRef.current);
    bootstrapRef.current = null;
    currentRunIdRef.current = null;
    hasPendingInputRef.current = false;
    pendingInputTextRef.current = "";
    inputPreviewPrefixRef.current = "";
    setVoiceState(INITIAL_VOICE_STATE);
    setInputTranscript("");
    setPendingInputState("idle");
    setPendingInputError(null);
    await cleanupMedia();
  }, [cleanupMedia, clearReconnectTimer]);

  useEffect(() => {
    if (enabled) return;
    startGenerationRef.current += 1;
    manualStopRef.current = true;
    clearReconnectTimer();
    clientRef.current?.close();
    clientRef.current = null;
    releaseBootstrap(bootstrapRef.current);
    bootstrapRef.current = null;
    currentRunIdRef.current = null;
    hasPendingInputRef.current = false;
    pendingInputTextRef.current = "";
    inputPreviewPrefixRef.current = "";
    setVoiceState(INITIAL_VOICE_STATE);
    setInputTranscript("");
    setPendingInputState("idle");
    setPendingInputError(null);
    void cleanupMedia();
  }, [cleanupMedia, clearReconnectTimer, enabled]);

  useEffect(() => {
    return () => {
      startGenerationRef.current += 1;
      manualStopRef.current = true;
      clearReconnectTimer();
      clientRef.current?.close();
      releaseBootstrap(bootstrapRef.current);
      bootstrapRef.current = null;
      void cleanupMedia();
    };
  }, [cleanupMedia, clearReconnectTimer]);

  const setMuted = useCallback(
    (next: boolean) => {
      mutedRef.current = next;
      setMutedState(next);
      captureRef.current?.setMuted(next);
      if (next) updateVoiceState({ input: "listening" });
    },
    [updateVoiceState],
  );

  const setInputDevice = useCallback(
    async (deviceId: string) => {
      inputDeviceIdRef.current = deviceId;
      setInputDeviceIdState(deviceId);
      if (captureRef.current) await restartCapture();
    },
    [restartCapture],
  );

  const interrupt = useCallback(() => {
    acceptOutputAudioRef.current = false;
    playbackRef.current?.interrupt();
    clientRef.current?.interrupt();
    updateVoiceState({ output: "interrupted" });
  }, [updateVoiceState]);

  const observeAgentRun = useCallback((): boolean => {
    return clientRef.current?.observeAgentRun() ?? false;
  }, []);

  const commitPending = useCallback((): boolean => {
    return clientRef.current?.commitPending() ?? false;
  }, []);

  const setAdmissionMode = useCallback((mode: VoiceAdmissionMode) => {
    setAdmissionModeState(mode);
    try {
      window.localStorage.setItem(ADMISSION_MODE_STORAGE_KEY, mode);
    } catch {
      // Browser storage is optional; the active session still updates.
    }
    clientRef.current?.setAdmissionMode(mode);
  }, []);

  const readyToStart = isRealtimeVoiceReady(capabilities);
  const status = deriveRealtimeVoiceStatus(voiceState);

  return {
    capabilities,
    readyToStart,
    status,
    connectionState: voiceState.connection,
    inputState: voiceState.input,
    agentState: voiceState.agent,
    outputState: voiceState.output,
    muted,
    inputDevices,
    inputDeviceId,
    admissionMode,
    inputTranscript,
    pendingInputState,
    pendingInputError,
    canCommitPending: hasPendingInputRef.current,
    assistantTranscript,
    error,
    conflict,
    start: () => begin(),
    confirmSwitch: () => begin(conflict?.sessionId),
    cancelSwitch: () => setConflict(null),
    stop,
    setMuted,
    setInputDevice,
    interrupt,
    observeAgentRun,
    commitPending,
    setAdmissionMode,
    reloadCapabilities: loadCapabilities,
  };
}
