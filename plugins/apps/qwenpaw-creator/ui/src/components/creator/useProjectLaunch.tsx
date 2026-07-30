import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Modal, message } from "antd";
import type {
  CreatorContentPart,
  CreatorScenario,
  ModelConfigData,
} from "@/contracts/creator";
import {
  createAssetImport,
  createProject,
  getAssetImport,
  getModelConfig,
  getTask,
  ingestAssetFile,
  ingestAssetValue,
  newClientId,
  sendCreatorMessage,
} from "@/api/creator";
import { taskErrorMessage } from "@/lib/taskPresentation";
import { creatorStatusLabel } from "@/lib/creatorPresentation";
import { useRouter } from "@/routing/navigation";

export type AttachmentDraft =
  | {
      kind: "file";
      id: string;
      file: File;
      source: "file" | "folder";
      relativePath?: string;
    }
  | { kind: "url"; id: string; url: string };

export const MODES = [
  { key: "agent", label: "Agent", enabled: true },
  { key: "loop", label: "Loop", enabled: false },
] as const;

export const AUTO_PROJECT_NAME_LENGTH = 20;

export const SCENARIO_OPTIONS: { key: CreatorScenario; label: string }[] = [
  { key: "short_drama", label: "短剧" },
  { key: "video_edit", label: "剪辑" },
  { key: "general", label: "通用" },
];

export const SCENARIO_TERMS: Record<CreatorScenario, { description: string }> =
  {
    general: {
      description:
        '例：以"我在马路边，捡到一分钱"的儿歌歌词为故事内容，做一个1分钟视频。',
    },
    short_drama: {
      description:
        "例：霸道总裁短剧。要突出快节奏，强化戏剧冲突，故事要有高频反转，最后要有个美好结局。",
    },
    video_edit: {
      description:
        "例：把我上传的这段黑白默片老电影，剪辑成一段新视频。新视频长度为30秒。新视频要用彩色图像替换到原有的黑白图像。新视频要给人物加上合适的中文配音。",
    },
  };

export const CONTENT_TYPE_OPTIONS: { key: string; label: string }[] = [
  { key: "pet_video", label: "宠物" },
  { key: "gaming", label: "游戏" },
  { key: "sports", label: "体育" },
  { key: "travel_vlog", label: "旅行" },
  { key: "interview", label: "采访" },
  { key: "general", label: "通用" },
];

const terminal = new Set(["SUCCEEDED", "FAILED", "CANCELLED", "QUARANTINED"]);
const wait = (ms: number) =>
  new Promise((resolve) => window.setTimeout(resolve, ms));

function projectNameFromDescription(description: string): string {
  const normalized = description.trim().replace(/\s+/g, " ");
  return Array.from(normalized).slice(0, AUTO_PROJECT_NAME_LENGTH).join("");
}

async function waitForTask(
  projectId: string,
  taskId: string,
): Promise<string[]> {
  for (;;) {
    const task = await getTask(projectId, taskId);
    if (terminal.has(task.status)) {
      if (task.status !== "SUCCEEDED") {
        throw new Error(
          taskErrorMessage(
            task.error,
            `素材处理失败（${creatorStatusLabel(task.status)}）`,
          ),
        );
      }
      return task.resultRefs;
    }
    await wait(800);
  }
}

export function chipLabel(att: AttachmentDraft): { tag: string; name: string } {
  if (att.kind === "url") return { tag: "URL", name: att.url };
  if (att.source === "folder")
    return { tag: "DIR", name: att.relativePath || att.file.name };
  const suffix = att.file.name.split(".").pop()?.toLowerCase() || "";
  const type = att.file.type;
  if (type.startsWith("image/")) return { tag: "IMG", name: att.file.name };
  if (type.startsWith("video/")) return { tag: "VID", name: att.file.name };
  if (type.startsWith("audio/")) return { tag: "AUD", name: att.file.name };
  return {
    tag: suffix ? suffix.toUpperCase().slice(0, 4) : "DOC",
    name: att.file.name,
  };
}

function remoteUrlContentPart(url: string): CreatorContentPart {
  let pathname = "";
  try {
    pathname = new URL(url).pathname.toLowerCase();
  } catch {
    return { type: "text", text: `远程素材 URL：${url}` };
  }
  if (/\.(png|jpe?g|webp|gif|bmp|avif)$/.test(pathname)) {
    return { type: "image_url", image_url: { url } };
  }
  if (/\.(mp4|mov|m4v|webm|mkv|avi|mpeg|mpg)$/.test(pathname)) {
    return { type: "video_url", video_url: { url } };
  }
  return { type: "text", text: `远程素材 URL：${url}` };
}

