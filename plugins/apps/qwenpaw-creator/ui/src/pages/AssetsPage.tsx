import { useEffect, useMemo, useRef, useState } from "react";
import { Button, Input, message, Modal, Tabs } from "antd";
import {
  Box,
  Clapperboard,
  Download,
  FileText,
  Film,
  Image as ImageIcon,
  Link2,
  Music2,
  Paperclip,
  Search,
  Sparkles,
  Upload,
  Wand2,
} from "lucide-react";
import {
  getArtifactVersionMediaUrl,
  getAssetVersionMediaUrl,
  ingestAssetFile,
  ingestAssetValue,
} from "@/api/creator";
import type {
  ArtifactVersionDocument,
  ProjectDocument,
  SourceAssetVersionDocument,
  VisualEntityDocument,
} from "@/contracts/creator";
import { navigate, useParams, useSearchParams } from "@/routing/navigation";
import {
  useReviewFieldFocus,
  useReviewMediaFocus,
} from "@/routing/reviewFocus";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";
import { useCreatorInteractionStore } from "@/store/creatorInteractionStore";
import { useCreatorTaskViewStore } from "@/store/creatorTaskViewStore";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import AssetMediaPreview from "@/components/assets/AssetMediaPreview";
import PageLoadError from "@/components/PageLoadError";
import PageSkeleton from "@/components/PageSkeleton";
import { selectPrimaryTimeline } from "@/selectors/timelineElementSelectors";

type FilterKey =
  | "all"
  | "source"
  | "artifact"
  | "visual"
  | "image"
  | "video"
  | "audio";
type AssetItem = {
  id: string;
  ref: string;
  kind: "source" | "artifact" | "visual";
  name: string;
  description: string;
  mediaKind: string;
  mediaType: string;
  previewUrl?: string;
  createdAt?: string;
  stale?: boolean;
  durationSeconds?: number | null;
  checksum?: string;
  ownerRef?: string;
  provenanceRefs: string[];
  metadata: Record<string, unknown>;
  raw:
    | SourceAssetVersionDocument
    | ArtifactVersionDocument
    | VisualEntityDocument;
};

const FILTERS: Array<{ key: FilterKey; label: string }> = [
  { key: "all", label: "全部" },
  { key: "source", label: "来源素材" },
  { key: "artifact", label: "生成产物" },
  { key: "visual", label: "视觉设定" },
  { key: "image", label: "图片" },
  { key: "video", label: "视频" },
  { key: "audio", label: "音频" },
];

function fileMedia(
  project: ProjectDocument,
  fileId: string | null,
): { kind: string; type: string } {
  const type = fileId
    ? project.assets.files_by_id[fileId]?.media_type || ""
    : "";
  const kind = type.startsWith("image/")
    ? "image"
    : type.startsWith("video/")
    ? "video"
    : type.startsWith("audio/")
    ? "audio"
    : type.startsWith("text/")
    ? "text"
    : "other";
  return { kind, type };
}

const MIME_EXTENSION_MAP: Record<string, string> = {
  "video/mp4": ".mp4",
  "video/quicktime": ".mov",
  "video/webm": ".webm",
  "video/x-matroska": ".mkv",
  "image/jpeg": ".jpg",
  "image/png": ".png",
  "image/webp": ".webp",
  "audio/mpeg": ".mp3",
  "audio/wav": ".wav",
  "audio/ogg": ".ogg",
};

function downloadName(name: string, mediaType: string): string {
  const base = name.trim() || "download";
  if (/\.[a-zA-Z0-9]{1,10}$/.test(base)) return base;
  const ext =
    MIME_EXTENSION_MAP[mediaType.split(";")[0].trim().toLowerCase()] ?? "";
  return ext ? `${base}${ext}` : base;
}

function artifactMedia(
  project: ProjectDocument,
  artifact: ArtifactVersionDocument,
): { kind: string; type: string } {
  const file = fileMedia(project, artifact.file_id);
  if (file.kind !== "other") return file;
  const hint = `${artifact.kind} ${artifact.name}`.toLocaleLowerCase();
  if (hint.includes("video") || hint.includes("render"))
    return { kind: "video", type: file.type };
  if (hint.includes("audio")) return { kind: "audio", type: file.type };
  if (hint.includes("image") || hint.includes("storyboard"))
    return { kind: "image", type: file.type };
  return file;
}

