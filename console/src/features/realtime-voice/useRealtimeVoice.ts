import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  RealtimeVoiceApiError,
  realtimeVoiceApi,
  type RealtimeVoiceBootstrap,
  type RealtimeVoiceCapabilities,
  type RealtimeVoiceMedia,
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

interface RealtimeVoiceState {
  connection: "idle" | "connecting" | "ready" | "reconnecting" | "error";
  input: "idle" | "listening" | "speaking";
  agent: "idle" | "working";
  output: "idle" | "speaking" | "interrupted" | "failed";
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

function releaseBootstrap(bootstrap: RealtimeVoiceBootstrap | null) {
  if (!bootstrap) return;
  // Never let cleanup of an old lease fail a newer connection. Unclaimed
  // bootstraps also expire server-side if the network is unavailable.
  void realtimeVoiceApi.endSession(bootstrap).catch(() => undefined);
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
  const [pendingInputError, setPendingInputError] = useState<string | null>(
    null,
  );
  const [assistantTranscript, setAssistantTranscript] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<ConflictState | null>(null);
  const [inputDevices, setInputDevices] = useState<MediaDeviceInfo[]>([]);
  const [inputDeviceId, setInputDeviceIdState] = useState("");

  const capabilitiesRef = useRef<RealtimeVoiceCapabilities | null>(null);
  const clientRef = useRef<RealtimeVoiceClient | null>(null);
  const captureRef = useRef<RealtimeAudioCapture | null>(null);
  const playbackRef = useRef<RealtimeAudioPlayback | null>(null);
  const bootstrapRef = useRef<RealtimeVoiceBootstrap | null>(null);
  const stopPromiseRef = useRef<Promise<void> | null>(null);
  const chatIdRef = useRef(chatId);
  chatIdRef.current = chatId;
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

  /** Invalidate the current generation and drop its connection and lease. */
  const abandonConnection = useCallback(() => {
    startGenerationRef.current += 1;
    manualStopRef.current = true;
    clearReconnectTimer();
    clientRef.current?.close();
    clientRef.current = null;
    releaseBootstrap(bootstrapRef.current);
    bootstrapRef.current = null;
  }, [clearReconnectTimer]);

  const fail = useCallback(
    async (message: string) => {
      abandonConnection();
      setVoiceState({ ...INITIAL_VOICE_STATE, connection: "error" });
      setError(message);
      await cleanupMedia();
    },
    [abandonConnection, cleanupMedia],
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
      const ownsCapture = () =>
        isCurrentGeneration(generation) && captureRef.current === capture;
      await capture.start(
        (pcm) => {
          if (ownsCapture()) forwardAudio(pcm);
        },
        () => {
          if (ownsCapture()) void restartCapture();
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
              setInputTranscript("");
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
            case "output.cancelled":
              if (
                typeof event.output_id === "string" &&
                playbackRef.current?.isActive(event.output_id)
              ) {
                playbackRef.current.interrupt();
                acceptOutputAudioRef.current = false;
                updateVoiceState({ output: "interrupted" });
              }
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
              setInputTranscript(String(event.text || ""));
              break;
            case "input_transcript.final":
              setInputTranscript(String(event.text || "").trim());
              setPendingInputError(null);
              break;
            case "input_transcript.failed":
              setInputTranscript("");
              setPendingInputError(t("realtimeVoice.transcriptionUnavailable"));
              break;
            case "input_turn.committed":
              setInputTranscript("");
              setPendingInputError(null);
              break;
            case "input_turn.rejected":
              setInputTranscript("");
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
            case "agent.input.accepted":
              if (eventRunId) currentRunIdRef.current = eventRunId;
              updateVoiceState({ agent: "working" });
              break;
            case "agent.input.consumed":
              if (!isStaleRun) updateVoiceState({ agent: "working" });
              break;
            case "agent.run.started":
              if (eventRunId) currentRunIdRef.current = eventRunId;
              updateVoiceState({ agent: "working" });
              if (event.status === "started") agentRunStartedRef.current();
              break;
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
              } else if (event.reason === "idle_timeout") {
                void fail(t("realtimeVoice.idleTimeout"));
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
          reconnectStartedRef.current ||= Date.now();
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
    [fail, isCurrentGeneration, updateVoiceState],
  );
  scheduleReconnectRef.current = scheduleReconnect;

  const begin = useCallback(
    async (replaceSessionId?: string) => {
      if (!enabled) return;
      abandonConnection();
      const startGeneration = startGenerationRef.current;
      manualStopRef.current = false;
      // Also resets provider readiness, output gating and pre-ready audio.
      void cleanupMedia();
      setError(null);
      setConflict(null);
      setVoiceState({ ...INITIAL_VOICE_STATE, connection: "connecting" });
      currentRunIdRef.current = null;
      setPendingInputError(null);
      reconnectStartedRef.current = 0;
      reconnectAttemptsRef.current = 0;

      let playback: RealtimeAudioPlayback | null = null;
      let capture: RealtimeAudioCapture | null = null;
      try {
        const loaded = capabilitiesRef.current ?? (await loadCapabilities());
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

        const ownsCapture = () =>
          isCurrentGeneration(startGeneration) &&
          captureRef.current === capture;
        // Both calls begin directly inside the click handler before bootstrap.
        await Promise.all([
          playback.unlock(),
          capture.start(
            (pcm) => {
              if (ownsCapture()) forwardAudio(pcm);
            },
            () => {
              if (ownsCapture()) void restartCapture();
            },
          ),
        ]);
        // A new connection must see the tail committed by the preceding stop.
        await stopPromiseRef.current;
        if (!isCurrentGeneration(startGeneration)) {
          await Promise.all([capture.stop(), playback.close()]);
          return;
        }
        void refreshInputDevices();
        const bootstrap = await realtimeVoiceApi.createSession({
          ...(chatId ? { chat_id: chatId } : {}),
          ...(replaceSessionId ? { replace_session_id: replaceSessionId } : {}),
        });
        if (!isCurrentGeneration(startGeneration)) {
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
      abandonConnection,
      chatId,
      cleanupMedia,
      connectBootstrap,
      enabled,
      forwardAudio,
      loadCapabilities,
      isCurrentGeneration,
      refreshInputDevices,
      restartCapture,
    ],
  );

  const stop = useCallback(() => {
    if (stopPromiseRef.current && manualStopRef.current)
      return stopPromiseRef.current;
    const precedingStop = stopPromiseRef.current;
    const generation = ++startGenerationRef.current;
    const stoppedChatId = chatIdRef.current;
    const bootstrap = bootstrapRef.current;
    manualStopRef.current = true;
    clearReconnectTimer();
    clientRef.current?.stop();
    clientRef.current?.close();
    clientRef.current = null;
    bootstrapRef.current = null;
    currentRunIdRef.current = null;
    setVoiceState(INITIAL_VOICE_STATE);
    setPendingInputError(null);
    const mediaCleanup = cleanupMedia();
    const isCurrent = () =>
      generation === startGenerationRef.current &&
      stoppedChatId === chatIdRef.current;
    const completion = (async () => {
      try {
        if (precedingStop) await precedingStop;
        if (bootstrap) {
          await realtimeVoiceApi.endSession(bootstrap);
          const history = await realtimeVoiceApi.getSessionHistory(bootstrap);
          if (!isCurrent()) return;
          // The host merges by message ID, retaining concurrent Agent output.
          timelineChangedRef.current?.(history.messages ?? []);
        }
        if (isCurrent()) setInputTranscript("");
      } catch {
        if (isCurrent()) {
          setError(
            "Could not finish saving or refreshing Voice Chat. Reload the conversation to check its history.",
          );
        }
      } finally {
        await mediaCleanup;
      }
    })();
    stopPromiseRef.current = completion;
    void completion.finally(() => {
      if (stopPromiseRef.current === completion) stopPromiseRef.current = null;
    });
    return completion;
  }, [cleanupMedia, clearReconnectTimer]);

  useEffect(() => {
    if (enabled) return;
    abandonConnection();
    currentRunIdRef.current = null;
    setVoiceState(INITIAL_VOICE_STATE);
    setInputTranscript("");
    setPendingInputError(null);
    void cleanupMedia();
  }, [abandonConnection, cleanupMedia, enabled]);

  useEffect(
    () => () => {
      abandonConnection();
      void cleanupMedia();
    },
    [abandonConnection, cleanupMedia],
  );

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

  const observeAgentRun = useCallback(
    () => clientRef.current?.observeAgentRun() ?? false,
    [],
  );

  return {
    capabilities,
    readyToStart: isRealtimeVoiceReady(capabilities),
    status: deriveRealtimeVoiceStatus(voiceState),
    inputState: voiceState.input,
    agentState: voiceState.agent,
    outputState: voiceState.output,
    muted,
    inputDevices,
    inputDeviceId,
    inputTranscript,
    pendingInputError,
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
    reloadCapabilities: loadCapabilities,
  };
}
