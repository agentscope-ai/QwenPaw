import { MobileAlert } from "@/components/MobileAlert";
import { AudioLines, Cpu, Mic } from "lucide-react-native";
import { useCallback, useEffect, useState } from "react";

import { QwenPawClient } from "../../api/client";
import type { Connection } from "../../api/types";
import { IosGroup, IosRow } from "../../components/IosList";
import { ModuleError, ModuleFooter, ModuleLoading } from "./ModuleState";

interface VoiceState {
  audioMode: string;
  providerType: string;
  providerId: string;
  providers: { id: string; name: string; available: boolean }[];
  localWhisper: { available?: boolean; ffmpeg_installed?: boolean; whisper_installed?: boolean };
}

export function VoiceSettings({ connection }: { connection: Connection }) {
  const [state, setState] = useState<VoiceState | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const client = new QwenPawClient(connection);
      const [mode, type, providers, local] = await Promise.all([
        client.inspectModule("/workspace/audio-mode"),
        client.inspectModule("/workspace/transcription-provider-type"),
        client.inspectModule("/workspace/transcription-providers"),
        client.inspectModule("/workspace/local-whisper-status"),
      ]) as [
        { audio_mode?: string },
        { transcription_provider_type?: string },
        { providers?: VoiceState["providers"]; configured_provider_id?: string },
        VoiceState["localWhisper"],
      ];
      setError(null);
      setState({
        audioMode: mode.audio_mode ?? "auto",
        providerType: type.transcription_provider_type ?? "disabled",
        providerId: providers.configured_provider_id ?? "",
        providers: providers.providers ?? [],
        localWhisper: local,
      });
    } catch (reason) {
      setError(errorMessage(reason));
    }
  }, [connection]);

  useEffect(() => {
    const task = setTimeout(() => void load(), 0);
    return () => clearTimeout(task);
  }, [load]);

  const update = async (path: string, body: Record<string, unknown>) => {
    try {
      await new QwenPawClient(connection).mutateModule(path, "PUT", body);
      await load();
    } catch (reason) {
      MobileAlert.alert("保存失败", errorMessage(reason));
    }
  };

  const chooseAudioMode = () => MobileAlert.alert("音频处理", undefined, [
    { text: "自动转写", onPress: () => void update("/workspace/audio-mode", { audio_mode: "auto" }) },
    { text: "原生多模态", onPress: () => void update("/workspace/audio-mode", { audio_mode: "native" }) },
    { text: "取消", style: "cancel" },
  ]);

  const chooseProviderType = () => MobileAlert.alert("语音转写", undefined, [
    { text: "关闭", onPress: () => void update("/workspace/transcription-provider-type", { transcription_provider_type: "disabled" }) },
    { text: "Whisper API", onPress: () => void update("/workspace/transcription-provider-type", { transcription_provider_type: "whisper_api" }) },
    { text: "本地 Whisper", onPress: () => void update("/workspace/transcription-provider-type", { transcription_provider_type: "local_whisper" }) },
    { text: "取消", style: "cancel" },
  ]);

  const chooseProvider = () => {
    if (!state) return;
    MobileAlert.alert("Whisper Provider", undefined, [
      ...state.providers.filter((item) => item.available).map((provider) => ({
        text: provider.name,
        onPress: () => void update(
          "/workspace/transcription-provider",
          { provider_id: provider.id },
        ),
      })),
      { text: "清除选择", onPress: () => void update("/workspace/transcription-provider", { provider_id: "" }) },
      { text: "取消", style: "cancel" },
    ]);
  };

  if (error) return <ModuleError message={error} onRetry={() => void load()} />;
  if (!state) return <ModuleLoading />;

  return (
    <>
      <IosGroup title="音频消息">
        <IosRow
          icon={AudioLines}
          label="处理方式"
          onPress={chooseAudioMode}
          subtitle="自动转写或直接交给多模态模型"
          trailing={state.audioMode === "native" ? "原生" : "自动"}
        />
      </IosGroup>
      <IosGroup title="语音转写">
        <IosRow
          icon={Mic}
          label="转写引擎"
          onPress={chooseProviderType}
          trailing={providerTypeLabel(state.providerType)}
        />
        <IosRow
          icon={Cpu}
          iconTone="ink"
          label="Whisper Provider"
          onPress={chooseProvider}
          subtitle={`${state.providers.filter((item) => item.available).length} 个可用 Provider`}
          trailing={state.providerId || "未选择"}
        />
        <IosRow
          icon={Cpu}
          iconTone="ink"
          label="本地 Whisper"
          subtitle={`FFmpeg ${state.localWhisper.ffmpeg_installed ? "已安装" : "未安装"} · Whisper ${state.localWhisper.whisper_installed ? "已安装" : "未安装"}`}
          trailing={state.localWhisper.available ? "可用" : "不可用"}
        />
      </IosGroup>
      <ModuleFooter>这些设置属于当前 QwenPaw，切换本地或云端会读取各自配置。</ModuleFooter>
    </>
  );
}

function providerTypeLabel(value: string): string {
  if (value === "whisper_api") return "Whisper API";
  if (value === "local_whisper") return "本地 Whisper";
  return "关闭";
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "操作失败";
}
