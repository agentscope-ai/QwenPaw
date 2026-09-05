import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Image as ImageIcon, X } from "lucide-react";
import type {
  ProjectDocument,
  TimelineElementDocument,
  VisualEntityDocument,
} from "@/contracts/creator";
import { getArtifactVersionMediaUrl } from "@/api/creator";
import {
  selectTimelineRenderSlot,
  type TimelineSummary,
} from "@/selectors/blueprintSelectors";
import { TONE_CHIP } from "./tones";

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

/** Visual entities referenced by the given enabled elements. */
export function referencedEntities(
  project: ProjectDocument,
  elements: TimelineElementDocument[],
): VisualEntityDocument[] {
  const referenced = new Set<string>();
  for (const element of elements) {
    const creation = element.creation;
    if (creation.type === "r2v") {
      creation.character_refs.forEach((ref) => referenced.add(ref));
      if (creation.scene_ref) referenced.add(creation.scene_ref);
      creation.prop_refs.forEach((ref) => referenced.add(ref));
    } else if (creation.type === "s2v" && creation.character_ref) {
      referenced.add(creation.character_ref);
    }
  }
  return project.visual.entities.order
    .filter((entityId) => referenced.has(entityId))
    .map((entityId) => project.visual.entities.items[entityId])
    .filter(Boolean);
}

export function SectionLabel({ text }: { text: string }) {
  return (
    <span className="block text-sm font-medium text-[var(--color-text-primary)]">
      {text}
    </span>
  );
}

export function EntityGroup({
  label,
  entities,
  onOpen,
  onRemove,
}: {
  label: string;
  entities: VisualEntityDocument[];
  onOpen: (entityId: string) => void;
  onRemove?: (entityId: string) => void;
}) {
  const { t } = useTranslation();
  if (entities.length === 0) return null;
  return (
    <div className="space-y-2">
      <SectionLabel text={label} />
      <div className="grid grid-cols-2 gap-2.5">
        {entities.map((entity) => {
          const versionId = entitySelectedVersionId(entity);
          const designed = versionId != null;
          return (
            <div key={entity.entity_id} className="group/card relative">
              <button
                type="button"
                title={t("blueprint.openVisualDetail")}
                onClick={() => onOpen(entity.entity_id)}
                className="group block w-full text-left"
              >
                <span
                  className={`relative block aspect-video w-full overflow-hidden rounded-lg border ${
                    designed
                      ? "border-[var(--color-border)] bg-[var(--color-bg-secondary)]"
                      : "border-dashed border-[var(--color-border-strong)] bg-[var(--color-bg-secondary)]/50"
                  }`}
                >
                  {versionId ? (
                    <img
                      src={getArtifactVersionMediaUrl(versionId)}
                      alt=""
                      loading="lazy"
                      className="h-full w-full object-cover transition-transform duration-200 group-hover:scale-[1.03]"
                    />
                  ) : (
                    <span className="flex h-full w-full flex-col items-center justify-center gap-1">
                      <ImageIcon className="h-5 w-5 text-[var(--color-text-tertiary)]" />
                      <span className="text-[10px] text-[var(--color-text-tertiary)]">
                        {t("blueprint.notGenerated")}
                      </span>
                    </span>
                  )}
                  <span className="absolute right-1 top-1 rounded bg-black/55 px-1.5 py-0.5 text-[10px] font-medium text-white">
                    {label}
                  </span>
                </span>
                <span className="mt-1 block truncate text-xs text-[var(--color-text-primary)]">
                  {entity.name}
                </span>
              </button>
              {onRemove && (
                <button
                  type="button"
                  aria-label={t("blueprint.removeEntity")}
                  title={t("blueprint.removeEntity")}
                  onClick={() => onRemove(entity.entity_id)}
                  className="absolute -right-1.5 -top-1.5 hidden h-5 w-5 items-center justify-center rounded-full border border-[var(--color-border)] bg-[var(--color-bg-primary)] text-[var(--color-text-secondary)] shadow-sm hover:text-[var(--color-error)] group-hover/card:flex"
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

interface EpisodeOverviewRailProps {
  project: ProjectDocument;
  timelineId: string;
  elements: TimelineElementDocument[];
  summary: TimelineSummary;
  onOpenVisualEntity: (entityId: string) => void;
}

/**
 * 本集概览 rail of the script review page (design 83:13383): the episode's
 * final cut, its stage status and the referenced 角色/道具/场景 asset cards.
 */
export default function EpisodeOverviewRail({
  project,
  timelineId,
  elements,
  summary,
  onOpenVisualEntity,
}: EpisodeOverviewRailProps) {
  const { t } = useTranslation();
  const render = useMemo(
    () => selectTimelineRenderSlot(project, timelineId),
    [project, timelineId],
  );
  const renderVersionId =
    render?.selected && !render.selected.stale
      ? render.selected.version_id
      : null;
  const entities = useMemo(
    () => referencedEntities(project, elements),
    [elements, project],
  );
  const characters = entities.filter((entity) => entity.kind === "character");
  const props = entities.filter((entity) => entity.kind === "prop");
  const scenes = entities.filter((entity) => entity.kind === "scene");

  return (
    <aside
      data-episode-overview-rail
      className="flex min-h-0 flex-col overflow-y-auto border-l border-[var(--color-border)] bg-[var(--color-bg-primary)]"
    >
      <div className="border-b border-[var(--color-border)] px-4 py-3">
        <span className="text-sm font-medium text-[var(--color-text-primary)]">
          {t("blueprint.overviewTitle")}
        </span>
      </div>
      <div className="min-h-0 flex-1 space-y-5 px-4 py-4">
        <div className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-black">
          {renderVersionId ? (
            <video
              src={getArtifactVersionMediaUrl(renderVersionId)}
              controls
              preload="metadata"
              className="aspect-video w-full"
            />
          ) : (
            <div className="flex aspect-video w-full items-center justify-center bg-[var(--color-bg-secondary)] text-[11px] text-[var(--color-text-tertiary)]">
              {t("blueprint.noFinalCut")}
            </div>
          )}
        </div>

        <div className="space-y-2">
          <SectionLabel text={t("blueprint.stageStatus")} />
          <div className="flex flex-wrap gap-1.5">
            <span
              className={`rounded px-1.5 text-[10px] font-semibold leading-[18px] ${
                summary.hasScript ? TONE_CHIP.done : TONE_CHIP.idle
              }`}
            >
              {t("blueprint.stageScript")}
            </span>
            <span
              className={`rounded px-1.5 text-[10px] font-semibold leading-[18px] ${
                summary.videoReady > 0
                  ? summary.videoReady === summary.videoTotal
                    ? TONE_CHIP.done
                    : TONE_CHIP.run
                  : TONE_CHIP.idle
              }`}
            >
              {t("blueprint.stageVideo", {
                ready: summary.videoReady,
                total: summary.videoTotal,
              })}
            </span>
            <span
              className={`rounded px-1.5 text-[10px] font-semibold leading-[18px] ${
                summary.renderReady ? TONE_CHIP.done : TONE_CHIP.idle
              }`}
            >
              {t("blueprint.stageRender")}
            </span>
          </div>
        </div>

        <EntityGroup
          label={t("blueprint.entityKinds.character")}
          entities={characters}
          onOpen={onOpenVisualEntity}
        />
        <EntityGroup
          label={t("blueprint.entityKinds.prop")}
          entities={props}
          onOpen={onOpenVisualEntity}
        />
        <EntityGroup
          label={t("blueprint.entityKinds.scene")}
          entities={scenes}
          onOpen={onOpenVisualEntity}
        />
      </div>
    </aside>
  );
}
