import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import {
  notifyPluginChange,
  subscribeToPluginChanges,
} from "../../../utils/pluginChangeEvents";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { useAgentStore } from "../../../stores/agentStore";
import { reviewDependencyUpgrade } from "../PluginManager/dependencyUpgrade";
import type { LocalWhisperStatus } from "../../../api/modules/agent";

// ─── Types ──────────────────────────────────────────────────────────────────

export interface TranscriptionProvider {
  id: string;
  name: string;
  available: boolean;
}

export type { LocalWhisperStatus } from "../../../api/modules/agent";

// ─── Hook ───────────────────────────────────────────────────────────────────

export function useVoiceTranscription() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { selectedAgent } = useAgentStore();
  const requestGenerationRef = useRef(0);
  const installingRef = useRef(false);
  const loadedAgentRef = useRef<string | null>(null);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [loadedAgent, setLoadedAgent] = useState<string | null>(null);
  const [audioMode, setAudioMode] = useState("auto");
  const [providerType, setProviderType] = useState("disabled");
  const [providers, setProviders] = useState<TranscriptionProvider[]>([]);
  const [selectedProviderId, setSelectedProviderId] = useState("");
  const [transcriptionModel, setTranscriptionModel] = useState("whisper-1");
  const [localWhisperStatus, setLocalWhisperStatus] =
    useState<LocalWhisperStatus | null>(null);

  const loadSettings = useCallback(
    async (requestedAgent: string) => {
      const requestGeneration = ++requestGenerationRef.current;
      const isCurrentRequest = () =>
        requestGenerationRef.current === requestGeneration &&
        useAgentStore.getState().selectedAgent === requestedAgent;

      if (!isCurrentRequest()) return;
      loadedAgentRef.current = null;
      setLoadedAgent(null);
      setLoading(true);
      setSaving(false);
      try {
        const [modeRes, provTypeRes, provRes, modelRes, lwStatus] =
          await Promise.all([
            api.getAudioMode(),
            api.getTranscriptionProviderType(),
            api.getTranscriptionProviders(),
            api.getTranscriptionModel(),
            api.getLocalWhisperStatus(),
          ]);
        if (!isCurrentRequest()) return;
        loadedAgentRef.current = requestedAgent;
        setLoadedAgent(requestedAgent);
        setAudioMode(modeRes.audio_mode ?? "auto");
        setProviderType(provTypeRes.transcription_provider_type ?? "disabled");
        setProviders(provRes.providers ?? []);
        setSelectedProviderId(provRes.configured_provider_id ?? "");
        setTranscriptionModel(modelRes.transcription_model ?? "whisper-1");
        setLocalWhisperStatus(lwStatus);
        setError(null);
      } catch (err) {
        if (!isCurrentRequest()) return;
        console.error("Failed to load voice transcription settings:", err);
        setError(err);
        message.error(t("voiceTranscription.loadFailed"));
      } finally {
        if (isCurrentRequest()) setLoading(false);
      }
    },
    [message, t],
  );

  const fetchSettings = useCallback(
    () => loadSettings(selectedAgent),
    [loadSettings, selectedAgent],
  );

  useEffect(() => {
    void fetchSettings();
    return () => {
      requestGenerationRef.current += 1;
      loadedAgentRef.current = null;
    };
  }, [fetchSettings]);

  // Refresh plugin state independently of unsaved voice settings. Polling also
  // picks up changes from other tabs and the plugin management page.
  useEffect(() => {
    if (
      loading ||
      error ||
      (providerType !== "local_whisper" && audioMode !== "native")
    )
      return;
    let cancelled = false;
    let requestSequence = 0;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      const sequence = ++requestSequence;
      const isCurrentRequest = () => !cancelled && sequence === requestSequence;
      try {
        const status = await api.getLocalWhisperStatus();
        if (isCurrentRequest()) setLocalWhisperStatus(status);
      } catch {
        // Do not leave a previously green status after losing the connection.
        if (isCurrentRequest())
          setLocalWhisperStatus(
            (status) =>
              status && {
                ...status,
                available: false,
                state: "failed",
                error: t("voiceTranscription.loadFailed"),
              },
          );
      }
    };
    const poll = async () => {
      await refresh();
      if (!cancelled) timer = setTimeout(() => void poll(), 2000);
    };
    const onChange = () => void refresh();
    const unsubscribe = subscribeToPluginChanges(onChange);
    window.addEventListener("focus", onChange);
    timer = setTimeout(() => void poll(), 2000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      unsubscribe();
      window.removeEventListener("focus", onChange);
    };
  }, [audioMode, providerType, loading, error, selectedAgent, t]);

  const installLocalWhisper = useCallback(async () => {
    const operation = localWhisperStatus?.dependency_upgrade;
    if (
      installingRef.current ||
      (localWhisperStatus?.state === "installing" && !operation)
    )
      return;
    installingRef.current = true;
    const generation = requestGenerationRef.current;
    setLocalWhisperStatus(
      (status) => status && { ...status, state: "installing", error: "" },
    );
    try {
      if (operation) await reviewDependencyUpgrade(operation, t);
      const status = operation
        ? await api.getLocalWhisperStatus()
        : await api.installLocalWhisper();
      notifyPluginChange();
      if (generation === requestGenerationRef.current)
        setLocalWhisperStatus(status);
    } catch (err) {
      if (generation === requestGenerationRef.current) {
        setLocalWhisperStatus(
          (status) =>
            status && {
              ...status,
              state: "failed",
              error: String(err),
            },
        );
      }
    } finally {
      installingRef.current = false;
    }
  }, [localWhisperStatus?.state, localWhisperStatus?.dependency_upgrade, t]);

  const enableLocalWhisper = useCallback(async () => {
    const generation = requestGenerationRef.current;
    try {
      await api.enableLocalWhisper();
      notifyPluginChange();
      const status = await api.getLocalWhisperStatus();
      if (generation === requestGenerationRef.current)
        setLocalWhisperStatus(status);
    } catch (err) {
      message.error(String(err));
    }
  }, [message]);

  const handleSave = useCallback(
    async (automatic = false) => {
      const currentAgent = useAgentStore.getState().selectedAgent;
      const ownerAgent = loadedAgentRef.current;
      if (
        ownerAgent === null ||
        ownerAgent !== loadedAgent ||
        ownerAgent !== currentAgent
      ) {
        await loadSettings(currentAgent);
        return;
      }
      if (providerType === "whisper_api" && !selectedProviderId) return;

      const isCurrentOwner = () =>
        loadedAgentRef.current === ownerAgent &&
        useAgentStore.getState().selectedAgent === ownerAgent;
      setSaving(true);
      try {
        const promises: Promise<unknown>[] = [
          api.updateAudioMode(audioMode),
          api.updateTranscriptionProviderType(providerType),
        ];
        if (providerType === "whisper_api") {
          promises.push(api.updateTranscriptionProvider(selectedProviderId));
          promises.push(api.updateTranscriptionModel(transcriptionModel));
        }
        await Promise.all(promises);
        if (isCurrentOwner() && !automatic) {
          message.success(t("voiceTranscription.saveSuccess"));
        }
      } catch (err) {
        if (!isCurrentOwner()) return;
        if (automatic) throw err;
        console.error("Failed to save voice transcription settings:", err);
        message.error(t("voiceTranscription.saveFailed"));
      } finally {
        if (isCurrentOwner()) setSaving(false);
      }
    },
    [
      audioMode,
      loadedAgent,
      loadSettings,
      message,
      providerType,
      selectedProviderId,
      transcriptionModel,
      t,
    ],
  );

  // Derived state
  const availableProviders = providers.filter((p) => p.available);
  const showProviderSection = audioMode !== "native";
  const isLocalWhisper = providerType === "local_whisper";
  const isWhisperApi = providerType === "whisper_api";
  const ready = !loading && error === null && loadedAgent === selectedAgent;

  return {
    loading,
    ready,
    saving,
    error,
    audioMode,
    setAudioMode,
    providerType,
    setProviderType,
    selectedProviderId,
    setSelectedProviderId,
    transcriptionModel,
    setTranscriptionModel,
    localWhisperStatus,
    installLocalWhisper,
    enableLocalWhisper,
    availableProviders,
    showProviderSection,
    isLocalWhisper,
    isWhisperApi,
    fetchSettings,
    handleSave,
  };
}
