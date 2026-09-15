import { useEffect, useMemo, useState } from "react";
import { message } from "antd";
import { ArrowLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import WorkspaceEmptyState from "@/components/WorkspaceEmptyState";
import type {
  ProjectDocument,
  VisualEntityDocument,
  AssetUnderstandingView,
} from "@/contracts/creator";
import {
  getArtifactVersionMediaUrl,
  getAssetUnderstanding,
  getAssetVersionMediaUrl,
} from "@/api/creator";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { useCreatorInteractionStore } from "@/store/creatorInteractionStore";
import {
  isVoiceOnlyVisualEntity,
  selectResearchSlots,
  type ResolvedSlot,
} from "@/selectors/blueprintSelectors";
import { visualVariantLabel } from "@/lib/visualVariants";
import { dispatchWorkGraphNode } from "@/api/creator/workGraph";
import { nodeGenerating } from "@/lib/generationActivity";
import { useCreatorTaskViewStore } from "@/store/creatorTaskViewStore";
import {
  GenerationPromptEditor,
  buildPromptSaveOperations,
  dispatchNodeIdForPrompt,
  visualEntityPromptTarget,
  type PromptTarget,
} from "@/pages/AssetsPage";
import { TONE_CHIP } from "./tones";
import PreviewImage from "@/components/assets/PreviewImage";
import { projectJsonPointer } from "@/lib/projectJsonPointer";

export type PreproductionTab = "visual" | "research";

export type PrepFocus =
  | { type: "visual"; entityId: string }
  | { type: "research"; slotId: string }
  | { type: "source"; sourceId: string };

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wide text-[var(--color-text-tertiary)]">
      {children}
    </span>
  );
}

function KvLines({ kv }: { kv: Array<[string, string]> }) {
  return (
    <div>
      {kv.map(([key, value]) => (
        <div
          key={key}
          className="flex justify-between gap-2.5 border-b border-dashed border-[var(--color-border)] py-1.5 text-xs last:border-b-0"
        >
          <span className="shrink-0 text-[var(--color-text-tertiary)]">
            {key}
          </span>
          <span className="break-all text-right text-[var(--color-text-primary)]">
            {value}
          </span>
        </div>
      ))}
    </div>
  );
}

function entitySelectedVersionId(entity: VisualEntityDocument): string | null {
  if (entity.selected_artifact_version_id)
    return entity.selected_artifact_version_id;
  for (const variantId of entity.variants.order) {
    const versionId =
      entity.variants.items[variantId]?.selected_artifact_version_id;
    if (versionId) return versionId;
  }
  return null;
}

/* ------------------------------------------------------------------ */
/* Visual entity detail                                                 */
/* ------------------------------------------------------------------ */

