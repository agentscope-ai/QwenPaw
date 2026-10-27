import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import i18n from "@/i18n";
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
  getTask,
  importTimelineScript,
  ingestAssetFile,
  ingestAssetValue,
  newClientId,
  sendCreatorMessage,
} from "@/api/creator";
import {
  detectScriptUpload,
  type ScriptUploadKind,
} from "@/lib/scriptUploadDetect";
import { useModelConfigStore } from "@/store/modelConfigStore";
import { useLaunchUploadStore } from "@/store/launchUploadStore";
import { taskErrorMessage } from "@/lib/taskPresentation";
import { creatorStatusLabel } from "@/lib/creatorPresentation";
import { useRouter } from "@/routing/navigation";

// A freshly created Project always ships this default Timeline (see backend
// models.Project.new), so a script attachment can land on it right after
// createProject returns and before the first Agent message.
const DEFAULT_TIMELINE_ID = "timeline:main";

export type AttachmentDraft =
  | {
      kind: "file";
      id: string;
      file: File;
      source: "file" | "folder";
      relativePath?: string;
      // Detection result + the user's current choice. The default is 素材
      // (asScript=false); at most one attachment carries asScript=true at
      // creation (single default Timeline).
      scriptKind: ScriptUploadKind;
      asScript: boolean;
    }
  | { kind: "url"; id: string; url: string };

export const MODES = [
  { key: "agent", label: "Agent", enabled: true },
  { key: "loop", label: "Loop", enabled: false },
] as const;

export const AUTO_PROJECT_NAME_LENGTH = 20;

export const SCENARIO_OPTIONS: { key: CreatorScenario; labelKey: string }[] = [
  { key: "short_drama", labelKey: "scenario.shortDrama" },
  { key: "video_edit", labelKey: "scenario.editing" },
  { key: "general", labelKey: "scenario.general" },
];

export const SCENARIO_TERMS: Record<
  CreatorScenario,
  { descriptionKey: string }
> = {
  general: {
    descriptionKey: "scenario.exampleGeneral",
  },
  short_drama: {
    descriptionKey: "scenario.exampleShortDrama",
  },
  video_edit: {
    descriptionKey: "scenario.exampleEditing",
  },
};

export const CONTENT_TYPE_OPTIONS: { key: string; labelKey: string }[] = [
  { key: "pet_video", labelKey: "scenario.pet" },
  { key: "gaming", labelKey: "scenario.game" },
  { key: "sports", labelKey: "scenario.sports" },
  { key: "travel_vlog", labelKey: "scenario.travel" },
  { key: "interview", labelKey: "scenario.interview" },
  { key: "general", labelKey: "scenario.generalType" },
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
            i18n.t("lib.sourceProcessingFailed", {
              status: creatorStatusLabel(task.status),
            }),
          ),
        );
      }
      return task.resultRefs;
    }
    await wait(800);
  }
}

// Batch launches upload every attachment before the first message can be
// sent; doing that one file at a time kept users staring at the composer
// for minutes (field run 2026-08-10: 18 clips ≈ uploads × RTT serialized).
// A small worker pool preserves per-file error isolation while letting
// uploads and ingest polling overlap.
const INGEST_CONCURRENCY = 4;

async function mapWithConcurrency<T>(
  items: readonly T[],
  limit: number,
  run: (item: T) => Promise<void>,
): Promise<void> {
  let cursor = 0;
  const workers = Array.from(
    { length: Math.min(limit, items.length) },
    async () => {
      for (;;) {
        const index = cursor;
        cursor += 1;
        if (index >= items.length) return;
        await run(items[index]);
      }
    },
  );
  await Promise.all(workers);
}

interface LaunchContinuation {
  project: Awaited<ReturnType<typeof createProject>>;
  goal: string;
  scriptAttachment: Extract<AttachmentDraft, { kind: "file" }> | null;
  scriptIdempotencyKey: string;
  folderFiles: Extract<AttachmentDraft, { kind: "file" }>[];
  looseFiles: Extract<AttachmentDraft, { kind: "file" }>[];
  urlAttachments: Extract<AttachmentDraft, { kind: "url" }>[];
}