// Keep only one card per underlying content (same checksum); semantic cards
// listed earlier (e.g. visual entities) win. No ownership naming convention is
// relied upon.
function dedupeByChecksum(items: AssetItem[]): AssetItem[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    if (!item.checksum) return true;
    if (seen.has(item.checksum)) return false;
    seen.add(item.checksum);
    return true;
  });
}

function assetItems(project: ProjectDocument): AssetItem[] {
  const sources = Object.values(project.assets.source_versions_by_id).map(
    (source): AssetItem => ({
      id: source.version_id,
      ref: `asset-version:${source.version_id}`,
      kind: "source",
      name: source.name || source.version_id,
      description: String(
        source.metadata.description ||
          source.metadata.user_notes ||
          "用户导入的来源素材",
      ),
      mediaKind: source.media_kind,
      mediaType: source.media_type,
      previewUrl: ["image", "video", "audio"].includes(source.media_kind)
        ? getAssetVersionMediaUrl(source.version_id)
        : undefined,
      createdAt: source.created_at,
      durationSeconds: source.duration_seconds,
      checksum: source.checksum,
      provenanceRefs: source.provenance_refs,
      metadata: source.metadata,
      raw: source,
    }),
  );
  const artifacts = Object.values(project.assets.artifact_versions_by_id).map(
    (artifact): AssetItem => {
      const media = artifactMedia(project, artifact);
      return {
        id: artifact.version_id,
        ref: `artifact-version:${artifact.version_id}`,
        kind: "artifact",
        name: artifact.name || artifact.version_id,
        description: artifact.stale
          ? artifact.stale_reason || "该产物依赖的 Project 内容已经变化"
          : `${artifact.kind} · generation ${artifact.based_on_generation}`,
        mediaKind: media.kind,
        mediaType: media.type,
        previewUrl: ["image", "video", "audio"].includes(media.kind)
          ? getArtifactVersionMediaUrl(artifact.version_id)
          : undefined,
        createdAt: artifact.created_at,
        stale: artifact.stale,
        durationSeconds: artifact.duration_seconds,
        checksum: artifact.checksum,
        ownerRef: artifact.owner_ref,
        provenanceRefs: artifact.provenance_refs,
        metadata: artifact.metadata,
        raw: artifact,
      };
    },
  );
  const visuals = project.visual.entities.order
    .map((entityId) => project.visual.entities.items[entityId])
    .filter(Boolean)
    .map((entity): AssetItem => {
      const artifact = entity.selected_artifact_version_id
        ? project.assets.artifact_versions_by_id[
            entity.selected_artifact_version_id
          ]
        : undefined;
      const media = artifact
        ? artifactMedia(project, artifact)
        : { kind: "image", type: "" };
      return {
        id: entity.entity_id,
        ref: `visual-entity:${entity.entity_id}`,
        kind: "visual",
        name: entity.name,
        description:
          entity.description || entity.continuity || `${entity.kind} 视觉设定`,
        mediaKind: media.kind,
        mediaType: media.type,
        previewUrl: artifact
          ? getArtifactVersionMediaUrl(artifact.version_id)
          : undefined,
        stale: artifact?.stale,
        checksum: artifact?.checksum,
        ownerRef: artifact?.owner_ref,
        provenanceRefs: [],
        metadata: {
          kind: entity.kind,
          continuity: entity.continuity,
          variants: entity.variants.order.length,
          selected_artifact_version_id: entity.selected_artifact_version_id,
        },
        raw: entity,
      };
    });
  return dedupeByChecksum([...visuals, ...sources, ...artifacts]).sort(
    (left, right) =>
      (right.createdAt || "").localeCompare(left.createdAt || "") ||
      left.name.localeCompare(right.name),
  );
}

function kindLabel(item: AssetItem): string {
  if (item.kind === "source") return "来源";
  if (item.kind === "artifact") return "产物";
  const entity = item.raw as VisualEntityDocument;
  return entity.kind === "character"
    ? "角色"
    : entity.kind === "scene"
    ? "场景"
    : "道具";
}