function VisualDetail({
  project,
  projectId,
  entity,
  onBack,
}: {
  project: ProjectDocument;
  projectId: string;
  entity: VisualEntityDocument;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const patchProject = useProjectSnapshotStore((state) => state.patch);
  const patching = useProjectSnapshotStore((state) => state.patching);
  const [viewedVariantId, setViewedVariantId] = useState<string | null>(null);
  const variantIds = entity.variants.order.filter(
    (id) => entity.variants.items[id],
  );
  const variantId =
    (viewedVariantId && variantIds.includes(viewedVariantId)
      ? viewedVariantId
      : null) ??
    (entity.canonical_variant_id &&
    variantIds.includes(entity.canonical_variant_id)
      ? entity.canonical_variant_id
      : variantIds[0]);
  const variant = variantId ? entity.variants.items[variantId] : null;
  const selectedVersionId = variant
    ? variant.selected_artifact_version_id
    : entitySelectedVersionId(entity);
  const [viewedVersionId, setViewedVersionId] = useState<string | null>(null);
  useEffect(() => {
    setViewedVariantId(null);
    setViewedVersionId(null);
  }, [entity.entity_id]);
  const versionIds = Array.from(
    new Set([
      ...(variant?.generated_artifact_version_ids ?? []),
      ...(selectedVersionId ? [selectedVersionId] : []),
    ]),
  );
  const displayedVersionId =
    viewedVersionId && versionIds.includes(viewedVersionId)
      ? viewedVersionId
      : selectedVersionId;
  const imageUrl = displayedVersionId
    ? getArtifactVersionMediaUrl(displayedVersionId)
    : null;
  // Same editing surface as the asset library detail: fullscreen prompt
  // editor with pickable reference images, plus the DAG regenerate pill.
  const promptTarget = useMemo(
    () =>
      visualEntityPromptTarget(project, entity, selectedVersionId, variantId),
    [project, entity, selectedVersionId, variantId],
  );
  const regenerateNodeId = promptTarget
    ? dispatchNodeIdForPrompt(promptTarget.pointer)
    : null;
  const refreshTasks = useCreatorTaskViewStore((state) => state.refresh);
  const tasks = useCreatorTaskViewStore((state) => state.tasks);
  const pollOnce = useProjectSnapshotStore((state) => state.pollOnce);

  const regenerate = () => {
    if (!regenerateNodeId) return;
    void dispatchWorkGraphNode(projectId, regenerateNodeId)
      .then((result) => {
        if (result.dispatched) {
          message.success(t("r2v.regenQueued"));
        } else if (result.status === "running") {
          message.info(t("r2v.regenRunning"));
        } else {
          message.info(t("r2v.regenUpToDate"));
        }
        void refreshTasks(projectId);
        void pollOnce(projectId);
      })
      .catch((error) => message.error((error as Error).message));
  };

  const savePromptTarget = async (
    target: PromptTarget,
    next: string,
    addedReferenceIds: string[],
  ) => {
    try {
      const operations = buildPromptSaveOperations(
        project,
        target,
        next,
        addedReferenceIds,
      );
      if (!operations.length) return;
      await patchProject(projectId, operations);
      message.success(t("blueprint.promptSaved"));
    } catch (error) {
      message.error(
        t("blueprint.promptSaveFailed", { detail: (error as Error).message }),
      );
    }
  };

  return (
    <div className="panel-enter flex h-full min-h-0 flex-col">
      <button
        type="button"
        onClick={onBack}
        className="mb-3 inline-flex w-fit items-center gap-1.5 rounded-md px-1.5 py-1 text-xs font-semibold text-[var(--color-text-secondary)] transition-colors hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)]"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        {t("blueprint.backToList")}
      </button>
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pb-2">
        {variantIds.length > 1 && (
          <div>
            <FieldLabel>{t("blueprint.variantSelector")}</FieldLabel>
            <div className="flex flex-wrap gap-1.5">
              {variantIds.map((id) => (
                <button
                  type="button"
                  key={id}
                  aria-pressed={id === variantId}
                  title={entity.variants.items[id].requirements}
                  onClick={() => {
                    setViewedVariantId(id);
                    setViewedVersionId(null);
                  }}
                  className={`rounded-lg border px-3 py-1.5 text-left text-xs ${
                    id === variantId
                      ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                      : "border-[var(--color-border)] text-[var(--color-text-secondary)]"
                  }`}
                >
                  {visualVariantLabel(entity.variants.items[id])}
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="flex min-h-[220px] shrink-0 items-center justify-center rounded-[10px] border border-[var(--color-border)] bg-[var(--color-bg-secondary)] p-0">
          {imageUrl ? (
            // Full-frame portrait designs must show the whole figure —
            // cover-cropping cut the character's head off.
            <PreviewImage
              src={imageUrl}
              alt={entity.name}
              className="mx-auto max-h-[48vh] w-auto max-w-full object-contain"
            />
          ) : (
            <span className="p-2.5 text-xs text-[var(--color-text-tertiary)]">
              {t("blueprint.noDesignYet")}
            </span>
          )}
        </div>
        {versionIds.length > 0 && (
          <div>
            <FieldLabel>{t("blueprint.versions")}</FieldLabel>
            <div className="flex flex-wrap gap-1.5">
              {versionIds.map((versionId, index) => (
                <button
                  type="button"
                  key={versionId}
                  onClick={() => setViewedVersionId(versionId)}
                  aria-pressed={versionId === displayedVersionId}
                  className={`inline-flex h-[26px] items-center rounded-full border px-3 text-[11px] font-semibold ${
                    versionId === displayedVersionId
                      ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                      : "border-[var(--color-border)] bg-[var(--color-bg-primary)] text-[var(--color-text-secondary)]"
                  }`}
                >
                  v{index + 1}
                  {versionId === selectedVersionId
                    ? ` · ${t("assets.currentVersion")}`
                    : ""}
                </button>
              ))}
            </div>
          </div>
        )}
        <div>
          <FieldLabel>{t("blueprint.infoLabel")}</FieldLabel>
          <KvLines
            kv={[
              [
                t("blueprint.entityKind"),
                t(`blueprint.entityKinds.${entity.kind}`),
              ],
              [
                t("blueprint.variantCount"),
                String(entity.variants.order.length),
              ],
            ]}
          />
          <FieldLabel>{t("blueprint.continuity")}</FieldLabel>
          <p
            data-creator-field={`asset:${entity.entity_id}/continuity`}
            data-creator-path={projectJsonPointer(
              "visual",
              "entities",
              "items",
              entity.entity_id,
              "continuity",
            )}
            data-creator-field-label={t("blueprint.continuity")}
            className="select-text whitespace-pre-wrap text-xs leading-5"
          >
            {entity.continuity || "—"}
          </p>
        </div>
        {promptTarget && (
          <GenerationPromptEditor
            key={promptTarget.pointer}
            target={
              displayedVersionId !== selectedVersionId
                ? { ...promptTarget, label: t("assets.currentPrompt") }
                : promptTarget
            }
            saving={patching}
            regenerating={nodeGenerating(tasks, regenerateNodeId)}
            regenerateLabel={t("r2v.regenerateImage")}
            onRegenerate={regenerateNodeId ? regenerate : undefined}
            onSave={savePromptTarget}
          />
        )}
        <div className="mt-auto flex items-center gap-2 pt-1">
          <span className="text-[10px] leading-relaxed text-[var(--color-text-tertiary)]">
            {t("blueprint.visualApproveHint")}
          </span>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Research report detail                                               */
/* ------------------------------------------------------------------ */

function ResearchDetail({
  entry,
  onBack,
}: {
  entry: ResolvedSlot;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const [text, setText] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const versionId = entry.selected?.version_id ?? null;
  useEffect(() => {
    if (!versionId) return;
    let cancelled = false;
    fetch(getArtifactVersionMediaUrl(versionId))
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.text();
      })
      .then((body) => {
        if (!cancelled) setText(body);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [versionId]);

  return (
    <div className="panel-enter flex h-full min-h-0 flex-col">
      <button
        type="button"
        onClick={onBack}
        className="mb-3 inline-flex w-fit items-center gap-1.5 rounded-md px-1.5 py-1 text-xs font-semibold text-[var(--color-text-secondary)] transition-colors hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)]"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        {t("blueprint.backToList")}
      </button>
      <div
        className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pb-2"
        data-creator-field={`research:${entry.slot.slot_id}/conclusion`}
        data-creator-field-label={
          entry.selected?.name || t("blueprint.researchReport")
        }
        data-creator-path={
          entry.selected
            ? `artifact:${entry.slot.slot_id}@${entry.selected.version_id}`
            : undefined
        }
      >
        <FieldLabel>{t("blueprint.researchConclusion")}</FieldLabel>
        {text !== null ? (
          <div className="whitespace-pre-wrap text-xs leading-relaxed text-[var(--color-text-primary)]">
            {text}
          </div>
        ) : failed ? (
          <p className="text-xs text-[var(--color-text-tertiary)]">
            {t("blueprint.researchLoadFailed")}
          </p>
        ) : versionId ? (
          <p className="text-xs text-[var(--color-text-tertiary)]">
            {t("blueprint.scriptLoading")}
          </p>
        ) : (
          <p className="text-xs text-[var(--color-text-tertiary)]">
            {t("blueprint.researchRunning")}
          </p>
        )}
        <p className="mt-auto pt-1 text-[10px] leading-relaxed text-[var(--color-text-tertiary)]">
          {t("blueprint.researchApproveHint")}
        </p>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Source understanding detail                                          */
/* ------------------------------------------------------------------ */

function currentSourceIntelligence(project: ProjectDocument, sourceId: string) {
  const source = project.sources.sources.items[sourceId];
  const intelligence = source?.current_intelligence_version_id
    ? project.assets.intelligence_versions_by_id[
        source.current_intelligence_version_id
      ]
    : null;
  return intelligence?.source_asset_version_id ===
    source?.selected_asset_version_id
    ? intelligence
    : null;
}

function SourceDetail({
  project,
  sourceId,
  onBack,
}: {
  project: ProjectDocument;
  sourceId: string;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const source = project.sources.sources.items[sourceId];
  const intelligence = currentSourceIntelligence(project, sourceId);
  const version = source
    ? project.assets.source_versions_by_id[source.selected_asset_version_id]
    : null;
  const [result, setResult] = useState<AssetUnderstandingView | null>(null);
  const [loadError, setLoadError] = useState(false);
  useEffect(() => {
    let active = true;
    setResult(null);
    setLoadError(false);
    if (source && intelligence) {
      void getAssetUnderstanding(
        project.project_id,
        source.logical_asset_id,
        intelligence.intelligence_version_id,
      )
        .then((value) => {
          if (active) setResult(value);
        })
        .catch(() => {
          if (active) setLoadError(true);
        });
    }
    return () => {
      active = false;
    };
  }, [
    project.project_id,
    source?.logical_asset_id,
    intelligence?.intelligence_version_id,
  ]);
  const rows = (value: unknown): Array<Record<string, unknown>> =>
    Array.isArray(value)
      ? value.filter((item) => item && typeof item === "object")
      : [];
  if (!source) return null;
  return (
    <div className="panel-enter flex h-full min-h-0 flex-col">
      <button
        type="button"
        onClick={onBack}
        className="mb-3 inline-flex w-fit items-center gap-1.5 rounded-md px-1.5 py-1 text-xs font-semibold text-[var(--color-text-secondary)] transition-colors hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)]"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        {t("blueprint.backToList")}
      </button>
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pb-2">
        {version?.media_kind === "image" && (
          <PreviewImage
            src={getAssetVersionMediaUrl(version.version_id)}
            alt={source.display_name}
            className="max-h-64 w-full shrink-0 rounded-lg object-contain"
          />
        )}
        <div>
          <FieldLabel>{t("blueprint.sourceSummary")}</FieldLabel>
          <KvLines
            kv={[
              [t("common.name"), source.display_name || source.source_id],
              [t("blueprint.mediaKind"), version?.media_kind ?? "—"],
              [
                t("common.duration"),
                version?.duration_seconds != null
                  ? `${version.duration_seconds}s`
                  : "—",
              ],
              [
                t("blueprint.understandingState"),
                intelligence
                  ? t("blueprint.board.sourceUnderstood")
                  : t("blueprint.board.sourcePending"),
              ],
            ]}
          />
        </div>
        {intelligence && (
          <section className="space-y-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-secondary)]/50 p-3">
            <h3 className="text-sm font-semibold">
              {t("blueprint.sourceFindings")}
            </h3>
            <div
              data-creator-field={`asset:${source.logical_asset_id}/understanding`}
              data-creator-field-label={t("blueprint.sourceFindings")}
              className="select-text space-y-4 text-xs leading-6"
            >
              {result ? (
                <>
                  <p className="whitespace-pre-wrap">{result.summary}</p>
                  {rows(result.entities).length > 0 && (
                    <div>
                      <FieldLabel>{t("blueprint.sourceEntities")}</FieldLabel>
                      {rows(result.entities).map((entity, index) => (
                        <p key={index}>
                          <strong>
                            {String(entity.label ?? entity.name ?? "")}
                          </strong>{" "}
                          {String(entity.description ?? "")}
                        </p>
                      ))}
                    </div>
                  )}
                  {rows(result.semanticEntries).length > 0 && (
                    <div>
                      <FieldLabel>{t("blueprint.sourceEvents")}</FieldLabel>
                      {rows(result.semanticEntries).map((entry, index) => (
                        <p
                          key={index}
                          className="mb-2 border-l-2 border-[var(--color-border)] pl-2"
                        >
                          {typeof entry.startMs === "number"
                            ? `${entry.startMs / 1000}s–${
                                Number(entry.endMs) / 1000
                              }s · `
                            : ""}
                          {String(entry.text ?? "")}
                        </p>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <p role="status">
                  {t(
                    loadError
                      ? "blueprint.sourceResultFailed"
                      : "blueprint.sourceResultLoading",
                  )}
                </p>
              )}
            </div>
          </section>
        )}
        {intelligence && Object.keys(intelligence.coverage).length > 0 && (
          <div>
            <FieldLabel>{t("blueprint.coverage")}</FieldLabel>
            <KvLines
              kv={Object.entries(intelligence.coverage).map(
                ([key, value]) => [key, String(value)] as [string, string],
              )}
            />
          </div>
        )}
        {source.user_notes && (
          <div className="rounded-r-lg border-l-[3px] border-[var(--color-accent)] bg-[var(--color-accent-soft)] px-3 py-2 text-xs text-[var(--color-text-secondary)]">
            {source.user_notes}
          </div>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Full-page pre-production view                                        */
/* ------------------------------------------------------------------ */

interface BlueprintPrepDrawerProps {
  project: ProjectDocument;
  projectId: string;
  open: boolean;
  tab: PreproductionTab;
  focus: PrepFocus | null;
  onClose: () => void;
  onTabChange: (tab: PreproductionTab) => void;
}

type VisualKind = VisualEntityDocument["kind"];

const VISUAL_KINDS: VisualKind[] = ["character", "scene", "prop"];

function EntityTag({ designed }: { designed: boolean }) {
  const { t } = useTranslation();
  return (
    <span
      className={`shrink-0 rounded px-1.5 text-[10px] font-semibold leading-[18px] ${
        designed ? TONE_CHIP.done : TONE_CHIP.wait
      }`}
    >
      {designed
        ? t("blueprint.board.visualReady")
        : t("blueprint.board.visualPending")}
    </span>
  );
}

/**
 * Pre-production view (视觉开发 / 调研与素材). The updated design (84:28086,
 * 84:41347, 84:39974) renders these as full workspace-column pages with a
 * 返回 header instead of a side drawer; the AgentDock column stays usable.
 */
export default function BlueprintPrepDrawer({
  project,
  projectId,
  open,
  tab,
  focus,
  onClose,
  onTabChange,
}: BlueprintPrepDrawerProps) {
  const { t } = useTranslation();
  const [detail, setDetail] = useState<PrepFocus | null>(null);
  const [kind, setKind] = useState<VisualKind>("character");
  useEffect(() => {
    setDetail(focus);
  }, [focus, open]);
  const focusedKind =
    focus?.type === "visual"
      ? project.visual.entities.items[focus.entityId]?.kind
      : null;
  useEffect(() => {
    if (focusedKind) setKind(focusedKind);
  }, [focusedKind]);

  // Escape closes the page (detail level first, then the page itself).
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA)$/.test(target.tagName)) return;
      setDetail((current) => {
        if (current) return null;
        onClose();
        return current;
      });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const entities = useMemo(
    () =>
      project.visual.entities.order
        .map((entityId) => project.visual.entities.items[entityId])
        .filter(Boolean),
    [project],
  );
  const research = useMemo(() => selectResearchSlots(project), [project]);
  const sources = useMemo(
    () =>
      project.sources.sources.order
        .map((sourceId) => project.sources.sources.items[sourceId])
        .filter(Boolean),
    [project],
  );

  if (!open) return null;

  const openDetail = (next: PrepFocus, ref: string) => {
    useCreatorInteractionStore.getState().select(ref);
    setDetail(next);
  };

  const detailNode = (() => {
    if (!detail) return null;
    if (detail.type === "visual") {
      const entity = project.visual.entities.items[detail.entityId];
      return entity ? (
        <VisualDetail
          project={project}
          projectId={projectId}
          entity={entity}
          onBack={() => setDetail(null)}
        />
      ) : null;
    }
    if (detail.type === "research") {
      const entry = research.find(
        (candidate) => candidate.slot.slot_id === detail.slotId,
      );
      return entry ? (
        <ResearchDetail entry={entry} onBack={() => setDetail(null)} />
      ) : null;
    }
    return (
      <SourceDetail
        project={project}
        sourceId={detail.sourceId}
        onBack={() => setDetail(null)}
      />
    );
  })();

  // 旁白/画外音: voice-only roles have no visual design card.
  const kindEntities = entities.filter(
    (entity) => entity.kind === kind && !isVoiceOnlyVisualEntity(entity),
  );

  const visualGrid =
    kind === "character" ? (
      // 角色卡 (84:39974): portrait 86×116 + name/tag, 形象：, bio — 3/row.
      <div className="grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-3">
        {kindEntities.map((entity) => {
          const versionId = entitySelectedVersionId(entity);
          const primaryVariant = entity.variants.order[0]
            ? entity.variants.items[entity.variants.order[0]]
            : null;
          return (
            <button
              key={entity.entity_id}
              type="button"
              onClick={() =>
                openDetail(
                  { type: "visual", entityId: entity.entity_id },
                  `visual-entity:${entity.entity_id}`,
                )
              }
              className="flex gap-3 rounded-lg bg-[var(--color-bg-secondary)] p-3 text-left transition-colors hover:bg-[var(--color-bg-secondary)]"
            >
              <span className="h-[116px] w-[86px] shrink-0 overflow-hidden rounded-md bg-[var(--color-bg-tertiary,var(--color-bg-secondary))]">
                {versionId && (
                  <img
                    src={getArtifactVersionMediaUrl(versionId)}
                    alt={entity.name}
                    loading="lazy"
                    className="h-full w-full object-cover object-top"
                  />
                )}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1.5">
                  <b className="truncate text-sm font-medium text-[var(--color-text-primary)]">
                    {entity.name}
                  </b>
                  <EntityTag designed={versionId != null} />
                </span>
                {primaryVariant && (
                  <span className="mt-0.5 block truncate text-xs text-[var(--color-text-tertiary)]">
                    {t("blueprint.variantLine", {
                      label: visualVariantLabel(primaryVariant, 16),
                    })}
                  </span>
                )}
                <p className="mt-1 line-clamp-4 text-xs leading-5 text-[var(--color-text-tertiary)]">
                  {entity.description || entity.continuity || "—"}
                </p>
              </span>
            </button>
          );
        })}
        {kindEntities.length === 0 && (
          <div className="col-span-full">
            <WorkspaceEmptyState projectId={projectId} area="visual" />
          </div>
        )}
      </div>
    ) : (
      // 道具/场景卡 (84:28086/84:41347): image tile + name/tag + description.
      <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-3">
        {kindEntities.map((entity) => {
          const versionId = entitySelectedVersionId(entity);
          return (
            <button
              key={entity.entity_id}
              type="button"
              onClick={() =>
                openDetail(
                  { type: "visual", entityId: entity.entity_id },
                  `visual-entity:${entity.entity_id}`,
                )
              }
              className="flex flex-col gap-1.5 rounded-lg bg-[var(--color-bg-secondary)] p-3 text-left transition-colors hover:bg-[var(--color-bg-secondary)]"
            >
              <span className="h-[116px] w-full overflow-hidden rounded-md bg-[var(--color-bg-tertiary,var(--color-bg-secondary))]">
                {versionId && (
                  <img
                    src={getArtifactVersionMediaUrl(versionId)}
                    alt={entity.name}
                    loading="lazy"
                    className="h-full w-full object-cover"
                  />
                )}
              </span>
              <span className="flex items-center gap-1.5">
                <b className="truncate text-sm font-medium text-[var(--color-text-primary)]">
                  {entity.name}
                </b>
                <EntityTag designed={versionId != null} />
              </span>
              <p className="line-clamp-2 text-xs leading-5 text-[var(--color-text-tertiary)]">
                {entity.description || entity.continuity || "—"}
              </p>
            </button>
          );
        })}
        {kindEntities.length === 0 && (
          <div className="col-span-full">
            <WorkspaceEmptyState projectId={projectId} area="visual" />
          </div>
        )}
      </div>
    );

  const researchList = (
    <div className="overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)]">
      {research.map((entry) => (
        <button
          key={entry.slot.slot_id}
          type="button"
          onClick={() =>
            openDetail(
              { type: "research", slotId: entry.slot.slot_id },
              `research:${entry.slot.slot_id}`,
            )
          }
          className="flex w-full items-start gap-2.5 border-b border-[var(--color-border)] px-3 py-2.5 text-left transition-colors last:border-b-0 hover:bg-[var(--color-bg-secondary)]"
        >
          <span className="min-w-0 flex-1">
            <b className="block truncate text-xs font-semibold text-[var(--color-text-primary)]">
              {entry.selected?.name ||
                String(
                  entry.slot.metadata.topic || t("blueprint.researchReport"),
                )}
            </b>
            <p className="mt-0.5 line-clamp-2 text-[11px] leading-relaxed text-[var(--color-text-secondary)]">
              {t("blueprint.researchSummary")}
            </p>
          </span>
          <span
            className={`shrink-0 rounded px-1.5 text-[10px] font-semibold leading-[18px] ${
              entry.selected ? TONE_CHIP.done : TONE_CHIP.run
            }`}
          >
            {entry.selected
              ? t("blueprint.board.researchReady")
              : t("blueprint.board.researchRunning")}
          </span>
        </button>
      ))}
      {sources.map((source) => (
        <button
          key={source.source_id}
          type="button"
          onClick={() =>
            openDetail(
              { type: "source", sourceId: source.source_id },
              `asset-version:${source.selected_asset_version_id}`,
            )
          }
          className="flex w-full items-start gap-2.5 border-b border-[var(--color-border)] px-3 py-2.5 text-left transition-colors last:border-b-0 hover:bg-[var(--color-bg-secondary)]"
        >
          <span className="min-w-0 flex-1">
            <b className="block truncate text-xs font-semibold text-[var(--color-text-primary)]">
              {source.display_name || source.source_id}
            </b>
            <p className="mt-0.5 line-clamp-2 text-[11px] leading-relaxed text-[var(--color-text-secondary)]">
              {source.user_notes || t("blueprint.sourceUnderstanding")}
            </p>
          </span>
          <span
            className={`shrink-0 rounded px-1.5 text-[10px] font-semibold leading-[18px] ${
              currentSourceIntelligence(project, source.source_id)
                ? TONE_CHIP.done
                : TONE_CHIP.wait
            }`}
          >
            {currentSourceIntelligence(project, source.source_id)
              ? t("blueprint.board.sourceUnderstood")
              : t("blueprint.board.sourcePending")}
          </span>
        </button>
      ))}
      {!research.length && !sources.length && (
        <WorkspaceEmptyState projectId={projectId} area="research" />
      )}
    </div>
  );

  return (
    <div
      data-blueprint-prep-drawer
      className="panel-enter absolute inset-0 z-30 flex min-h-0 flex-col bg-[var(--color-bg-layout)]"
    >
      {/* 返回 + 标题 (design 84:28086): full page header. */}
      <div className="flex flex-wrap items-center gap-2.5 border-b border-[var(--color-border)] bg-[var(--color-bg-primary)] px-5 py-3">
        <button
          type="button"
          onClick={onClose}
          className="btn-secondary shrink-0"
          title={t("blueprint.closeKeepRef")}
        >
          {t("common.back")}
        </button>
        <h3 className="text-sm font-medium text-[var(--color-text-primary)]">
          {tab === "visual"
            ? t("blueprint.visualDev")
            : t("blueprint.researchAndSources")}
        </h3>
        {detailNode == null && tab === "visual" && (
          <span className="ml-4 flex items-center gap-1.5">
            {VISUAL_KINDS.map((candidate) => (
              <button
                key={candidate}
                type="button"
                data-visual-kind={candidate}
                onClick={() => setKind(candidate)}
                className={`rounded-full px-3.5 py-1 text-xs transition ${
                  kind === candidate
                    ? "bg-[var(--color-bg-secondary)] font-medium text-[var(--color-text-primary)]"
                    : "border border-[var(--color-border)] bg-white text-[var(--color-text-secondary)] hover:border-[var(--color-accent)]/50 dark:bg-[var(--color-bg-primary)]"
                }`}
              >
                {t(`blueprint.entityKinds.${candidate}`)}
              </button>
            ))}
          </span>
        )}
        {entities.length > 0 && tab === "research" && (
          <button
            type="button"
            className="ml-4 text-xs text-[var(--color-text-tertiary)] transition-colors hover:text-[var(--color-accent)]"
            onClick={() => {
              setDetail(null);
              onTabChange("visual");
            }}
          >
            {t("blueprint.visualDev")} »
          </button>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
        {detailNode ?? (tab === "visual" ? visualGrid : researchList)}
      </div>
    </div>
  );
}