/**
 * Ingest launch attachments and send the durable first message after the
 * composer already navigated away. Module-level on purpose: it must not
 * depend on any component lifecycle, and it reports every step to the
 * launch-upload store so the project workspace can render live progress.
 */
async function continueLaunchInBackground({
  project,
  goal,
  scriptAttachment,
  scriptIdempotencyKey,
  folderFiles,
  looseFiles,
  urlAttachments,
}: LaunchContinuation): Promise<void> {
  const projectId = project.projectId;
  const progress = useLaunchUploadStore.getState();
  progress.begin(
    projectId,
    folderFiles.length +
      looseFiles.length +
      urlAttachments.length +
      (scriptAttachment ? 1 : 0),
  );
  const refs: string[] = [];
  const remoteContentParts: CreatorContentPart[] = [];
  try {
    // Land a user-provided script directly on the default Timeline before the
    // first Agent message: it becomes the selected timeline_script version
    // without creating a ProjectSource, so it never enters material
    // understanding and the Agent reuses it instead of re-drafting.
    if (scriptAttachment) {
      const scriptName = scriptAttachment.file.name;
      useLaunchUploadStore.getState().fileStarted(projectId, scriptName);
      try {
        await importTimelineScript(
          project.projectId,
          DEFAULT_TIMELINE_ID,
          { file: scriptAttachment.file },
          scriptIdempotencyKey || undefined,
        );
        useLaunchUploadStore
          .getState()
          .fileFinished(projectId, scriptName, true);
      } catch (error) {
        // Never lose the user's file: warn and fall back to material ingest.
        message.warning(
          i18n.t("home.scriptImportAtLaunchFailed", {
            detail: (error as Error).message,
          }),
        );
        try {
          const accepted = await ingestAssetFile(
            project.projectId,
            scriptAttachment.file,
            "NONE",
            { clientRequestId: newClientId("asset") },
          );
          const taskRefs = accepted.assetVersionId
            ? [`asset-version:${accepted.assetVersionId}`]
            : await waitForTask(project.projectId, accepted.taskId);
          refs.push(...taskRefs);
          useLaunchUploadStore
            .getState()
            .fileFinished(projectId, scriptName, true);
        } catch (fallbackError) {
          useLaunchUploadStore
            .getState()
            .fileFinished(projectId, scriptName, false);
          message.warning(
            i18n.t("lib.attachmentIngestFailed", {
              name: scriptName,
              detail: (fallbackError as Error).message,
            }),
          );
        }
      }
    }

    if (folderFiles.length > 0) {
      const files = folderFiles.map((att) => att.file);
      try {
        const accepted = await createAssetImport(
          project.projectId,
          files,
          "NONE",
          newClientId("asset"),
        );
        for (;;) {
          const view = await getAssetImport(
            project.projectId,
            accepted.importId,
          );
          if (terminal.has(view.status)) {
            if (view.status !== "SUCCEEDED")
              throw new Error(
                i18n.t("lib.folderImportFailed", {
                  status: creatorStatusLabel(view.status),
                }),
              );
            refs.push(
              ...view.items.map(
                (item) => `asset-version:${item.assetVersionId}`,
              ),
            );
            if (view.failures.length > 0) {
              message.warning(
                i18n.t("lib.folderImportSkipped", {
                  count: view.failures.length,
                }),
              );
            }
            break;
          }
          await wait(800);
        }
        for (const att of folderFiles) {
          useLaunchUploadStore
            .getState()
            .fileFinished(projectId, att.file.name, true);
        }
      } catch (error) {
        message.warning(
          i18n.t("lib.folderImportError", {
            detail: (error as Error).message,
          }),
        );
        for (const att of folderFiles) {
          useLaunchUploadStore
            .getState()
            .fileFinished(projectId, att.file.name, false);
        }
      }
    }

    await mapWithConcurrency(looseFiles, INGEST_CONCURRENCY, async (att) => {
      const store = useLaunchUploadStore.getState();
      store.fileStarted(projectId, att.file.name);
      try {
        const accepted = await ingestAssetFile(
          project.projectId,
          att.file,
          "NONE",
          { clientRequestId: newClientId("asset") },
        );
        const taskRefs = accepted.assetVersionId
          ? [`asset-version:${accepted.assetVersionId}`]
          : await waitForTask(project.projectId, accepted.taskId);
        refs.push(...taskRefs);
        useLaunchUploadStore
          .getState()
          .fileFinished(projectId, att.file.name, true);
      } catch (error) {
        useLaunchUploadStore
          .getState()
          .fileFinished(projectId, att.file.name, false);
        message.warning(
          i18n.t("lib.attachmentIngestFailed", {
            name: att.file.name,
            detail: (error as Error).message,
          }),
        );
      }
    });

    for (const att of urlAttachments) {
      // The Agent can consume the public URL immediately. Local caching is
      // a parallel Runtime task whose progress is rendered in the Project.
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
          newClientId("asset"),
        );
        if (accepted.assetVersionId) {
          refs.push(`asset-version:${accepted.assetVersionId}`);
        }
        useLaunchUploadStore.getState().fileFinished(projectId, att.url, true);
      } catch (error) {
        useLaunchUploadStore.getState().fileFinished(projectId, att.url, false);
        message.warning(
          i18n.t("lib.attachmentIngestFailed", {
            name: att.url,
            detail: (error as Error).message,
          }),
        );
      }
    }

    useLaunchUploadStore.getState().messaging(projectId);
    const uniqueRefs = [...new Set(refs)].filter((ref) =>
      ref.startsWith("asset-version:"),
    );
    // Deliberate: the first message is sent even when every ingest failed —
    // the text goal alone is a valid brief, and each failure was already
    // surfaced to the user as a warning above.
    await sendCreatorMessage(project.projectId, {
      clientMessageId: newClientId("initial-message"),
      creatorSessionId: project.creatorSessionId,
      conversationId: project.conversationId,
      content: [{ type: "text", text: goal }, ...remoteContentParts],
      assetVersionRefs: uniqueRefs,
      context: { panel: "composer" },
    });
    useLaunchUploadStore.getState().finish(projectId, true);
  } catch (error) {
    useLaunchUploadStore.getState().finish(projectId, false);
    message.error((error as Error).message || i18n.t("home.launchFailed"));
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
    return { type: "text", text: i18n.t("lib.remoteSourceUrl", { url }) };
  }
  if (/\.(png|jpe?g|webp|gif|bmp|avif)$/.test(pathname)) {
    return { type: "image_url", image_url: { url } };
  }
  if (/\.(mp4|mov|m4v|webm|mkv|avi|mpeg|mpg)$/.test(pathname)) {
    return { type: "video_url", video_url: { url } };
  }
  return { type: "text", text: i18n.t("lib.remoteSourceUrl", { url }) };
}

