import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../hooks/useAppMessage";
import {
  voiceApi,
  type VoiceConfiguration,
  type VoiceSettings,
  transcriptionErrorKey,
} from "@/api/modules/voice";
import { useVoiceScope } from "@/api/voiceScope";

export type TranscriptionProvider = VoiceConfiguration["providers"][number];
export type LocalWhisperStatus = VoiceConfiguration["local_status"];
const empty: VoiceSettings = {
  audio_mode: "auto",
  transcription_provider_type: "disabled",
  transcription_provider_id: "",
  transcription_model: "",
  transcription_local_model: "base",
};
export function useVoiceTranscription() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const scope = useVoiceScope();
  const [loaded, setLoaded] = useState<{
    key: string;
    data: VoiceConfiguration;
  } | null>(null);
  const [draft, setDraft] = useState(empty);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState("");
  const active = useRef<AbortController | null>(null);
  const feedback = useRef({ message, t });
  feedback.current = { message, t };
  const valid = loaded?.key === scope.key && scope.canManage;
  const settings = valid ? draft : empty;
  const config = valid ? loaded.data : null;
  const fetchSettings = useCallback(async () => {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setLoaded(null);
    setTestResult("");
    setSaving(false);
    setTesting(false);
    if (!scope.canManage) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const data = await voiceApi.getSettings(scope, controller.signal);
      if (!scope.current() || controller.signal.aborted) return;
      setLoaded({ key: scope.key, data });
      setDraft(data.settings);
    } catch {
      if (scope.current() && !controller.signal.aborted)
        feedback.current.message.error(
          feedback.current.t("voiceTranscription.loadFailed"),
        );
    } finally {
      if (scope.current() && !controller.signal.aborted) setLoading(false);
    }
  }, [scope]);
  useEffect(() => {
    void fetchSettings();
    return () => active.current?.abort();
  }, [fetchSettings]);
  const handleSave = async () => {
    if (!valid || !scope.current() || loading || saving || testing) return;
    const controller = new AbortController();
    active.current?.abort();
    active.current = controller;
    setSaving(true);
    setTestResult("");
    try {
      const data = await voiceApi.saveSettings(
        settings,
        scope,
        controller.signal,
      );
      if (!scope.current() || controller.signal.aborted) return;
      setLoaded({
        key: scope.key,
        data,
      });
      message.success(t("voiceTranscription.saveSuccess"));
      window.dispatchEvent(new Event("voice-transcription-changed"));
    } catch {
      if (scope.current() && !controller.signal.aborted)
        message.error(t("voiceTranscription.saveFailed"));
    } finally {
      if (scope.current() && !controller.signal.aborted) setSaving(false);
    }
  };
  const dirty =
    !!config && JSON.stringify(settings) !== JSON.stringify(config.settings);
  const handleTest = async (file: File) => {
    if (!valid || !scope.current() || dirty || loading || saving || testing)
      return;
    const controller = new AbortController();
    active.current?.abort();
    active.current = controller;
    setTesting(true);
    setTestResult("");
    try {
      const result = await voiceApi.test(file, scope, controller.signal);
      if (scope.current() && !controller.signal.aborted)
        setTestResult(result.text);
    } catch (error) {
      if (scope.current() && !controller.signal.aborted)
        message.error(t(transcriptionErrorKey(error)));
    } finally {
      if (scope.current() && !controller.signal.aborted) setTesting(false);
    }
  };
  const update = (key: keyof VoiceSettings) => (value: string) =>
    setDraft((previous) => ({ ...previous, [key]: value }));
  return {
    loading,
    saving,
    testing,
    testResult: valid ? testResult : "",
    canManage: scope.canManage,
    canSave: valid && !loading && !saving && !testing,
    canTest: valid && !dirty && !loading && !saving && !testing,
    audioMode: settings.audio_mode,
    setAudioMode: update("audio_mode"),
    providerType: settings.transcription_provider_type,
    setProviderType: update("transcription_provider_type"),
    selectedProviderId: settings.transcription_provider_id,
    setSelectedProviderId: update("transcription_provider_id"),
    model: settings.transcription_model,
    setModel: update("transcription_model"),
    localModel: settings.transcription_local_model,
    setLocalModel: update("transcription_local_model"),
    localModels: config?.local_models ?? [],
    localWhisperStatus: config?.local_status ?? null,
    availableProviders: config?.providers.filter((p) => p.available) ?? [],
    showProviderSection: settings.audio_mode !== "native",
    isLocalWhisper: settings.transcription_provider_type === "local_whisper",
    isWhisperApi: settings.transcription_provider_type === "whisper_api",
    fetchSettings,
    handleSave,
    handleTest,
  };
}