function mediaIcon(kind: string) {
  if (kind === "video") return Film;
  if (kind === "audio") return Music2;
  if (kind === "image") return ImageIcon;
  if (kind === "text" || kind === "document") return FileText;
  return Box;
}

function displayValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean")
    return String(value);
  if (value === null || value === undefined) return "—";
  return JSON.stringify(value);
}

interface PromptTarget {
  pointer: string;
  value: string;
  label: string;
}

function visualEntityPromptTarget(
  entity: VisualEntityDocument,
  versionId: string | null,
): PromptTarget | null {
  const variantId =
    (versionId &&
      entity.variants.order.find(
        (candidate) =>
          entity.variants.items[
            candidate
          ]?.generated_artifact_version_ids.includes(versionId),
      )) ||
    entity.variants.order[0];
  const variant = variantId ? entity.variants.items[variantId] : null;
  if (!variant) return null;
  return {
    pointer: `/visual/entities/items/${entity.entity_id}/variants/items/${variant.variant_id}/prompt`,
    value: variant.prompt,
    label: "生成 Prompt",
  };
}

function generationPromptTarget(
  project: ProjectDocument,
  selected: AssetItem,
): PromptTarget | null {
  if (selected.kind === "visual") {
    const entity = selected.raw as VisualEntityDocument;
    return visualEntityPromptTarget(
      entity,
      entity.selected_artifact_version_id,
    );
  }
  if (selected.kind !== "artifact") return null;
  const ownerRef = selected.ownerRef ?? "";
  if (ownerRef.startsWith("visual-entity:")) {
    const entity =
      project.visual.entities.items[ownerRef.slice("visual-entity:".length)];
    return entity ? visualEntityPromptTarget(entity, selected.id) : null;
  }
  if (ownerRef.startsWith("element:")) {
    const elementId = ownerRef.slice("element:".length);
    const timeline = selectPrimaryTimeline(project);
    const element = timeline?.elements_by_id[elementId];
    if (!timeline || !element) return null;
    const base = `/timelines/items/${timeline.timeline_id}/elements_by_id/${elementId}/creation`;
    if (element.creation.type === "r2v") {
      const artifact = selected.raw as ArtifactVersionDocument;
      const isVideo =
        selected.mediaKind === "video" || `${artifact.kind}`.includes("video");
      return isVideo
        ? {
            pointer: `${base}/video_prompt`,
            value: element.creation.video_prompt,
            label: "视频生成 Prompt",
          }
        : {
            pointer: `${base}/storyboard_prompt`,
            value: element.creation.storyboard_prompt,
            label: "分镜图生成 Prompt",
          };
    }
    if (element.creation.type === "overlay") {
      return {
        pointer: `${base}/prompt`,
        value: element.creation.prompt,
        label: "生成 Prompt",
      };
    }
  }
  return null;
}

/** Editable generation-prompt block; key is bound to the pointer so drafts reset when the selection changes. */
function GenerationPromptEditor({
  target,
  onSave,
  saving,
}: {
  target: PromptTarget;
  onSave: (target: PromptTarget, next: string) => Promise<void>;
  saving: boolean;
}) {
  const [draft, setDraft] = useState(target.value);
  const dirty = draft !== target.value;
  return (
    <div
      data-creator-path={target.pointer}
      data-creator-field-label={target.label}
      className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] p-3"
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="flex items-center gap-1 text-xs font-semibold text-[var(--color-text-secondary)]">
          <Wand2 className="h-3.5 w-3.5" />
          {target.label}
        </span>
        <div className="flex gap-1.5">
          {dirty && (
            <Button size="small" onClick={() => setDraft(target.value)}>
              还原
            </Button>
          )}
          <Button
            size="small"
            type="primary"
            disabled={!dirty}
            loading={saving}
            onClick={() => void onSave(target, draft)}
          >
            保存
          </Button>
        </div>
      </div>
      <Input.TextArea
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        autoSize={{ minRows: 3, maxRows: 10 }}
        placeholder="该产物的生成 Prompt"
        className="!text-xs"
      />
      <p className="mt-1.5 text-[10px] leading-4 text-[var(--color-text-tertiary)]">
        修改后保存即写入项目；下次生成将使用新 Prompt。
      </p>
    </div>
  );
}