/**
 * Shared Project launch state machine used by both the inline hero composer
 * and the legacy modal composer: draft fields, attachment intake (file /
 * folder / URL), required-model validation and the idempotent launch flow.
 */
export function useProjectLaunch(options?: {
  onLaunched?: () => void;
  initialValues?: {
    name: string;
    description: string;
    scenario: CreatorScenario;
    contentType: string | null;
    resolution: string;
    aspectRatio: string;
    sourceUrls: string[];
  };
}) {
  const { t } = useTranslation();
  const onLaunched = options?.onLaunched;
  const initialValues = options?.initialValues;
  const router = useRouter();
  const [projectName, setProjectName] = useState(initialValues?.name ?? "");
  const [projectDescription, setProjectDescription] = useState(
    initialValues?.description ?? "",
  );
  const [scenario, setScenario] = useState<CreatorScenario>(
    (initialValues?.scenario as CreatorScenario) ?? "short_drama",
  );
  const [contentType, setContentType] = useState<string | null>(
    initialValues?.contentType ?? null,
  );
  const [resolution, setResolution] = useState<"720P" | "1080P">(
    (initialValues?.resolution as "720P" | "1080P") ?? "720P",
  );
  const [aspectRatio, setAspectRatio] = useState<string>(
    initialValues?.aspectRatio ?? "16:9",
  );
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(
    null,
  );
  const [attachments, setAttachments] = useState<AttachmentDraft[]>(() =>
    (initialValues?.sourceUrls ?? []).map((url) => ({
      kind: "url" as const,
      id: `att-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      url,
    })),
  );
  const [urlDraft, setUrlDraft] = useState("");
  const [launching, setLaunching] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const projectRequest = useRef({ signature: "", id: "" });
  const initialMessageRequests = useRef(new Map<string, string>());
  const sourceRequestIds = useRef(new Map<string, string>());
  // Shared snapshot: saving the config in the home banner or header badges
  // modal must clear this composer's required-model hint without a reload.
  const modelConfig = useModelConfigStore((state) => state.config);
  const refreshModelConfig = useModelConfigStore((state) => state.refresh);
  const [modelConfigModalOpen, setModelConfigModalOpen] = useState(false);
  // Match the server's launch policy: confirmation modes start with script
  // review, while automatic/YOLO modes need the media models up front.
  const scriptFirst = modelConfig?.executionAuthorization?.mode !== "allow_all";
  const hasUrl =
    urlDraft.trim().length > 0 || attachments.some((att) => att.kind === "url");
  const hasAttachments = attachments.length > 0 || hasUrl;
  const missingRequiredModels: string[] | null = useMemo(() => {
    if (!modelConfig) return null;
    const config = modelConfig as Partial<ModelConfigData>;
    const required: ("llm" | "vlm" | "image" | "video")[] =
      scenario === "short_drama" && !scriptFirst
        ? ["llm", "vlm", "image", "video"]
        : scenario === "video_edit" || hasAttachments
        ? ["llm", "vlm"]
        : ["llm"];
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
  }, [modelConfig, scenario, hasAttachments, scriptFirst]);
  useEffect(() => {
    void refreshModelConfig();
  }, [refreshModelConfig]);

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
    // 2 * 1024 * 1024 * 1024: 2GB
    const oversized = files.filter(
      (file) => file.size > 2 * 1024 * 1024 * 1024,
    );
    if (oversized.length > 0) {
      const errorMessage = `${oversized.map((f) => f.name).join("\n")}`;
      Modal.error({
        title: t("home.fileSizeLimit"),
        content: <div style={{ whiteSpace: "pre-wrap" }}>{errorMessage}</div>,
      });
      return true;
    }
    return false;
  };

  const addFiles = useCallback(
    (files: FileList | File[], source: "file" | "folder" = "file") => {
      const incoming = Array.from(files);
      if (stopOnOversizedFiles(incoming)) {
        return;
      }
      const drafts = incoming.map((file) => ({
        kind: "file" as const,
        id: newClientId("att"),
        file,
        source,
        relativePath:
          source === "folder"
            ? (file as File & { webkitRelativePath?: string })
                .webkitRelativePath || file.name
            : undefined,
        scriptKind: "none" as ScriptUploadKind,
        asScript: false,
      }));
      setAttachments((prev) => [...prev, ...drafts]);
      // Detect script-like files in the background and patch the chips in
      // place. Media short-circuits to "none" without reading; text reads only
      // the first screen. Detection just reveals the 剧本/素材 switch — the
      // default stays 素材 (asScript=false), so a file is imported as a script
      // only when the user explicitly opts in via its chip.
      void Promise.all(
        drafts.map(async (draft) => ({
          id: draft.id,
          detected: await detectScriptUpload(draft.file),
        })),
      ).then((results) => {
        const detectedById = new Map(results.map((r) => [r.id, r.detected]));
        setAttachments((prev) =>
          prev.map((att) => {
            if (att.kind !== "file") return att;
            const detected = detectedById.get(att.id);
            if (!detected || detected === "none") return att;
            return { ...att, scriptKind: detected };
          }),
        );
      });
    },
    [],
  );

  const addUrl = () => {
    const url = urlDraft.trim();
    if (!url) return;
    if (!/^https?:\/\//i.test(url)) {
      message.warning(t("home.urlFormatError"));
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

  // Flip a file between "import as script" and "understand as material".
  // Marking one as script clears any other, so creation lands at most one
  // script on the single default Timeline.
  const toggleAttachmentScript = useCallback((id: string) => {
    setAttachments((prev) => {
      const target = prev.find((att) => att.id === id);
      const next = !(target && target.kind === "file" && target.asScript);
      return prev.map((att) => {
        if (att.kind !== "file") return att;
        if (att.id === id) return { ...att, asScript: next };
        return next ? { ...att, asScript: false } : att;
      });
    });
  }, []);

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
    if (!projectDescription.trim()) return t("home.inputPlaceholder");
    if (isVideoEdit && contentType === null) return t("home.selectContentType");
    if (hasMissingModels) return t("home.configureRequiredModel");
    return undefined;
  };

  const handleLaunch = async () => {
    if (!projectDescription.trim()) {
      message.warning(t("home.describeTargetFirst"));
      return;
    }
    if (isVideoEdit && contentType === null) {
      message.warning(t("home.selectContentType"));
      return;
    }
    if (hasMissingModels) {
      message.warning(t("home.configureRequiredModel"));
      return;
    }
    const pendingUrl = urlDraft.trim();
    if (pendingUrl && !/^https?:\/\//i.test(pendingUrl)) {
      message.warning(t("home.urlFormatError"));
      return;
    }
    setLaunching(true);
    try {
      const resolvedProjectName =
        projectName.trim() || projectNameFromDescription(projectDescription);
      const projectPayload = {
        // Resolve the stage from the saved permission mode on the server,
        // so a stale client snapshot cannot override the user's choice.
        name: resolvedProjectName,
        description: projectDescription.trim(),
        scenario,
        resolution,
        aspectRatio,
        contentType: isVideoEdit ? contentType : null,
        templateId: selectedTemplateId ?? undefined,
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
      // A file the user marked as a script lands directly (no source ingest);
      // everything else keeps the unchanged material-understanding path.
      const scriptAttachment =
        fileAttachments.find((att) => att.asScript) ?? null;
      const scriptIdempotencyKey = scriptAttachment
        ? requestIdFor(`script:${scriptAttachment.id}`)
        : "";
      const materialFiles = scriptAttachment
        ? fileAttachments.filter((att) => att.id !== scriptAttachment.id)
        : fileAttachments;
      const folderFiles = materialFiles.filter(
        (att) => att.source === "folder",
      );
      const looseFiles = materialFiles.filter((att) => att.source !== "folder");
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
        router.push(`/project/${project.projectId}`);
        onLaunched?.();
        projectRequest.current = { signature: "", id: "" };
        initialMessageRequests.current.clear();
        sourceRequestIds.current.clear();
        return;
      }

      // Navigate immediately: the user lands on the project page while
      // attachments upload in the background. The continuation lives at
      // module level (not in this component's closure), reports to the
      // launch-upload store for the workspace progress card, and sends
      // the durable first message once every ingest settled — so a
      // torn-down composer can no longer strand a Goal-less Project.
      router.push(`/project/${project.projectId}`);
      onLaunched?.();
      projectRequest.current = { signature: "", id: "" };
      initialMessageRequests.current.clear();
      sourceRequestIds.current.clear();
      void continueLaunchInBackground({
        project,
        goal: projectDescription.trim(),
        scriptAttachment,
        scriptIdempotencyKey,
        folderFiles,
        looseFiles,
        urlAttachments,
      });
    } catch (error) {
      message.error((error as Error).message || t("home.launchFailed"));
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
    selectedTemplateId,
    setSelectedTemplateId,
    attachments,
    addFiles,
    addUrl,
    removeAttachment,
    toggleAttachmentScript,
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