/**
 * Shared Project launch state machine used by both the inline hero composer
 * and the legacy modal composer: draft fields, attachment intake (file /
 * folder / URL), required-model validation and the idempotent launch flow.
 */
export function useProjectLaunch(options?: { onLaunched?: () => void }) {
  const onLaunched = options?.onLaunched;
  const router = useRouter();
  const [projectName, setProjectName] = useState("");
  const [projectDescription, setProjectDescription] = useState("");
  const [scenario, setScenario] = useState<CreatorScenario>("short_drama");
  const [contentType, setContentType] = useState<string | null>(null);
  const [resolution, setResolution] = useState<"720P" | "1080P">("720P");
  const [aspectRatio, setAspectRatio] = useState<string>("16:9");
  const [attachments, setAttachments] = useState<AttachmentDraft[]>([]);
  const [urlDraft, setUrlDraft] = useState("");
  const [launching, setLaunching] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const projectRequest = useRef({ signature: "", id: "" });
  const initialMessageRequests = useRef(new Map<string, string>());
  const sourceRequestIds = useRef(new Map<string, string>());
  const [modelConfig, setModelConfig] = useState<ModelConfigData | null>(null);
  const [modelConfigModalOpen, setModelConfigModalOpen] = useState(false);
  const hasUrl =
    urlDraft.trim().length > 0 || attachments.some((att) => att.kind === "url");
  const hasAttachments = attachments.length > 0 || hasUrl;
  const missingRequiredModels: string[] | null = useMemo(() => {
    if (!modelConfig) return null;
    const config = modelConfig as Partial<ModelConfigData>;
    const required: ("vlm" | "image" | "video")[] =
      scenario === "short_drama"
        ? ["vlm", "image", "video"]
        : scenario === "video_edit" || hasAttachments
        ? ["vlm"]
        : [];
    const missing: string[] = [];
    for (const type of required) {
      const item = config[type];
      const ok =
        type === "vlm" && config.vlm?.use_llm && config.llm?.model_name
          ? Boolean(config.vlm.enabled)
          : Boolean(item?.model_name && item.enabled);
      if (!ok) missing.push(type);
    }
    return missing;
  }, [modelConfig, scenario, hasAttachments]);
  const refreshModelConfig = useCallback(() => {
    getModelConfig()
      .then(setModelConfig)
      .catch(() => setModelConfig(null));
  }, []);
  useEffect(() => {
    refreshModelConfig();
  }, [refreshModelConfig, scenario, hasAttachments]);

  const requestIdFor = (key: string) => {
    const existing = sourceRequestIds.current.get(key);
    if (existing) return existing;
    const created = newClientId("asset");
    sourceRequestIds.current.set(key, created);
    return created;
  };

  const projectRequestIdFor = (signature: string) => {
    if (projectRequest.current.signature !== signature) {
      projectRequest.current = { signature, id: newClientId("project") };
    }
    return projectRequest.current.id;
  };

  const stopOnOversizedFiles = (files: File[]) => {
    // 100 * 1024 * 1024: 100MB
    const oversized = files.filter((file) => file.size > 104857600);
    if (oversized.length > 0) {
      const errorMessage = `${oversized.map((f) => f.name).join("\n")}`;
      Modal.error({
        title: "文件尺寸超过 100MB 限制",
        content: <div style={{ whiteSpace: "pre-wrap" }}>{errorMessage}</div>,
      });
      return true;
    }
    return false;
  };

  const addFiles = useCallback(
    (files: FileList | File[], source: "file" | "folder" = "file") => {
      if (stopOnOversizedFiles(Array.from(files))) {
        return;
      }
      const drafts: AttachmentDraft[] = Array.from(files).map((file) => ({
        kind: "file",
        id: newClientId("att"),
        file,
        source,
        relativePath:
          source === "folder"
            ? (file as File & { webkitRelativePath?: string })
                .webkitRelativePath || file.name
            : undefined,
      }));
      setAttachments((prev) => [...prev, ...drafts]);
    },
    [],
  );

  const addUrl = () => {
    const url = urlDraft.trim();
    if (!url) return;
    if (!/^https?:\/\//i.test(url)) {
      message.warning("请输入以 http(s):// 开头的链接");
      return;
    }
    setAttachments((prev) => [
      ...prev,
      { kind: "url", id: `att-${Date.now()}`, url },
    ]);
    setUrlDraft("");
  };

  const removeAttachment = (id: string) => {
    setAttachments((prev) => prev.filter((att) => att.id !== id));
  };

  const isVideoEdit = scenario === "video_edit";
  const hasMissingModels =
    missingRequiredModels !== null && missingRequiredModels.length > 0;
  const canLaunch =
    projectDescription.trim().length > 0 &&
    !launching &&
    (!isVideoEdit || contentType !== null) &&
    !hasMissingModels;

  const handleScenarioChange = (next: CreatorScenario) => {
    setScenario(next);
    if (next !== "video_edit") setContentType(null);
  };

  const launchHint = () => {
    if (!projectDescription.trim()) return "请用文字描述你的目标";
    if (isVideoEdit && contentType === null) return "请选择视频剪辑的内容类型";
    if (hasMissingModels) return "请先配置当前场景必选的模型";
    return undefined;
  };

  const handleLaunch = async () => {
    if (!projectDescription.trim()) {
      message.warning("请先用文字描述你的目标，附件会作为项目资产入库");
      return;
    }
    if (isVideoEdit && contentType === null) {
      message.warning("请选择视频剪辑的内容类型");
      return;
    }
    if (hasMissingModels) {
      message.warning("请先配置当前场景必选的模型");
      return;
    }
    const pendingUrl = urlDraft.trim();
    if (pendingUrl && !/^https?:\/\//i.test(pendingUrl)) {
      message.warning("URL 格式不正确，请以 http:// 或 https:// 开头");
      return;
    }
    setLaunching(true);
    try {
      const resolvedProjectName =
        projectName.trim() || projectNameFromDescription(projectDescription);
      const projectPayload = {
        name: resolvedProjectName,
        description: projectDescription.trim(),
        scenario,
        resolution,
        aspectRatio,
        contentType: isVideoEdit ? contentType : null,
        // With no assets, let Project creation persist the first Goal and
        // message atomically.  This avoids an observable IDLE Project between
        // navigation and the follow-up /messages request.
        initialGoal:
          attachments.length === 0 && !pendingUrl
            ? projectDescription.trim()
            : undefined,
      };
      const projectSignature = JSON.stringify(projectPayload);
      const project = await createProject({
        clientRequestId: projectRequestIdFor(projectSignature),
        ...projectPayload,
      });

      const fileAttachments = attachments.filter(
        (att): att is Extract<AttachmentDraft, { kind: "file" }> =>
          att.kind === "file",
      );
      const folderFiles = fileAttachments.filter(
        (att) => att.source === "folder",
      );
      const looseFiles = fileAttachments.filter(
        (att) => att.source !== "folder",
      );
      const committedUrlAttachments = attachments.filter(
        (att): att is Extract<AttachmentDraft, { kind: "url" }> =>
          att.kind === "url",
      );
      const urlAttachments = pendingUrl
        ? [
            ...committedUrlAttachments,
            { kind: "url" as const, id: `att-${Date.now()}`, url: pendingUrl },
          ]
        : committedUrlAttachments;

      if (projectPayload.initialGoal) {
        router.push(`/project/${project.projectId}/plan`);
        onLaunched?.();
        projectRequest.current = { signature: "", id: "" };
        initialMessageRequests.current.clear();
        sourceRequestIds.current.clear();
        return;
      }

      const refs: string[] = [];
      const remoteContentParts: CreatorContentPart[] = [];
      if (folderFiles.length > 0) {
        try {
          const files = folderFiles.map((att) => att.file);
          if (stopOnOversizedFiles(files)) {
            return;
          }
          const folderKey = files
            .map((file) => {
              const relative =
                (file as File & { webkitRelativePath?: string })
                  .webkitRelativePath || file.name;
              return `${relative}:${file.size}:${file.lastModified}`;
            })
            .join("|");
          const accepted = await createAssetImport(
            project.projectId,
            files,
            "NONE",
            requestIdFor(`folder:${folderKey}`),
          );
          for (;;) {
            const view = await getAssetImport(
              project.projectId,
              accepted.importId,
            );
            if (terminal.has(view.status)) {
              if (view.status !== "SUCCEEDED")
                throw new Error(
                  `文件夹导入失败（${creatorStatusLabel(view.status)}）`,
                );
              refs.push(
                ...view.items.map(
                  (item) => `asset-version:${item.assetVersionId}`,
                ),
              );
              if (view.failures.length > 0) {
                message.warning(
                  `文件夹导入完成，跳过 ${view.failures.length} 个文件`,
                );
              }
              break;
            }
            await wait(800);
          }
        } catch (error) {
          message.warning(`文件夹导入失败：${(error as Error).message}`);
        }
      }

      for (const att of looseFiles) {
        try {
          const accepted = await ingestAssetFile(
            project.projectId,
            att.file,
            "NONE",
            requestIdFor(
              `file:${att.file.name}:${att.file.size}:${att.file.lastModified}`,
            ),
          );
          const taskRefs = accepted.assetVersionId
            ? [`asset-version:${accepted.assetVersionId}`]
            : await waitForTask(project.projectId, accepted.taskId);
          refs.push(...taskRefs);
        } catch (error) {
          message.warning(
            `附件「${att.file.name}」入库失败：${(error as Error).message}`,
          );
        }
      }

      for (const att of urlAttachments) {
        // The Agent can consume the public URL immediately. Local caching is a
        // parallel Runtime task whose progress is rendered in the Project.
        remoteContentParts.push(remoteUrlContentPart(att.url));
        try {
          const accepted = await ingestAssetValue(
            project.projectId,
            {
              kind: "url",
              name: att.url,
              value: att.url,
              postIngestAction: "NONE",
            },
            requestIdFor(`url:${att.url}`),
          );
          const taskRefs = accepted.assetVersionId
            ? [`asset-version:${accepted.assetVersionId}`]
            : [];
          refs.push(...taskRefs);
        } catch (error) {
          message.warning(
            `附件「${att.url}」入库失败：${(error as Error).message}`,
          );
        }
      }

      const uniqueRefs = [...new Set(refs)].filter((ref) =>
        ref.startsWith("asset-version:"),
      );
      const messageSignature = JSON.stringify({
        projectId: project.projectId,
        conversationId: project.conversationId,
        goal: projectDescription.trim(),
        assetVersionRefs: uniqueRefs,
        remoteUrls: urlAttachments.map((item) => item.url),
      });
      const clientMessageId =
        initialMessageRequests.current.get(messageSignature) ??
        newClientId("initial-message");
      initialMessageRequests.current.set(messageSignature, clientMessageId);
      await sendCreatorMessage(project.projectId, {
        clientMessageId,
        creatorSessionId: project.creatorSessionId,
        conversationId: project.conversationId,
        content: [
          { type: "text", text: projectDescription.trim() },
          ...remoteContentParts,
        ],
        assetVersionRefs: uniqueRefs,
        context: { panel: "composer" },
      });
      // Keep the Composer context alive until the durable first message has
      // been accepted.  Navigating before a slow remote ingest completes can
      // tear down this async continuation and leave a valid Project with no
      // Goal, no message, and an AgentDock permanently showing IDLE.
      router.push(`/project/${project.projectId}/plan`);
      onLaunched?.();
      initialMessageRequests.current.delete(messageSignature);
      projectRequest.current = { signature: "", id: "" };
      initialMessageRequests.current.clear();
      sourceRequestIds.current.clear();
    } catch (error) {
      message.error((error as Error).message || "启动失败");
    } finally {
      setLaunching(false);
    }
  };

  return {
    projectName,
    setProjectName,
    projectDescription,
    setProjectDescription,
    scenario,
    handleScenarioChange,
    contentType,
    setContentType,
    resolution,
    setResolution,
    aspectRatio,
    setAspectRatio,
    attachments,
    addFiles,
    addUrl,
    removeAttachment,
    urlDraft,
    setUrlDraft,
    launching,
    dragOver,
    setDragOver,
    fileInputRef,
    folderInputRef,
    modelConfig,
    modelConfigModalOpen,
    setModelConfigModalOpen,
    refreshModelConfig,
    missingRequiredModels,
    hasMissingModels,
    isVideoEdit,
    canLaunch,
    launchHint,
    handleLaunch,
  };
}
