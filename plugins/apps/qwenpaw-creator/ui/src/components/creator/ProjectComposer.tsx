import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Input, Modal, Select, Tooltip, message } from "antd";
import {
  EyeOutlined,
  PictureOutlined,
  VideoCameraOutlined,
} from "@ant-design/icons";
import {
  FileText,
  Film,
  FolderOpen,
  Link2,
  Paperclip,
  Rocket,
  X,
} from "lucide-react";
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
import ModelConfigModal from "./ModelConfigModal";

const { TextArea } = Input;

type AttachmentDraft =
  | {
      kind: "file";
      id: string;
      file: File;
      source: "file" | "folder";
      relativePath?: string;
    }
  | { kind: "url"; id: string; url: string };

const MODES = [
  { key: "agent", label: "Agent", enabled: true },
  { key: "loop", label: "Loop", enabled: false },
] as const;

const AUTO_PROJECT_NAME_LENGTH = 20;

export const SCENARIO_OPTIONS: { key: CreatorScenario; label: string }[] = [
  { key: "short_drama", label: "短剧" },
  { key: "video_edit", label: "剪辑" },
  { key: "general", label: "通用" },
];

const SCENARIO_TERMS: Record<CreatorScenario, { description: string }> = {
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

function chipLabel(att: AttachmentDraft): { tag: string; name: string } {
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

interface ProjectComposerProps {
  open: boolean;
  onClose: () => void;
}

export function ProjectComposer({ open, onClose }: ProjectComposerProps) {
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
        onClose();
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
      onClose();
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

  return (
    <Modal
      open={open}
      onCancel={launching ? undefined : onClose}
      footer={null}
      width={720}
      centered
      closable={false}
      destroyOnHidden
      title={null}
    >
      <div className="pt-2">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-semibold text-[var(--color-text-primary)]">
              <Film className="h-5 w-5 text-[var(--color-accent)]" />
              把目标、素材和限制交给 Agent
            </h2>
            <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
              资料输入是一次性的启动动作。进入项目后，它们会变成可管理、可引用、可追踪的项目资产。
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            <div className="flex items-center gap-1 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-secondary)] p-1">
              {MODES.map((mode) => (
                <Tooltip
                  key={mode.key}
                  title={mode.enabled ? undefined : "即将推出"}
                >
                  <button
                    type="button"
                    disabled={!mode.enabled}
                    aria-pressed={mode.key === "agent"}
                    className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${
                      mode.enabled
                        ? "bg-[var(--color-bg-primary)] text-[var(--color-text-primary)] shadow-sm"
                        : "cursor-not-allowed text-[var(--color-text-tertiary)]"
                    }`}
                  >
                    {mode.label}
                  </button>
                </Tooltip>
              ))}
            </div>
            {!launching && (
              <button
                type="button"
                onClick={onClose}
                className="flex h-7 w-7 items-center justify-center rounded-lg text-[var(--color-text-tertiary)] transition-colors hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)]"
                aria-label="关闭"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>

        {/* Benchmark scenario picker (5.5): drives the structure template, default
            style and the UI terminology throughout. */}
        <div className="mt-4 flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] font-medium text-[var(--color-text-tertiary)]">
            视频场景
          </span>
          {SCENARIO_OPTIONS.map((option) => (
            <button
              key={option.key}
              type="button"
              onClick={() => handleScenarioChange(option.key)}
              className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold transition-colors ${
                scenario === option.key
                  ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                  : "border-[var(--color-border)] bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] hover:border-[var(--color-accent)]"
              }`}
            >
              {option.label}
            </button>
          ))}
          {!isVideoEdit && (
            <div className="ml-auto flex items-center gap-2">
              <Select
                aria-label="分辨率"
                size="small"
                value={resolution}
                onChange={setResolution}
                options={[
                  { value: "720P", label: "720P" },
                  { value: "1080P", label: "1080P" },
                ]}
                popupMatchSelectWidth={false}
                className="!relative !h-7 !w-auto min-w-[76px] !rounded-full !border-[var(--color-border)] !bg-[var(--color-bg-secondary)]"
                classNames={{
                  content:
                    "!mr-0 !w-full !-translate-x-0.5 !justify-center !text-center !text-[11px] !font-semibold !text-[var(--color-text-secondary)]",
                  suffix:
                    "!absolute !right-2 !text-[10px] !text-[var(--color-text-tertiary)]",
                  popup: {
                    listItem:
                      "!text-[11px] !font-semibold !text-[var(--color-text-secondary)]",
                  },
                }}
              />
              <Select
                aria-label="宽高比"
                size="small"
                value={aspectRatio}
                onChange={setAspectRatio}
                options={[
                  { value: "16:9", label: "16:9" },
                  { value: "9:16", label: "9:16" },
                  { value: "1:1", label: "1:1" },
                  { value: "4:3", label: "4:3" },
                  { value: "3:4", label: "3:4" },
                ]}
                popupMatchSelectWidth={false}
                className="!relative !h-7 !w-auto min-w-[76px] !rounded-full !border-[var(--color-border)] !bg-[var(--color-bg-secondary)]"
                classNames={{
                  content:
                    "!mr-0 !w-full !-translate-x-0.5 !justify-center !text-center !text-[11px] !font-semibold !text-[var(--color-text-secondary)]",
                  suffix:
                    "!absolute !right-2 !text-[10px] !text-[var(--color-text-tertiary)]",
                  popup: {
                    listItem:
                      "!text-[11px] !font-semibold !text-[var(--color-text-secondary)]",
                  },
                }}
              />
            </div>
          )}
        </div>

        <div
          className={`mt-3 rounded-xl border-2 transition-colors ${
            dragOver
              ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)]"
              : "border-[var(--color-border)]"
          }`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            if (e.dataTransfer.files.length > 0)
              addFiles(e.dataTransfer.files, "file");
          }}
        >
          <Input
            value={projectName}
            onChange={(e) => setProjectName(e.target.value)}
            placeholder={`项目名称（选填，留空则取目标描述前 ${AUTO_PROJECT_NAME_LENGTH} 字）`}
            className="!rounded-none !border-x-0 !border-t-0 !bg-transparent !text-sm !font-semibold !shadow-none focus:!shadow-none"
          />
          <TextArea
            value={projectDescription}
            onChange={(e) => setProjectDescription(e.target.value)}
            autoSize={{ minRows: 5, maxRows: 12 }}
            placeholder={"目标描述：" + SCENARIO_TERMS[scenario].description}
            className="!border-none !bg-transparent !p-4 !text-sm !shadow-none focus:!shadow-none"
          />

          {attachments.length > 0 && (
            <div className="flex flex-wrap gap-1.5 px-4 pb-2">
              {attachments.map((att) => {
                const { tag, name } = chipLabel(att);
                return (
                  <span
                    key={att.id}
                    className="inline-flex max-w-[220px] items-center gap-1.5 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-secondary)] py-1 pl-2 pr-1 text-[11px] text-[var(--color-text-secondary)]"
                  >
                    <b className="shrink-0 text-[10px] text-[var(--color-accent)]">
                      {tag}
                    </b>
                    <span className="min-w-0 truncate">{name}</span>
                    <button
                      type="button"
                      onClick={() => removeAttachment(att.id)}
                      className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full hover:bg-[var(--color-border)]"
                      aria-label="移除附件"
                    >
                      <X className="h-2.5 w-2.5" />
                    </button>
                  </span>
                );
              })}
            </div>
          )}

          {hasMissingModels && (
            <button
              type="button"
              onClick={() => {
                setModelConfigModalOpen(true);
              }}
              className="flex flex-wrap items-center gap-2 border-t border-[var(--color-warning)]/30 bg-[var(--color-warning-soft)]/40 px-3 py-2 text-left transition-colors hover:bg-[var(--color-warning-soft)]/70"
            >
              <span className="text-[11px] font-medium text-[var(--color-warning)]">
                必选模型未配置：
              </span>
              {missingRequiredModels!.map((type) => {
                const meta = {
                  vlm: {
                    label: "VLM",
                    icon: <EyeOutlined style={{ fontSize: 10 }} />,
                  },
                  image: {
                    label: "Image",
                    icon: <PictureOutlined style={{ fontSize: 10 }} />,
                  },
                  video: {
                    label: "Video",
                    icon: <VideoCameraOutlined style={{ fontSize: 10 }} />,
                  },
                }[type] ?? { label: type, icon: null };
                return (
                  <span
                    key={type}
                    className="inline-flex items-center gap-1 rounded-full border border-[var(--color-warning)]/40 bg-white/60 px-1.5 py-0.5 text-[10px] font-semibold text-[var(--color-warning)]"
                  >
                    {meta.icon}
                    {meta.label}
                  </span>
                );
              })}
              <span className="ml-auto text-[11px] font-semibold text-[var(--color-accent)]">
                点击配置 →
              </span>
            </button>
          )}
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[var(--color-border)] px-3 py-2">
            <div className="flex min-w-0 flex-1 items-center gap-2">
              <Button
                size="small"
                type="text"
                icon={<Paperclip className="h-3.5 w-3.5" />}
                onClick={() => fileInputRef.current?.click()}
                className="!text-xs !text-[var(--color-text-secondary)]"
              >
                添加文件
              </Button>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                hidden
                onChange={(e) => {
                  if (e.target.files?.length) addFiles(e.target.files);
                  e.target.value = "";
                }}
              />
              <Button
                size="small"
                type="text"
                icon={<FolderOpen className="h-3.5 w-3.5" />}
                onClick={() => folderInputRef.current?.click()}
                className="!text-xs !text-[var(--color-text-secondary)]"
              >
                选择文件夹
              </Button>
              <input
                ref={folderInputRef}
                type="file"
                multiple
                hidden
                {...{ webkitdirectory: "", directory: "" }}
                onChange={(e) => {
                  if (e.target.files?.length)
                    addFiles(e.target.files, "folder");
                  e.target.value = "";
                }}
              />
              <div className="flex min-w-0 flex-1 items-center gap-1">
                <Link2 className="h-3.5 w-3.5 shrink-0 text-[var(--color-text-tertiary)]" />
                <Input
                  size="small"
                  value={urlDraft}
                  onChange={(e) => setUrlDraft(e.target.value)}
                  onPressEnter={addUrl}
                  placeholder="粘贴 URL 后回车"
                  className="!max-w-[240px] !border-none !bg-transparent !text-xs !shadow-none"
                />
              </div>
            </div>
            <Tooltip title={canLaunch ? undefined : launchHint()}>
              <Button
                type="primary"
                icon={<Rocket className="h-3.5 w-3.5" />}
                disabled={!canLaunch}
                loading={launching}
                onClick={handleLaunch}
                className="!flex !items-center !gap-1.5 !font-semibold"
              >
                启动 Agent
              </Button>
            </Tooltip>
          </div>
          {isVideoEdit && (
            <div className="flex flex-wrap items-center gap-1.5 border-t border-[var(--color-border)] px-3 py-2">
              <span className="text-[11px] font-medium text-[var(--color-text-tertiary)]">
                内容类型<sup className="text-[var(--color-accent)]">*</sup>
              </span>
              {CONTENT_TYPE_OPTIONS.map((option) => (
                <button
                  key={option.key}
                  type="button"
                  onClick={() => setContentType(option.key)}
                  className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold transition-colors ${
                    contentType === option.key
                      ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                      : "border-[var(--color-border)] bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] hover:border-[var(--color-accent)]"
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
          )}
        </div>

        <p className="mt-3 flex items-center gap-1.5 text-[11px] text-[var(--color-text-tertiary)]">
          <FileText className="h-3 w-3" />
          附件将进入资产库「用户上传」分类。
        </p>
      </div>
      <ModelConfigModal
        open={modelConfigModalOpen}
        onClose={() => {
          setModelConfigModalOpen(false);
          refreshModelConfig();
        }}
      />
    </Modal>
  );
}