export default function AssetsPage() {
  const { id = "" } = useParams();
  const query = useSearchParams();
  const project = useProjectSnapshotStore((state) =>
    state.projectId === id ? state.project : null,
  );
  const syncStatus = useProjectSnapshotStore((state) => state.syncStatus);
  const syncError = useProjectSnapshotStore((state) => state.syncError);
  const pollOnce = useProjectSnapshotStore((state) => state.pollOnce);
  const patchProject = useProjectSnapshotStore((state) => state.patch);
  const patching = useProjectSnapshotStore((state) => state.patching);
  const refreshTasks = useCreatorTaskViewStore((state) => state.refresh);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [filter, setFilter] = useState<FilterKey>("all");
  const [search, setSearch] = useState("");
  const [uploading, setUploading] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [inputKind, setInputKind] = useState<"url" | "text">("url");
  const [inputName, setInputName] = useState("");
  const [inputValue, setInputValue] = useState("");
  const selectedId = query.get("asset");
  const reviewMode = query.get("review") === "1";
  const reviewField = query.get("field");
  const reviewPulse = query.get("reviewPulse");
  const versionFromUrl = query.get("version");
  useReviewFieldFocus({
    path: `/project/${id}/assets`,
    field: reviewField,
    enabled: reviewMode,
    pulse: reviewPulse,
  });
  // "View generation detail" for portrait-image reviews has no field pointer;
  // flash the detail preview anchored by the version awaiting review.
  useReviewMediaFocus({
    versionId: versionFromUrl,
    enabled: reviewMode && !reviewField,
    pulse: reviewPulse,
  });
  const allItems = useMemo(
    () => (project ? assetItems(project) : []),
    [project],
  );
  const items = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase();
    return allItems.filter((item) => {
      const filterMatch =
        filter === "all" || filter === item.kind || filter === item.mediaKind;
      const searchMatch =
        !needle ||
        `${item.name} ${item.description} ${item.ref}`
          .toLocaleLowerCase()
          .includes(needle);
      return filterMatch && searchMatch;
    });
  }, [allItems, filter, search]);
  const selected = allItems.find((item) => item.id === selectedId) || null;

  useEffect(() => {
    useCreatorInteractionStore.getState().select(selected?.ref || null);
  }, [selected?.ref]);

  const selectItem = (item: AssetItem | null) => {
    navigate(
      item
        ? `/project/${id}/assets?asset=${encodeURIComponent(item.id)}`
        : `/project/${id}/assets`,
    );
  };
  const openAgent = (item: AssetItem) => {
    useCreatorInteractionStore.getState().select(item.ref);
    useAgentDockUiStore.getState().setOpen(true);
    useAgentDockUiStore.getState().setTab("conversation");
    useAgentDockUiStore
      .getState()
      .setDraft(
        `请检查并完善「${item.name}」(${item.ref})，先读取 Project 中的现状和引用关系再行动。`,
      );
  };
  const refreshAfterIngest = async () => {
    await Promise.allSettled([pollOnce(id), refreshTasks(id)]);
  };
  const uploadFile = async (file: File) => {
    setUploading(true);
    try {
      await ingestAssetFile(id, file, "ATTACH_SOURCE");
      message.success("素材已提交，入库完成后会自动出现在这里");
      await refreshAfterIngest();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "上传失败");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };
  const addValue = async () => {
    if (!inputName.trim() || !inputValue.trim()) {
      message.warning("请填写名称和内容");
      return;
    }
    setUploading(true);
    try {
      await ingestAssetValue(id, {
        kind: inputKind,
        name: inputName.trim(),
        value: inputValue.trim(),
        postIngestAction: "ATTACH_SOURCE",
      });
      message.success(
        inputKind === "url" ? "链接已提交入库" : "文本素材已提交入库",
      );
      setAddOpen(false);
      setInputName("");
      setInputValue("");
      await refreshAfterIngest();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "添加失败");
    } finally {
      setUploading(false);
    }
  };

  if (!project) {
    if (syncStatus === "invalid" || syncStatus === "not_found") {
      return (
        <PageLoadError
          message={syncError || "Project 无法读取"}
          retry={() => void pollOnce(id)}
        />
      );
    }
    return <PageSkeleton type="grid" />;
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-[var(--color-bg-layout)]">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-[var(--color-border)] bg-[var(--color-bg-primary)]/70 px-5 py-3 backdrop-blur">
        <div>
          <h2 className="text-base font-semibold text-[var(--color-text-primary)]">
            素材与产物
          </h2>
          <p className="mt-0.5 text-xs text-[var(--color-text-secondary)]">
            当前项目中的来源素材、生成结果与视觉设定；时间线内容会引用这里的具体版本。
          </p>
        </div>
        <div
          data-onboarding-id="assets-upload"
          className="flex items-center gap-2"
        >
          <input
            ref={fileInputRef}
            type="file"
            hidden
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void uploadFile(file);
            }}
          />
          <Button
            size="small"
            icon={<Link2 className="h-3.5 w-3.5" />}
            onClick={() => setAddOpen(true)}
          >
            添加链接或文本
          </Button>
          <Button
            size="small"
            loading={uploading}
            icon={<Upload className="h-3.5 w-3.5" />}
            onClick={() => fileInputRef.current?.click()}
          >
            上传素材
          </Button>
        </div>
      </header>

      <div
        data-onboarding-id="assets-filters"
        className="flex shrink-0 flex-wrap items-center gap-2 border-b border-[var(--color-border)] bg-[var(--color-bg-primary)] px-5 py-2.5"
      >
        <div className="flex flex-wrap gap-1">
          {FILTERS.map((candidate) => (
            <button
              key={candidate.key}
              type="button"
              onClick={() => setFilter(candidate.key)}
              className={`rounded-full px-3 py-1 text-xs transition ${
                filter === candidate.key
                  ? "bg-[var(--color-accent)] text-white"
                  : "border border-[var(--color-border)] bg-white text-[var(--color-text-secondary)] hover:border-[var(--color-accent)]/50"
              }`}
            >
              {candidate.label}
            </button>
          ))}
        </div>
        <div className="ml-auto flex w-56 items-center rounded-lg border border-[var(--color-border)] bg-white px-2.5">
          <Search className="h-3.5 w-3.5 text-[var(--color-text-tertiary)]" />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="搜索名称或 ID"
            className="min-w-0 flex-1 border-0 bg-transparent px-2 py-1.5 text-xs outline-none"
          />
        </div>
        <span className="text-[11px] text-[var(--color-text-tertiary)]">
          {items.length} 项
        </span>
      </div>

      <main className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_340px] gap-4 overflow-hidden p-4">
        <section
          data-onboarding-id="assets-grid"
          className="min-h-0 overflow-y-auto rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-primary)] p-3"
        >
          {items.length > 0 ? (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(190px,1fr))] gap-3">
              {items.map((item) => {
                const Icon = mediaIcon(item.mediaKind);
                return (
                  <button
                    key={`${item.kind}:${item.id}`}
                    type="button"
                    data-creator-module="asset-card"
                    data-creator-module-id={item.id}
                    onClick={() => selectItem(item)}
                    className={`group overflow-hidden rounded-xl border bg-[var(--color-bg-card)] text-left transition ${
                      selected?.id === item.id
                        ? "border-[var(--color-accent)] shadow-[0_0_0_1px_var(--color-accent)]"
                        : "border-[var(--color-border)] hover:border-[var(--color-border-strong)] hover:shadow-sm"
                    }`}
                  >
                    <div className="relative flex h-32 items-center justify-center overflow-hidden bg-[var(--color-bg-secondary)]">
                      <AssetMediaPreview
                        name={item.name}
                        mediaType={item.mediaKind}
                        previewUrl={item.previewUrl}
                        state={item.previewUrl ? "ready" : "unavailable"}
                        mediaClassName="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.02]"
                        placeholderClassName="flex flex-col items-center gap-1.5 text-[11px] text-[var(--color-text-tertiary)]"
                      />
                      {!item.previewUrl && (
                        <Icon className="pointer-events-none absolute h-6 w-6 -translate-y-3 text-[var(--color-text-tertiary)]" />
                      )}
                      <span className="absolute left-2 top-2 rounded bg-black/65 px-1.5 py-0.5 text-[10px] font-bold text-white">
                        {kindLabel(item)}
                      </span>
                      {item.stale && (
                        <span className="absolute right-2 top-2 rounded bg-amber-500 px-1.5 py-0.5 text-[10px] font-bold text-white">
                          过期
                        </span>
                      )}
                    </div>
                    <div className="p-3">
                      <h3 className="truncate text-sm font-semibold text-[var(--color-text-primary)]">
                        {item.name}
                      </h3>
                      <p className="mt-1 line-clamp-2 min-h-8 text-[11px] leading-4 text-[var(--color-text-secondary)]">
                        {item.description}
                      </p>
                      <p className="mt-2 truncate font-mono text-[10px] text-[var(--color-text-tertiary)]">
                        {item.id}
                      </p>
                    </div>
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="flex h-full min-h-64 flex-col items-center justify-center text-center text-[var(--color-text-tertiary)]">
              <Paperclip className="mb-3 h-8 w-8 opacity-50" />
              <p className="text-sm font-medium text-[var(--color-text-secondary)]">
                当前筛选下没有素材
              </p>
              <p className="mt-1 text-xs">
                上传来源素材，或让 Agent 根据时间轴生成画面与成片。
              </p>
            </div>
          )}
        </section>

        <aside
          data-onboarding-id="assets-detail"
          className="min-h-0 overflow-y-auto rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-primary)]"
        >
          {selected ? (
            <div>
              <div
                data-review-media-anchor={versionFromUrl ?? undefined}
                className="flex aspect-video items-center justify-center overflow-hidden bg-black"
              >
                {selected.mediaKind === "audio" && selected.previewUrl ? (
                  <audio
                    src={selected.previewUrl}
                    controls
                    className="w-[86%]"
                  />
                ) : (
                  <AssetMediaPreview
                    name={selected.name}
                    mediaType={selected.mediaKind}
                    previewUrl={selected.previewUrl}
                    state={selected.previewUrl ? "ready" : "unavailable"}
                    controls
                    mediaClassName="h-full w-full object-contain"
                    placeholderClassName="text-xs text-white/55"
                  />
                )}
              </div>
              <div className="space-y-4 p-4">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-[var(--color-accent-soft)] px-2 py-0.5 text-[10px] font-semibold text-[var(--color-accent)]">
                      {kindLabel(selected)}
                    </span>
                    {selected.stale && (
                      <span className="text-[10px] font-semibold text-amber-600">
                        已过期
                      </span>
                    )}
                  </div>
                  <h3 className="mt-2 text-base font-semibold text-[var(--color-text-primary)]">
                    {selected.name}
                  </h3>
                  <p className="mt-1 whitespace-pre-wrap text-xs leading-5 text-[var(--color-text-secondary)]">
                    {selected.description}
                  </p>
                </div>
                <dl className="space-y-2 text-xs">
                  {[
                    ["引用", selected.ref],
                    ["媒体", selected.mediaType || selected.mediaKind],
                    [
                      "时长",
                      selected.durationSeconds == null
                        ? "—"
                        : `${selected.durationSeconds.toFixed(2)}s`,
                    ],
                    ["Owner", selected.ownerRef || "—"],
                    [
                      "创建时间",
                      selected.createdAt
                        ? new Date(selected.createdAt).toLocaleString("zh-CN")
                        : "—",
                    ],
                    ["Checksum", selected.checksum || "—"],
                  ].map(([label, value]) => (
                    <div
                      key={label}
                      className="grid grid-cols-[64px_minmax(0,1fr)] gap-2"
                    >
                      <dt className="text-[var(--color-text-tertiary)]">
                        {label}
                      </dt>
                      <dd className="break-all font-mono text-[11px] text-[var(--color-text-secondary)]">
                        {value}
                      </dd>
                    </div>
                  ))}
                </dl>
                {Object.keys(selected.metadata).length > 0 && (
                  <details className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] p-3 text-xs">
                    <summary className="cursor-pointer font-semibold text-[var(--color-text-secondary)]">
                      元数据
                    </summary>
                    <dl className="mt-2 space-y-1.5">
                      {Object.entries(selected.metadata).map(([key, value]) => (
                        <div
                          key={key}
                          className="grid grid-cols-[100px_minmax(0,1fr)] gap-2"
                        >
                          <dt className="truncate font-mono text-[10px] text-[var(--color-text-tertiary)]">
                            {key}
                          </dt>
                          <dd className="break-all text-[11px] text-[var(--color-text-secondary)]">
                            {displayValue(value)}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  </details>
                )}
                {(() => {
                  if (!project) return null;
                  const promptTarget = generationPromptTarget(
                    project,
                    selected,
                  );
                  if (!promptTarget) return null;
                  return (
                    <GenerationPromptEditor
                      key={promptTarget.pointer}
                      target={promptTarget}
                      saving={patching}
                      onSave={async (target, next) => {
                        try {
                          await patchProject(id, [
                            {
                              op: "replace",
                              path: target.pointer,
                              before: target.value,
                              value: next,
                            },
                          ]);
                          message.success("生成 Prompt 已保存");
                        } catch (error) {
                          message.error(
                            `保存失败：${(error as Error).message}`,
                          );
                        }
                      }}
                    />
                  );
                })()}
                {selected.mediaKind === "video" &&
                  selected.ownerRef?.startsWith("element:") && (
                    <Button
                      block
                      icon={<Clapperboard className="h-3.5 w-3.5" />}
                      onClick={() =>
                        navigate(
                          `/project/${id}/plan/element/${encodeURIComponent(
                            selected.ownerRef!.slice("element:".length),
                          )}`,
                        )
                      }
                    >
                      进入该视频的 R2V 工作台
                    </Button>
                  )}
                <div className="flex gap-2">
                  {selected.previewUrl && (
                    <Button
                      icon={<Download className="h-3.5 w-3.5" />}
                      onClick={() => {
                        const filename = downloadName(
                          selected.name,
                          selected.mediaType,
                        );
                        fetch(selected.previewUrl!)
                          .then((res) => {
                            if (!res.ok)
                              throw new Error(`下载失败（${res.status}）`);
                            return res.blob();
                          })
                          .then((blob) => {
                            const url = URL.createObjectURL(blob);
                            const a = document.createElement("a");
                            a.href = url;
                            a.download = filename;
                            a.click();
                            URL.revokeObjectURL(url);
                          })
                          .catch((error) => {
                            message.error(
                              error instanceof Error
                                ? error.message
                                : "下载失败",
                            );
                          });
                      }}
                    >
                      下载
                    </Button>
                  )}
                  <Button
                    className="flex-1"
                    icon={<Sparkles className="h-3.5 w-3.5" />}
                    onClick={() => openAgent(selected)}
                  >
                    交给 Agent
                  </Button>
                  <Button onClick={() => selectItem(null)}>关闭</Button>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex h-full min-h-64 flex-col items-center justify-center px-8 text-center">
              <Box className="mb-3 h-8 w-8 text-[var(--color-text-tertiary)] opacity-50" />
              <p className="text-sm font-medium text-[var(--color-text-secondary)]">
                选择一项查看详情
              </p>
              <p className="mt-1 text-xs leading-5 text-[var(--color-text-tertiary)]">
                这里显示 Project 内实际保存的版本、引用与产物状态。
              </p>
            </div>
          )}
        </aside>
      </main>

      <Modal
        title="添加来源素材"
        open={addOpen}
        confirmLoading={uploading}
        okText="提交入库"
        cancelText="取消"
        onOk={() => void addValue()}
        onCancel={() => setAddOpen(false)}
      >
        <Tabs
          activeKey={inputKind}
          onChange={(key) => setInputKind(key as "url" | "text")}
          items={[
            { key: "url", label: "链接" },
            { key: "text", label: "文本" },
          ]}
        />
        <div className="space-y-3">
          <Input
            value={inputName}
            onChange={(event) => setInputName(event.target.value)}
            placeholder="素材名称"
          />
          <Input.TextArea
            value={inputValue}
            onChange={(event) => setInputValue(event.target.value)}
            autoSize={{ minRows: inputKind === "url" ? 2 : 6, maxRows: 10 }}
            placeholder={
              inputKind === "url" ? "https://…" : "粘贴脚本、要求或其他文本素材"
            }
          />
        </div>
      </Modal>
    </div>
  );
}
