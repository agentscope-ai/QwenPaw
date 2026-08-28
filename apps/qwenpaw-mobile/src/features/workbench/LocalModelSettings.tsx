import { MobileAlert } from "@/components/MobileAlert";
import {
  CircleStop,
  Cpu,
  Download,
  Server,
} from "lucide-react-native";
import { useCallback, useEffect, useState } from "react";

import { QwenPawClient } from "../../api/client";
import type { Connection } from "../../api/types";
import { IosGroup, IosRow } from "../../components/IosList";

interface LocalServerStatus {
  available: boolean;
  installable: boolean;
  installed: boolean;
  port: number | null;
  model_name: string | null;
  message: string | null;
}

interface LocalModel {
  id: string;
  name: string;
  size_bytes: number;
  downloaded: boolean;
  source: "huggingface" | "modelscope" | "auto";
}

interface DownloadProgress {
  status: string;
  model_name: string | null;
  downloaded_bytes: number;
  total_bytes: number | null;
  error: string | null;
}

export function LocalModelSettings({
  connection,
  onChanged,
}: {
  connection: Connection;
  onChanged: () => Promise<void>;
}) {
  const [server, setServer] = useState<LocalServerStatus | null>(null);
  const [models, setModels] = useState<LocalModel[]>([]);
  const [runtimeProgress, setRuntimeProgress] = useState<DownloadProgress | null>(null);
  const [modelProgress, setModelProgress] = useState<DownloadProgress | null>(null);
  const [supported, setSupported] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const client = new QwenPawClient(connection);
      const [status, catalog, runtimeDownload, modelDownload] = await Promise.all([
        client.inspectModule("/local-models/server"),
        client.inspectModule("/local-models/models"),
        client.inspectModule("/local-models/server/download"),
        client.inspectModule("/local-models/models/download"),
      ]);
      setServer(status as LocalServerStatus);
      setModels(Array.isArray(catalog) ? catalog as LocalModel[] : []);
      setRuntimeProgress(runtimeDownload as DownloadProgress);
      setModelProgress(modelDownload as DownloadProgress);
      setSupported(true);
    } catch {
      setSupported(false);
    }
  }, [connection]);

  useEffect(() => {
    const task = setTimeout(() => void load(), 0);
    return () => clearTimeout(task);
  }, [load]);

  useEffect(() => {
    const active = [runtimeProgress?.status, modelProgress?.status].some(
      (status) => status === "pending" || status === "downloading" || status === "canceling",
    );
    if (!active) return;
    const timer = setInterval(() => void load(), 1500);
    return () => clearInterval(timer);
  }, [load, modelProgress?.status, runtimeProgress?.status]);

  const run = async (action: () => Promise<unknown>, success?: string) => {
    if (busy) return;
    setBusy(true);
    try {
      await action();
      await load();
      await onChanged();
      if (success) MobileAlert.alert(success);
    } catch (reason) {
      MobileAlert.alert("操作失败", errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  if (!supported || !server) return null;

  const runtimeDownloading = isDownloading(runtimeProgress);
  const modelDownloading = isDownloading(modelProgress);

  return (
    <>
      <IosGroup title="本地模型运行时">
        <IosRow
          icon={Server}
          iconTone="ink"
          label={server.installed ? "llama.cpp 已安装" : "安装 llama.cpp"}
          onPress={server.installed || busy ? undefined : () => void run(
            () => new QwenPawClient(connection).mutateModule(
              "/local-models/server/download",
              "POST",
            ),
          )}
          subtitle={runtimeDownloading
            ? progressText(runtimeProgress)
            : server.message || (server.installed ? "本地推理运行时可用" : "下载并安装运行时")}
          trailing={server.model_name ? `:${server.port ?? "-"}` : undefined}
        />
        {server.model_name ? (
          <IosRow
            destructive
            icon={CircleStop}
            label="停止本地模型"
            onPress={busy ? undefined : () => void run(
              () => new QwenPawClient(connection).mutateModule(
                "/local-models/server",
                "DELETE",
              ),
              "本地模型已停止",
            )}
            subtitle={server.model_name}
          />
        ) : null}
      </IosGroup>

      {server.installed ? (
        <IosGroup title="本地模型">
          {models.map((model) => (
            <IosRow
              icon={model.downloaded ? Cpu : Download}
              iconTone={model.downloaded ? "ink" : "orange"}
              key={model.id}
              label={model.name}
              onPress={busy ? undefined : () => openModel(model)}
              subtitle={modelProgress?.model_name === model.id && modelDownloading
                ? progressText(modelProgress)
                : model.downloaded
                  ? `${formatBytes(model.size_bytes)} · 已下载`
                  : `${formatBytes(model.size_bytes)} · ${model.source}`}
              trailing={server.model_name === model.id ? "运行中" : undefined}
            />
          ))}
        </IosGroup>
      ) : null}
    </>
  );

  function openModel(model: LocalModel) {
    if (!model.downloaded) {
      MobileAlert.alert("下载本地模型？", `${model.name} · ${formatBytes(model.size_bytes)}`, [
        { text: "取消", style: "cancel" },
        {
          text: "下载",
          onPress: () => void run(() => new QwenPawClient(connection).mutateModule(
            "/local-models/models/download",
            "POST",
            { model_name: model.id, source: model.source },
          )),
        },
      ]);
      return;
    }
    MobileAlert.alert(model.name, "管理已下载的本地模型", [
      { text: "取消", style: "cancel" },
      {
        text: server?.model_name === model.id ? "正在运行" : "启动",
        onPress: server?.model_name === model.id ? undefined : () => void run(
          () => new QwenPawClient(connection).mutateModule(
            "/local-models/server",
            "POST",
            { model_id: model.id },
          ),
          "本地模型已启动",
        ),
      },
      {
        text: "删除",
        style: "destructive",
        onPress: () => void run(
          () => new QwenPawClient(connection).mutateModule(
            `/local-models/models/${encodeURIComponent(model.id)}`,
            "DELETE",
          ),
          "本地模型已删除",
        ),
      },
    ]);
  }
}

function isDownloading(progress: DownloadProgress | null): boolean {
  return progress?.status === "pending" || progress?.status === "downloading" ||
    progress?.status === "canceling";
}

function progressText(progress: DownloadProgress | null): string {
  if (!progress) return "准备中";
  if (progress.error) return progress.error;
  if (!progress.total_bytes) return `已下载 ${formatBytes(progress.downloaded_bytes)}`;
  const percent = Math.round(progress.downloaded_bytes / progress.total_bytes * 100);
  return `${percent}% · ${formatBytes(progress.downloaded_bytes)} / ${formatBytes(progress.total_bytes)}`;
}

function formatBytes(value: number): string {
  if (!value) return "大小未知";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index > 1 ? 1 : 0)} ${units[index]}`;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "本地模型操作失败";
}
