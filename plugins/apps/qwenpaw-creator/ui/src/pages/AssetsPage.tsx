import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Button, Input, message, Modal, Select, Tabs } from "antd";
import i18n from "@/i18n";
import {
  Box,
  Clapperboard,
  FileText,
  Film,
  Image as ImageIcon,
  Link2,
  Mic,
  Music2,
  Paperclip,
  Search,
  SquarePen,
  Upload,
} from "lucide-react";
import { MenuUnfoldOutlined } from "@ant-design/icons";
import { RegeneratePill } from "@/components/workbench/PromptRichBlock";
import type { PromptRichToken } from "@/components/workbench/PromptRichBlock";
import PromptEditorModal, {
  type PromptRefCandidate,
} from "@/components/workbench/PromptEditorModal";
import { refImageThumbUrl } from "@/components/workbench/referenceThumbs";
import {
  createCharacterVoice,
  getArtifactVersionMediaUrl,
  getAssetVersionMediaUrl,
  getVoiceCapabilities,
  ingestAssetFile,
  ingestAssetValue,
  type VoiceCapabilities,
} from "@/api/creator";
import { dispatchWorkGraphNode } from "@/api/creator/workGraph";
import type {
  ArtifactVersionDocument,
  CharacterVoiceDocument,
  ProjectDocument,
  SourceAssetVersionDocument,
  TaskView,
  VisualEntityDocument,
  VisualCastLineupDocument,
  VisualVariantDocument,
} from "@/contracts/creator";
import { navigate, useParams, useSearchParams } from "@/routing/navigation";
import {
  useReviewFieldFocus,
  useReviewMediaFocus,
} from "@/routing/reviewFocus";
import { useCreatorInteractionStore } from "@/store/creatorInteractionStore";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";
import { useCreatorTaskViewStore } from "@/store/creatorTaskViewStore";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import type { ProjectEditOperation } from "@/store/projectSnapshotStore";
import { useTimelineStore } from "@/store/timelineStore";
import { useNarrowWorkspace, useDetailRail } from "@/lib/useNarrowWorkspace";
import AssetMediaPreview from "@/components/assets/AssetMediaPreview";
import DocumentUnderstanding from "@/components/assets/DocumentUnderstanding";
import SourceCacheGate from "@/components/creator/SourceCacheGate";
import { useSourceCache } from "@/lib/sourceCache";
import PageLoadError from "@/components/PageLoadError";
import PageSkeleton from "@/components/PageSkeleton";
import { selectPrimaryTimeline } from "@/selectors/timelineElementSelectors";
import { isVoiceOnlyVisualEntity } from "@/selectors/blueprintSelectors";
import { visualVariantLabel } from "@/lib/visualVariants";
import { useTranslation } from "react-i18next";

type FilterKey = "all" | "character" | "scene" | "prop" | "video" | "audio";

/** 来源下拉 (design 84:78645): 视觉设定 / 生成产物 / 上传素材. */
type OriginKey = "any" | "visual" | "artifact" | "source";
type AssetItem = {
  id: string;
  ref: string;
  kind: "source" | "artifact" | "visual";
  name: string;
  cardName?: string;
  description: string;
  mediaKind: string;
  mediaType: string;
  previewUrl?: string;
  createdAt?: string;
  stale?: boolean;
  durationSeconds?: number | null;
  checksum?: string;
  ownerRef?: string;
  entityId?: string;
  variantId?: string;
  variantOrder?: number;
  variantLabel?: string;
  variantState?: "active" | "history" | "unselected";
  /** All versions of the owning slot — one card, switchable preview. */
  versions?: AssetVersionOption[];
  provenanceRefs: string[];
  metadata: Record<string, unknown>;
  raw:
    | SourceAssetVersionDocument
    | ArtifactVersionDocument
    | VisualEntityDocument
    | VisualCastLineupDocument;
};

type AssetVersionOption = {
  id: string;
  name: string;
  stale?: boolean;
  selected: boolean;
  mediaKind: string;
  mediaType: string;
  previewUrl?: string;
  createdAt?: string;
  raw: ArtifactVersionDocument;
};

type AssetItemGroup = {
  key: string;
  label: string | null;
  badge?: string;
  countLabel?: string;
  /** Ownership groups link back to the blueprint (plan §4.7). */
  blueprint?: boolean;
  items: AssetItem[];
};

const FILTERS: Array<{ key: FilterKey; labelKey: string }> = [
  { key: "all", labelKey: "assets.all" },
  { key: "character", labelKey: "assets.character" },
  { key: "scene", labelKey: "assets.scene" },
  { key: "prop", labelKey: "assets.prop" },
  { key: "video", labelKey: "assets.video" },
  { key: "audio", labelKey: "assets.audio" },
];

const ORIGINS: Array<{ key: OriginKey; labelKey: string }> = [
  { key: "any", labelKey: "assets.originAll" },
  { key: "visual", labelKey: "assets.visual" },
  { key: "artifact", labelKey: "assets.artifact" },
  { key: "source", labelKey: "assets.source" },
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

// Source version ids whose long-source graph memory is built FOR THE
// CURRENTLY SELECTED VERSION. A SUCCEEDED source_memory_build task alone
// is not enough: after a same-logical-asset version replacement the old
// task must not decorate the new, unbuilt version. The badge therefore
// requires the ProjectSource's current intelligence version to point at
// this exact selected version with a matching source checksum (the
// backend memoryRef itself is checksum-gated on load).
function memoryBuiltVersionIds(
  project: ProjectDocument,
  tasks: TaskView[],
): Set<string> {
  const builtLogicalIds = new Set<string>();
  for (const task of tasks) {
    if (task.kind !== "source_memory_build") continue;
    if (task.status !== "SUCCEEDED") continue;
    if (!task.targetRef.startsWith("asset:")) continue;
    builtLogicalIds.add(task.targetRef.slice("asset:".length));
  }
  const badged = new Set<string>();
  if (!builtLogicalIds.size) return badged;
  for (const source of Object.values(project.sources.sources.items)) {
    if (!builtLogicalIds.has(source.logical_asset_id)) continue;
    const intelligenceId = source.current_intelligence_version_id;
    if (!intelligenceId) continue;
    const intelligence =
      project.assets.intelligence_versions_by_id[intelligenceId];
    if (!intelligence) continue;
    const versionId = intelligence.source_asset_version_id;
    if (versionId !== source.selected_asset_version_id) continue;
    const version = project.assets.source_versions_by_id[versionId];
    if (!version) continue;
    if (version.checksum !== intelligence.source_checksum) continue;
    badged.add(versionId);
  }
  return badged;
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

// Keep one semantic card per Variant and underlying content. The same image
// can legitimately be attached to two legacy Variants; keep both assignments
// visible instead of hiding the data-quality issue.
function dedupeByChecksum(items: AssetItem[]): AssetItem[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    if (!item.checksum) return true;
    const key = `${item.variantId ?? ""}:${item.checksum}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function visualVariantForVersion(
  project: ProjectDocument,
  versionId: string,
): {
  entity: VisualEntityDocument;
  variant: VisualVariantDocument;
} | null {
  const artifact = project.assets.artifact_versions_by_id[versionId];
  const metadataVariantId =
    typeof artifact?.metadata.variantId === "string"
      ? artifact.metadata.variantId
      : null;
  const ownerEntityId = (artifact?.owner_ref ?? "").replace(
    /^(?:visual-entity|asset):/,
    "",
  );
  const ownerEntity = project.visual.entities.items[ownerEntityId];
  if (
    ownerEntity &&
    metadataVariantId &&
    ownerEntity.variants.items[metadataVariantId]
  ) {
    return {
      entity: ownerEntity,
      variant: ownerEntity.variants.items[metadataVariantId],
    };
  }
  for (const entityId of project.visual.entities.order) {
    const entity = project.visual.entities.items[entityId];
    if (!entity) continue;
    for (const variantId of entity.variants.order) {
      const variant = entity.variants.items[variantId];
      if (variant?.generated_artifact_version_ids.includes(versionId)) {
        return { entity, variant };
      }
    }
  }
  return null;
}

function visualVariantCardName(variant: VisualVariantDocument): string {
  const variantName = variant.variant_id
    .replace(/^(?:visual-variant:|variant:|var:)/, "")
    .split(":")
    .at(-1)
    ?.trim();
  if (!variantName) return visualVariantLabel(variant, 36);
  if (variantName.toLocaleLowerCase() === "default")
    return i18n.t("assets.defaultLook");
  return variantName
    .split(/[-_]+/)
    .filter(Boolean)
    .map((word) => {
      if (/^(?:nba|wnba|nfl|mlb|nhl|2d|3d)$/i.test(word))
        return word.toLocaleUpperCase();
      return `${word.charAt(0).toLocaleUpperCase()}${word.slice(1)}`;
    })
    .join(" ");
}

function visualSettingCardName(
  entity: VisualEntityDocument,
  variant: VisualVariantDocument | null,
): string {
  if (entity.kind !== "character" || !variant) return entity.name;
  return visualVariantCardName(variant);
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
          i18n.t("assets.userImportedSource"),
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
  // Slot-first artifact cards: every ArtifactSlot occupies ONE position and
  // its versions switch inline (no flat tiling of stale history). Scripts
  // are text workproducts reviewed on the blueprint, not library assets.
  const slottedVersionIds = new Set<string>();
  const slotArtifacts = Object.values(project.assets.artifact_slots_by_id)
    .filter(
      (slot) =>
        slot.kind !== "timeline_script" &&
        slot.kind !== "research_report" &&
        slot.version_ids.length > 0,
    )
    .flatMap((slot): AssetItem[] => {
      for (const versionId of slot.version_ids) {
        slottedVersionIds.add(versionId);
      }
      const versions = slot.version_ids
        .map((versionId) => project.assets.artifact_versions_by_id[versionId])
        .filter((version): version is ArtifactVersionDocument =>
          Boolean(version),
        )
        .map((version): AssetVersionOption => {
          const media = artifactMedia(project, version);
          return {
            id: version.version_id,
            name: version.name || version.version_id,
            stale: version.stale,
            selected: version.version_id === slot.selected_version_id,
            mediaKind: media.kind,
            mediaType: media.type,
            previewUrl: ["image", "video", "audio"].includes(media.kind)
              ? getArtifactVersionMediaUrl(version.version_id)
              : undefined,
            createdAt: version.created_at,
            raw: version,
          };
        });
      if (!versions.length) return [];
      const active =
        versions.find((version) => version.selected) ??
        versions[versions.length - 1];
      const artifact = active.raw;
      const visualVariant = visualVariantForVersion(project, active.id);
      return [
        {
          id: slot.slot_id,
          ref: `artifact-version:${active.id}`,
          kind: "artifact",
          name: active.name,
          description:
            versions.length > 1
              ? `${slot.kind} · ${i18n.t("assets.versionCount", {
                  count: versions.length,
                })}`
              : `${slot.kind} · generation ${artifact.based_on_generation}`,
          mediaKind: active.mediaKind,
          mediaType: active.mediaType,
          previewUrl: active.previewUrl,
          createdAt: active.createdAt,
          stale: artifact.stale,
          durationSeconds: artifact.duration_seconds,
          checksum: artifact.checksum,
          ownerRef: artifact.owner_ref,
          entityId: visualVariant?.entity.entity_id,
          variantId: visualVariant?.variant.variant_id,
          versions: versions.length > 1 ? versions : undefined,
          provenanceRefs: artifact.provenance_refs,
          metadata: artifact.metadata,
          raw: artifact,
        },
      ];
    });
  const scriptVersionIds = new Set(
    Object.values(project.assets.artifact_slots_by_id)
      .filter(
        (slot) =>
          slot.kind === "timeline_script" || slot.kind === "research_report",
      )
      .flatMap((slot) => slot.version_ids),
  );
  const artifacts = Object.values(project.assets.artifact_versions_by_id)
    .filter(
      (artifact) =>
        !slottedVersionIds.has(artifact.version_id) &&
        !scriptVersionIds.has(artifact.version_id),
    )
    .map((artifact): AssetItem => {
      const media = artifactMedia(project, artifact);
      const visualVariant = visualVariantForVersion(
        project,
        artifact.version_id,
      );
      return {
        id: artifact.version_id,
        ref: `artifact-version:${artifact.version_id}`,
        kind: "artifact",
        name: artifact.name || artifact.version_id,
        description: artifact.stale
          ? artifact.stale_reason || i18n.t("assets.staleDescription")
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
        entityId: visualVariant?.entity.entity_id,
        variantId: visualVariant?.variant.variant_id,
        variantLabel: visualVariant
          ? `${visualVariant.entity.name} · ${visualVariantCardName(
              visualVariant.variant,
            )}`
          : undefined,
        variantState: visualVariant
          ? visualVariant.variant.selected_artifact_version_id ===
            artifact.version_id
            ? "active"
            : "history"
          : undefined,
        provenanceRefs: artifact.provenance_refs,
        metadata: artifact.metadata,
        raw: artifact,
      };
    });
  const visuals = project.visual.entities.order.flatMap(
    (entityId): AssetItem[] => {
      const entity = project.visual.entities.items[entityId];
      if (!entity) return [];
      const variants = entity.variants.order.length
        ? entity.variants.order
            .map((variantId) => entity.variants.items[variantId])
            .filter((variant): variant is VisualVariantDocument =>
              Boolean(variant),
            )
        : [null];
      return variants.map((variant, variantIndex): AssetItem => {
        const cardName = visualSettingCardName(entity, variant);
        const selectedVersionId =
          variant?.selected_artifact_version_id ??
          (!variant ? entity.selected_artifact_version_id : null);
        const artifact = selectedVersionId
          ? project.assets.artifact_versions_by_id[selectedVersionId]
          : undefined;
        const media = artifact
          ? artifactMedia(project, artifact)
          : { kind: "image", type: "" };
        return {
          id: variant
            ? `${entity.entity_id}@${variant.variant_id}`
            : entity.entity_id,
          ref: variant
            ? `visual-variant:${entity.entity_id}@${variant.variant_id}`
            : `visual-entity:${entity.entity_id}`,
          kind: "visual",
          name: entity.name,
          cardName,
          description:
            variant?.requirements ||
            entity.description ||
            entity.continuity ||
            `${entity.kind} ${i18n.t("assets.visualSettingSuffix")}`,
          mediaKind: media.kind,
          mediaType: media.type,
          previewUrl: artifact
            ? getArtifactVersionMediaUrl(artifact.version_id)
            : undefined,
          stale: artifact?.stale,
          checksum: artifact?.checksum,
          ownerRef: artifact?.owner_ref,
          entityId: entity.entity_id,
          variantId: variant?.variant_id,
          variantOrder: variantIndex,
          variantLabel: variant ? visualVariantCardName(variant) : undefined,
          variantState: variant
            ? artifact
              ? "active"
              : "unselected"
            : undefined,
          // Surface the references the generation model actually saw — e.g. the
          // web-grounding photo a scene design was composed from. The artifact
          // is the ground truth; the variant's reference_asset_version_ids is
          // the configured intent, which the provenance_refs mirror at run time.
          provenanceRefs: artifact?.provenance_refs ?? [],
          metadata: {
            kind: entity.kind,
            continuity: entity.continuity,
            variants: entity.variants.order.length,
            variant_id: variant?.variant_id,
            generated_artifact_version_ids:
              variant?.generated_artifact_version_ids ?? [],
            selected_artifact_version_id: selectedVersionId,
          },
          raw: entity,
        };
      });
    },
  );
  // Cast lineups are visual assets too: the group anchor that locks
  // relative scale and style across characters surfaces alongside the
  // per-entity cards so its generation state is never invisible.
  const lineups = (project.visual.cast_lineups?.order ?? []).flatMap(
    (lineupId): AssetItem[] => {
      const lineup = project.visual.cast_lineups?.items[lineupId];
      if (!lineup) return [];
      const selectedVersionId = lineup.selected_artifact_version_id;
      const artifact = selectedVersionId
        ? project.assets.artifact_versions_by_id[selectedVersionId]
        : undefined;
      const media = artifact
        ? artifactMedia(project, artifact)
        : { kind: "image", type: "" };
      const characterNames = lineup.character_refs.map(
        (ref) => project.visual.entities.items[ref]?.name || ref,
      );
      return [
        {
          id: lineupId,
          ref: `lineup:${lineupId}`,
          kind: "visual",
          name: lineup.name,
          cardName: `${lineup.name}${i18n.t("assets.lineupCardSuffix")}`,
          description:
            lineup.relative_notes ||
            lineup.description ||
            `${i18n.t("assets.lineupDescPrefix")}${characterNames.join("、")}`,
          mediaKind: media.kind,
          mediaType: media.type,
          previewUrl: artifact
            ? getArtifactVersionMediaUrl(artifact.version_id)
            : undefined,
          stale: artifact?.stale,
          checksum: artifact?.checksum,
          ownerRef: artifact?.owner_ref,
          variantState: artifact ? "active" : "unselected",
          provenanceRefs: artifact?.provenance_refs ?? [],
          metadata: {
            kind: "cast_lineup",
            character_refs: lineup.character_refs,
            relative_notes: lineup.relative_notes,
            generated_artifact_version_ids:
              lineup.generated_artifact_version_ids,
            selected_artifact_version_id: selectedVersionId,
          },
          raw: lineup,
        },
      ];
    },
  );
  return dedupeByChecksum([
    ...lineups,
    ...visuals,
    ...sources,
    ...slotArtifacts,
    ...artifacts,
  ]).sort((left, right) => {
    return (
      (right.createdAt || "").localeCompare(left.createdAt || "") ||
      left.name.localeCompare(right.name)
    );
  });
}

function visualItemGroups(
  project: ProjectDocument,
  items: AssetItem[],
): AssetItemGroup[] {
  const itemsByEntity = new Map<string, AssetItem[]>();
  const lineupItems: AssetItem[] = [];
  const unassigned: AssetItem[] = [];
  for (const item of items) {
    if (item.ref.startsWith("lineup:")) {
      lineupItems.push(item);
      continue;
    }
    if (!item.entityId) {
      unassigned.push(item);
      continue;
    }
    const entityItems = itemsByEntity.get(item.entityId) ?? [];
    entityItems.push(item);
    itemsByEntity.set(item.entityId, entityItems);
  }

  const characterGroups: AssetItemGroup[] = [];
  const voiceGroups: AssetItemGroup[] = [];
  const sceneItems: AssetItem[] = [];
  const propItems: AssetItem[] = [];
  for (const entityId of project.visual.entities.order) {
    const entity = project.visual.entities.items[entityId];
    const entityItems = itemsByEntity.get(entityId);
    if (!entity || !entityItems?.length) continue;
    entityItems.sort(
      (left, right) =>
        (left.variantOrder ?? 0) - (right.variantOrder ?? 0) ||
        (left.cardName || left.name).localeCompare(
          right.cardName || right.name,
        ),
    );
    if (entity.kind === "character") {
      // 旁白/画外音: an enrolled voice with no visual form is not a 角色 card.
      if (isVoiceOnlyVisualEntity(entity)) {
        voiceGroups.push({
          key: `voice:${entityId}`,
          label: entity.name,
          badge: i18n.t("assets.voiceBadge"),
          countLabel: i18n.t("assets.voiceOnlyRole"),
          items: entityItems,
        });
        continue;
      }
      const requiredCount = entity.required_variant_ids.length;
      const definedCount = entity.variants.order.length;
      characterGroups.push({
        key: `character:${entityId}`,
        label: entity.name,
        badge: i18n.t("assets.character"),
        countLabel:
          requiredCount > 0
            ? definedCount === requiredCount
              ? i18n.t("assets.charactersCount", { count: definedCount })
              : i18n.t("assets.charactersOfCount", {
                  defined: definedCount,
                  required: requiredCount,
                })
            : i18n.t("assets.oneSetting"),
        items: entityItems,
      });
    } else if (entity.kind === "scene") {
      sceneItems.push(...entityItems);
    } else {
      propItems.push(...entityItems);
    }
  }

  return [
    ...characterGroups,
    ...voiceGroups,
    ...(sceneItems.length
      ? [
          {
            key: "visual-scenes",
            label: i18n.t("assets.scene"),
            countLabel: i18n.t("assets.sceneSettings", {
              count: sceneItems.length,
            }),
            items: sceneItems,
          },
        ]
      : []),
    ...(propItems.length
      ? [
          {
            key: "visual-props",
            label: i18n.t("assets.prop"),
            countLabel: i18n.t("assets.propSettings", {
              count: propItems.length,
            }),
            items: propItems,
          },
        ]
      : []),
    ...(lineupItems.length
      ? [
          {
            key: "visual-lineups",
            label: i18n.t("assets.lineupGroup"),
            countLabel: i18n.t("assets.lineupGroupCount", {
              count: lineupItems.length,
            }),
            items: lineupItems,
          },
        ]
      : []),
    ...(unassigned.length
      ? [
          {
            key: "visual-other",
            label: i18n.t("assets.otherSettings"),
            countLabel: i18n.t("assets.otherSettingsCount", {
              count: unassigned.length,
            }),
            items: unassigned,
          },
        ]
      : []),
  ];
}

/**
 * Ownership projection (plan §4.7): scripts / visual development (per
 * entity) / research & understanding / shots & final cuts / source assets.
 */

/**
 * Intelligence version bound to one exact SourceAssetVersion. Repeated
 * analyses keep every record, so the Source's current pointer wins and
 * older versions fall back to their newest analysis by created_at.
 */
function intelligenceVersionForSource(
  project: ProjectDocument,
  version: SourceAssetVersionDocument,
): string | null {
  const records = Object.values(
    project.assets.intelligence_versions_by_id,
  ).filter((record) => record.source_asset_version_id === version.version_id);
  if (!records.length) return null;
  const current = Object.values(project.sources.sources.items).find(
    (source) => source.logical_asset_id === version.logical_asset_id,
  )?.current_intelligence_version_id;
  const pinned = records.find(
    (record) => record.intelligence_version_id === current,
  );
  if (pinned) return pinned.intelligence_version_id;
  return [...records].sort((left, right) =>
    right.created_at.localeCompare(left.created_at),
  )[0].intelligence_version_id;
}

function kindLabel(item: AssetItem, t: (key: string) => string): string {
  if (item.kind === "source")
    return item.mediaKind === "document"
      ? t("assets.sourceDocumentLabel")
      : t("assets.sourceLabel");
  if (item.kind === "artifact") return t("assets.artifactLabel");
  if (item.ref.startsWith("lineup:")) return t("assets.lineupLabel");
  const entity = item.raw as VisualEntityDocument;
  return entity.kind === "character"
    ? isVoiceOnlyVisualEntity(entity)
      ? t("assets.voiceBadge")
      : t("assets.character")
    : entity.kind === "scene"
    ? t("assets.scene")
    : t("assets.prop");
}

/** Enrolled voice binding of a character visual entity, if any. */
function characterVoice(item: AssetItem): CharacterVoiceDocument | null {
  if (item.kind !== "visual") return null;
  const entity = item.raw as VisualEntityDocument;
  if (entity.kind !== "character") return null;
  return entity.voice ?? null;
}

function mediaIcon(kind: string) {
  if (kind === "video") return Film;
  if (kind === "audio") return Music2;
  if (kind === "image") return ImageIcon;
  if (kind === "text" || kind === "document") return FileText;
  return Box;
}

/** Resolve a provenance/ref string to a previewable thumbnail + label. */
function resolveProvenanceRef(
  project: ProjectDocument,
  ref: string,
): { name: string; url: string; kind: "image" | "video"; ref: string } | null {
  if (ref.startsWith("asset-version:")) {
    const id = ref.slice("asset-version:".length);
    const version = project.assets.source_versions_by_id[id];
    if (!version) return null;
    return {
      name: version.name || id,
      url: getAssetVersionMediaUrl(id),
      kind: version.media_kind === "video" ? "video" : "image",
      ref,
    };
  }
  if (ref.startsWith("artifact-version:")) {
    const id = ref.slice("artifact-version:".length);
    const version = project.assets.artifact_versions_by_id[id];
    if (!version) return null;
    const media = artifactMedia(project, version);
    if (!media) return null;
    return {
      name: version.name || id,
      url: getArtifactVersionMediaUrl(id),
      kind: media.kind === "video" ? "video" : "image",
      ref,
    };
  }
  if (ref.startsWith("visual-entity:")) {
    const entityId = ref.slice("visual-entity:".length);
    const entity = project.visual.entities.items[entityId];
    // A multi-Variant entity has no safe implicit selection. Legacy entity
    // provenance therefore stays unresolved until it names visual-variant:.
    const versionId = entity
      ? entity.variants.order.length === 1
        ? entity.variants.items[entity.variants.order[0]]
            ?.selected_artifact_version_id ?? null
        : entity.variants.order.length === 0
        ? entity.selected_artifact_version_id
        : null
      : null;
    const version = versionId
      ? project.assets.artifact_versions_by_id[versionId]
      : undefined;
    if (!version) return null;
    return {
      name: entity?.name || entityId,
      url: getArtifactVersionMediaUrl(versionId!),
      kind: "image",
      ref,
    };
  }
  if (ref.startsWith("visual-variant:")) {
    const identity = ref.slice("visual-variant:".length);
    const separator = identity.lastIndexOf("@");
    if (separator < 1) return null;
    const entityId = identity.slice(0, separator);
    const variantId = identity.slice(separator + 1);
    const entity = project.visual.entities.items[entityId];
    const versionId =
      entity?.variants.items[variantId]?.selected_artifact_version_id ?? null;
    if (!entity || !versionId) return null;
    return {
      name: `${entity.name} / ${visualVariantLabel(
        entity.variants.items[variantId],
      )}`,
      url: getArtifactVersionMediaUrl(versionId),
      kind: "image",
      ref,
    };
  }
  return null;
}

export interface PromptTarget {
  pointer: string;
  value: string;
  label: string;
  /** [Image N] references insertable in the fullscreen editor. */
  tokens?: PromptRichToken[];
  /** Where newly picked references persist (visual variants only). */
  referenceBinding?: {
    base: string;
    assetIds: string[];
    artifactIds: string[];
  };
  /** Project assets addable as brand-new references. */
  candidates?: PromptRefCandidate[];
}

function referenceVersionDisplayName(
  project: ProjectDocument,
  versionId: string,
): string {
  return (
    project.assets.artifact_versions_by_id[versionId]?.name ??
    project.assets.source_versions_by_id[versionId]?.name ??
    versionId
  );
}

/** Variant reference images become editor tokens, numbered by their order. */
function variantReferenceTokens(
  project: ProjectDocument,
  variant: VisualVariantDocument,
): PromptRichToken[] {
  const versionIds = [
    ...variant.reference_asset_version_ids,
    ...variant.reference_artifact_version_ids,
  ];
  return versionIds.map((versionId, position) => ({
    index: position + 1,
    name: referenceVersionDisplayName(project, versionId),
    kind: "artifact" as const,
    thumbUrl: refImageThumbUrl(
      project,
      null,
      project.assets.artifact_versions_by_id[versionId]
        ? `artifact-version:${versionId}`
        : `asset-version:${versionId}`,
    ),
  }));
}

/** Project image assets not yet referenced by this variant — pickable in the
 *  editor as brand-new [Image N] references. */
function variantReferenceCandidates(
  project: ProjectDocument,
  variant: VisualVariantDocument,
): PromptRefCandidate[] {
  const taken = new Set([
    ...variant.reference_asset_version_ids,
    ...variant.reference_artifact_version_ids,
    ...variant.generated_artifact_version_ids,
  ]);
  // Artifact versions produced by a visual entity's variants carry that
  // entity's kind so the condensed asset-library picker can offer real
  // category tabs; loose versions stay "material".
  const kindByVersionId = new Map<string, PromptRefCandidate["kind"]>();
  for (const entityId of project.visual.entities.order) {
    const entity = project.visual.entities.items[entityId];
    if (!entity) continue;
    for (const variantId of entity.variants.order) {
      for (const versionId of entity.variants.items[variantId]
        ?.generated_artifact_version_ids ?? []) {
        kindByVersionId.set(
          versionId,
          entity.kind as PromptRefCandidate["kind"],
        );
      }
    }
  }
  const sources = Object.values(project.assets.source_versions_by_id)
    .filter(
      (version) =>
        version.media_kind === "image" && !taken.has(version.version_id),
    )
    .map((version) => ({
      id: version.version_id,
      name: version.name || version.version_id,
      kind: "material" as const,
      thumbUrl: refImageThumbUrl(
        project,
        null,
        `asset-version:${version.version_id}`,
      ),
    }));
  const artifacts = Object.values(project.assets.artifact_versions_by_id)
    .filter((version) => {
      if (taken.has(version.version_id)) return false;
      const mediaType =
        project.assets.files_by_id[version.file_id]?.media_type ?? "";
      return mediaType.startsWith("image/");
    })
    .map((version) => ({
      id: version.version_id,
      name: version.name || version.version_id,
      kind: kindByVersionId.get(version.version_id) ?? ("material" as const),
      thumbUrl: refImageThumbUrl(
        project,
        null,
        `artifact-version:${version.version_id}`,
      ),
    }));
  return [...sources, ...artifacts];
}

/** Work-graph node the prompt regenerates through — manual dispatch, no agent. */
export function dispatchNodeIdForPrompt(pointer: string): string | null {
  let match =
    /^\/visual\/entities\/items\/([^/]+)\/variants\/items\/([^/]+)\/prompt$/.exec(
      pointer,
    );
  if (match) return `visual:${match[1]}:${match[2]}`;
  match = /^\/visual\/cast_lineups\/items\/([^/]+)\/relative_notes$/.exec(
    pointer,
  );
  if (match) return `lineup:${match[1]}`;
  match = /\/elements_by_id\/([^/]+)\/creation\/video_prompt$/.exec(pointer);
  if (match) return `video:${match[1]}`;
  match = /\/elements_by_id\/([^/]+)\/creation\/storyboard_prompt$/.exec(
    pointer,
  );
  if (match) return `storyboard:${match[1]}`;
  return null;
}

export function visualEntityPromptTarget(
  project: ProjectDocument,
  entity: VisualEntityDocument,
  versionId: string | null,
  requestedVariantId?: string,
): PromptTarget | null {
  const variantId =
    (requestedVariantId &&
      entity.variants.items[requestedVariantId] &&
      requestedVariantId) ||
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
    label: i18n.t("assets.generationPrompt"),
    tokens: variantReferenceTokens(project, variant),
    candidates: variantReferenceCandidates(project, variant),
    referenceBinding: {
      base: `/visual/entities/items/${entity.entity_id}/variants/items/${variant.variant_id}`,
      assetIds: variant.reference_asset_version_ids,
      artifactIds: variant.reference_artifact_version_ids,
    },
  };
}

function generationPromptTarget(
  project: ProjectDocument,
  selected: AssetItem,
): PromptTarget | null {
  if (selected.ref.startsWith("lineup:")) {
    // Lineup cards reuse kind "visual" for filtering, but their raw is a
    // VisualCastLineupDocument — no variants tree to walk. Their editable
    // "prompt" is the relative_notes the lineup image is drawn from.
    const lineup = selected.raw as VisualCastLineupDocument;
    return {
      pointer: `/visual/cast_lineups/items/${lineup.lineup_id}/relative_notes`,
      value: lineup.relative_notes,
      label: i18n.t("assets.lineupRelativeNotes"),
    };
  }
  if (selected.kind === "visual") {
    const entity = selected.raw as VisualEntityDocument;
    return visualEntityPromptTarget(
      project,
      entity,
      selected.variantId
        ? entity.variants.items[selected.variantId]
            ?.selected_artifact_version_id ?? null
        : entity.selected_artifact_version_id,
      selected.variantId,
    );
  }
  if (selected.kind !== "artifact") return null;
  const ownerRef = selected.ownerRef ?? "";
  if (ownerRef.startsWith("visual-entity:") || ownerRef.startsWith("asset:")) {
    const visualVariant = visualVariantForVersion(project, selected.id);
    const entity =
      visualVariant?.entity ??
      project.visual.entities.items[
        ownerRef.replace(/^(visual-entity:|asset:)/, "")
      ];
    return entity
      ? visualEntityPromptTarget(
          project,
          entity,
          selected.id,
          visualVariant?.variant.variant_id,
        )
      : null;
  }
  if (ownerRef.startsWith("element:")) {
    const elementId = ownerRef.slice("element:".length);
    const activeTid = useTimelineStore.getState().activeTimelineId;
    const timeline = selectPrimaryTimeline(project, activeTid);
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
            label: i18n.t("assets.videoGenPrompt"),
          }
        : {
            pointer: `${base}/storyboard_prompt`,
            value: element.creation.storyboard_prompt,
            label: i18n.t("assets.storyboardGenPrompt"),
          };
    }
    if (element.creation.type === "overlay") {
      return {
        pointer: `${base}/prompt`,
        value: element.creation.prompt,
        label: i18n.t("assets.generationPrompt"),
      };
    }
  }
  return null;
}

/** Prompt block: read-only text with 编辑 / 重新生成. 编辑 opens the same
 *  fullscreen token editor as the R2V workbench (reference images insert as
 *  pills); 重新生成 dispatches the matching work-graph node directly. */
/** Build the patch ops for a prompt edit: text replace + newly picked
 *  reference ids appended to the variant's reference bindings. */
export function buildPromptSaveOperations(
  project: ProjectDocument,
  target: PromptTarget,
  next: string,
  addedReferenceIds: string[],
): ProjectEditOperation[] {
  const operations: ProjectEditOperation[] = [];
  if (next !== target.value) {
    operations.push({
      op: "replace",
      path: target.pointer,
      before: target.value,
      value: next,
    });
  }
  const binding = target.referenceBinding;
  if (binding && addedReferenceIds.length > 0) {
    const addedAssets = addedReferenceIds.filter(
      (versionId) => project.assets.source_versions_by_id[versionId],
    );
    const addedArtifacts = addedReferenceIds.filter(
      (versionId) => !addedAssets.includes(versionId),
    );
    if (addedAssets.length) {
      operations.push({
        op: "replace",
        path: `${binding.base}/reference_asset_version_ids`,
        before: binding.assetIds,
        value: [...binding.assetIds, ...addedAssets],
      });
    }
    if (addedArtifacts.length) {
      operations.push({
        op: "replace",
        path: `${binding.base}/reference_artifact_version_ids`,
        before: binding.artifactIds,
        value: [...binding.artifactIds, ...addedArtifacts],
      });
    }
  }
  return operations;
}

export function GenerationPromptEditor({
  target,
  onSave,
  onRegenerate,
  regenerateLabel,
  saving,
}: {
  target: PromptTarget;
  onSave: (
    target: PromptTarget,
    next: string,
    addedReferenceIds: string[],
  ) => Promise<void>;
  onRegenerate?: () => void;
  regenerateLabel: string;
  saving: boolean;
}) {
  const { t } = useTranslation();
  const [editOpen, setEditOpen] = useState(false);
  const softPill =
    "inline-flex h-10 shrink-0 cursor-pointer select-none items-center gap-1 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-4 text-sm font-medium leading-6 text-[var(--color-text-primary)] transition-colors hover:border-[var(--color-border-strong)] disabled:cursor-not-allowed disabled:opacity-50";
  return (
    <div
      data-creator-path={target.pointer}
      data-creator-field-label={target.label}
      className="space-y-1.5"
    >
      <span className="block text-sm text-[var(--color-text-primary)]">
        {target.label}
      </span>
      <div className="space-y-2 rounded-[10px] border border-[var(--color-border)] bg-[var(--color-bg-secondary)]/50 p-3">
        <p className="max-h-[135px] overflow-y-auto whitespace-pre-wrap text-xs leading-[1.6] text-[var(--color-text-primary)]">
          {target.value || t("assets.promptPlaceholder")}
        </p>
        <div className="flex justify-end gap-3">
          <button
            type="button"
            data-prompt-edit={target.pointer}
            disabled={saving}
            className={softPill}
            onClick={() => setEditOpen(true)}
          >
            <SquarePen className="h-5 w-5" />
            {t("common.edit")}
          </button>
          {onRegenerate && (
            <span data-asset-regenerate>
              <RegeneratePill
                field={target.pointer}
                label={regenerateLabel}
                disabled={saving}
                onClick={onRegenerate}
              />
            </span>
          )}
        </div>
      </div>
      <PromptEditorModal
        open={editOpen}
        label={target.label}
        initialValue={target.value}
        tokens={target.tokens ?? []}
        candidates={target.candidates ?? []}
        disabled={saving}
        onCancel={() => setEditOpen(false)}
        onDone={(next, addedReferenceIds) => {
          setEditOpen(false);
          if (next !== target.value || addedReferenceIds.length > 0)
            void onSave(target, next, addedReferenceIds);
        }}
      />
    </div>
  );
}

/** Voice generation dialog: design prompt (when the TTS model supports it)
 *  and/or an audio sample; submits straight to the enrollment executor. */
function VoiceGenerationModal({
  open,
  projectId,
  entity,
  onClose,
}: {
  open: boolean;
  projectId: string;
  entity: VisualEntityDocument | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const project = useProjectSnapshotStore((state) =>
    state.projectId === projectId ? state.project : null,
  );
  const [capabilities, setCapabilities] = useState<VoiceCapabilities | null>(
    null,
  );
  const [voicePrompt, setVoicePrompt] = useState("");
  const [sampleId, setSampleId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!open || !entity) return;
    setVoicePrompt(entity.voice?.voice_prompt || entity.description || "");
    setSampleId(entity.voice?.sample_source_version_id ?? null);
    setCapabilities(null);
    void getVoiceCapabilities(projectId)
      .then(setCapabilities)
      .catch(() => setCapabilities(null));
    // Sampled per opening.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  const supportsDesign = capabilities?.supportsDesign ?? false;
  const audioOptions = project
    ? Object.values(project.assets.source_versions_by_id)
        .filter((version) => version.media_kind === "audio")
        .map((version) => ({
          value: version.version_id,
          label: version.name || version.version_id,
        }))
    : [];
  const submit = async () => {
    if (!entity) return;
    const prompt = supportsDesign ? voicePrompt.trim() : "";
    if (!prompt && !sampleId) {
      message.error(t("assets.voiceNeedInput"));
      return;
    }
    setBusy(true);
    try {
      await createCharacterVoice(projectId, {
        characterRef: `asset:${entity.entity_id}`,
        ...(prompt ? { voicePrompt: prompt } : {}),
        ...(!prompt && sampleId ? { sampleSourceVersionId: sampleId } : {}),
        preferredName: entity.name,
      });
      message.success(t("assets.voiceDone"));
      void useProjectSnapshotStore.getState().pollOnce(projectId);
      onClose();
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open={open}
      title={t("assets.voiceModalTitle", { name: entity?.name ?? "" })}
      okText={t("assets.voiceModalConfirm")}
      cancelText={t("common.cancel")}
      confirmLoading={busy}
      onOk={() => void submit()}
      onCancel={onClose}
      destroyOnHidden
    >
      <div className="space-y-3 py-1">
        {supportsDesign && (
          <div className="space-y-1.5">
            <span className="block text-xs font-medium text-[var(--color-text-secondary)]">
              {t("assets.voicePromptLabel")}
            </span>
            <Input.TextArea
              value={voicePrompt}
              onChange={(event) => setVoicePrompt(event.target.value)}
              autoSize={{ minRows: 3, maxRows: 8 }}
              placeholder={t("assets.voicePromptPlaceholder")}
              className="!text-xs"
            />
          </div>
        )}
        <div className="space-y-1.5">
          <span className="block text-xs font-medium text-[var(--color-text-secondary)]">
            {supportsDesign
              ? t("assets.voiceSampleOptional")
              : t("assets.voiceSampleRequired")}
          </span>
          <Select
            className="!w-full"
            allowClear
            placeholder={t("assets.voiceSamplePlaceholder")}
            value={sampleId}
            options={audioOptions}
            onChange={(next) => setSampleId(next ?? null)}
          />
        </div>
      </div>
    </Modal>
  );
}

export default function AssetsPage() {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const query = useSearchParams();
  const project = useProjectSnapshotStore((state) =>
    state.projectId === id ? state.project : null,
  );
  const syncStatus = useProjectSnapshotStore((state) => state.syncStatus);
  const syncError = useProjectSnapshotStore((state) => state.syncError);
  const builtinExample = useProjectSnapshotStore((state) =>
    state.projectId === id ? state.builtinExample : false,
  );
  // Bundled examples ship trimmed clips only; the gigabyte-scale originals
  // are fetched on demand when the user wants to watch them here.
  const sourceCache = useSourceCache(id, builtinExample);
  const pollOnce = useProjectSnapshotStore((state) => state.pollOnce);
  const patchProject = useProjectSnapshotStore((state) => state.patch);
  const patching = useProjectSnapshotStore((state) => state.patching);
  const refreshTasks = useCreatorTaskViewStore((state) => state.refresh);
  const tasks = useCreatorTaskViewStore((state) => state.tasks);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [filter, setFilter] = useState<FilterKey>("all");
  const [origin, setOrigin] = useState<OriginKey>("any");
  const sidebarOpen = useAgentDockUiStore((state) => state.open);
  const setSidebarOpen = useAgentDockUiStore((state) => state.setOpen);
  const [search, setSearch] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [voiceModalEntity, setVoiceModalEntity] =
    useState<VisualEntityDocument | null>(null);
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
    const entityKindOf = (item: AssetItem): string | null => {
      // Cast lineups are character-centric visual settings.
      if (item.ref.startsWith("lineup:")) return "character";
      if (!item.entityId || !project) return null;
      return project.visual.entities.items[item.entityId]?.kind ?? null;
    };
    return allItems.filter((item) => {
      const typeMatch =
        filter === "all" ||
        (filter === "video" || filter === "audio"
          ? item.mediaKind === filter
          : item.kind === "visual" && entityKindOf(item) === filter);
      const originMatch = origin === "any" || item.kind === origin;
      const searchMatch =
        !needle ||
        `${item.name} ${item.description} ${item.ref}`
          .toLocaleLowerCase()
          .includes(needle);
      return typeMatch && originMatch && searchMatch;
    });
  }, [allItems, filter, origin, search, project]);
  const itemGroups = useMemo(() => {
    // Media pills render one titled section (design 资产仓库-音频 84:81503).
    if (filter === "video" || filter === "audio") {
      return [
        {
          key: `media:${filter}`,
          label: i18n.t(`assets.${filter}`),
          countLabel: i18n.t("assets.items", { count: items.length }),
          items,
        },
      ];
    }
    const visualItems = items.filter((item) => item.kind === "visual");
    const sourceItems = items.filter((item) => item.kind === "source");
    const artifactItems = items.filter((item) => item.kind === "artifact");
    const groups: AssetItemGroup[] = visualItemGroups(project, visualItems);
    if (sourceItems.length) {
      groups.push({
        key: "sources",
        label: i18n.t("assets.source"),
        countLabel: i18n.t("assets.items", { count: sourceItems.length }),
        blueprint: true,
        items: sourceItems,
      });
    }
    if (artifactItems.length) {
      groups.push({
        key: "artifacts",
        label: i18n.t("assets.artifact"),
        countLabel: i18n.t("assets.items", { count: artifactItems.length }),
        blueprint: true,
        items: artifactItems,
      });
    }
    return groups;
  }, [filter, items, project]);
  const selected =
    allItems.find((item) => item.id === selectedId) ||
    allItems.find(
      (item) =>
        item.kind === "visual" &&
        item.entityId === selectedId &&
        item.variantState === "active",
    ) ||
    null;
  const selectedOriginalGate =
    selected?.kind === "source" &&
    sourceCache.versions.some(
      (version) => version.assetVersionId === selected.id && !version.cached,
    );
  const memoryBuilt = useMemo(
    () => (project ? memoryBuiltVersionIds(project, tasks) : new Set<string>()),
    [project, tasks],
  );

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
  // Per-slot version preview choice; defaults to the selected version.
  const [versionPick, setVersionPick] = useState<Record<string, number>>({});
  const displayedItem = (item: AssetItem): AssetItem => {
    if (!item.versions) return item;
    const fallback = item.versions.findIndex((version) => version.selected);
    const index = Math.min(
      Math.max(versionPick[item.id] ?? Math.max(fallback, 0), 0),
      item.versions.length - 1,
    );
    const version = item.versions[index];
    if (!version || version.raw === item.raw) return item;
    return {
      ...item,
      ref: `artifact-version:${version.id}`,
      name: version.name,
      mediaKind: version.mediaKind,
      mediaType: version.mediaType,
      previewUrl: version.previewUrl,
      createdAt: version.createdAt,
      stale: version.raw.stale,
      checksum: version.raw.checksum,
      durationSeconds: version.raw.duration_seconds,
      provenanceRefs: version.raw.provenance_refs,
      metadata: version.raw.metadata,
      raw: version.raw,
    };
  };
  const stepVersion = (item: AssetItem, delta: number) => {
    if (!item.versions) return;
    const fallback = item.versions.findIndex((version) => version.selected);
    const current = versionPick[item.id] ?? Math.max(fallback, 0);
    const next = Math.min(
      Math.max(current + delta, 0),
      item.versions.length - 1,
    );
    setVersionPick((state) => ({ ...state, [item.id]: next }));
  };
  const refreshAfterIngest = async () => {
    await Promise.allSettled([pollOnce(id), refreshTasks(id)]);
  };
  const uploadFile = async (file: File) => {
    setUploading(true);
    setUploadError(null);
    try {
      await ingestAssetFile(id, file, "ATTACH_SOURCE");
      message.success(t("assets.uploadSuccess"));
      await refreshAfterIngest();
    } catch (error) {
      // Keep a persistent inline banner besides the transient toast so the
      // rejection reason stays readable (acceptance B6).
      const text =
        error instanceof Error ? error.message : t("assets.uploadFailed");
      setUploadError(text);
      message.error(text, 6);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };
  const addValue = async () => {
    if (!inputName.trim() || !inputValue.trim()) {
      message.warning(t("assets.fillNameAndContent"));
      return;
    }
    setUploading(true);
    setUploadError(null);
    try {
      await ingestAssetValue(id, {
        kind: inputKind,
        name: inputName.trim(),
        value: inputValue.trim(),
        postIngestAction: "ATTACH_SOURCE",
      });
      message.success(
        inputKind === "url"
          ? t("assets.linkSubmitted")
          : t("assets.textSubmitted"),
      );
      setAddOpen(false);
      setInputName("");
      setInputValue("");
      await refreshAfterIngest();
    } catch (error) {
      const text =
        error instanceof Error ? error.message : t("assets.addFailed");
      setUploadError(text);
      message.error(text, 6);
    } finally {
      setUploading(false);
    }
  };

  // Hooks must run unconditionally, before the loading early-returns.
  const narrowWorkspace = useNarrowWorkspace();
  const detailRail = useDetailRail(narrowWorkspace);

  if (!project) {
    if (syncStatus === "invalid" || syncStatus === "not_found") {
      return (
        <PageLoadError
          message={syncError || t("assets.projectReadError")}
          retry={() => void pollOnce(id)}
        />
      );
    }
    return <PageSkeleton type="grid" />;
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-[var(--color-bg-layout)]">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-[var(--color-border)] bg-[var(--color-bg-primary)]/70 px-5 py-3 backdrop-blur">
        <div className="flex min-w-0 items-center gap-2.5">
          {!sidebarOpen && (
            <button
              type="button"
              data-sidebar-expand
              title={t("plan.expandSidebar")}
              aria-label={t("plan.expandSidebar")}
              onClick={() => setSidebarOpen(true)}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-[var(--color-border)] bg-white text-[var(--color-text-secondary)] transition hover:border-[var(--color-accent)]/50 hover:text-[var(--color-accent)] dark:bg-[var(--color-bg-elevated)]"
            >
              <MenuUnfoldOutlined className="text-base" />
            </button>
          )}
          <div>
            <h2 className="text-base font-semibold text-[var(--color-text-primary)]">
              {t("assets.title")}
            </h2>
            <p className="mt-0.5 text-xs text-[var(--color-text-secondary)]">
              {t("assets.description")}
            </p>
          </div>
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
            {t("assets.addLinkOrText")}
          </Button>
          <Button
            size="small"
            loading={uploading}
            icon={<Upload className="h-3.5 w-3.5" />}
            onClick={() => fileInputRef.current?.click()}
          >
            {t("assets.uploadAsset")}
          </Button>
        </div>
      </header>

      {uploadError && (
        <div
          role="alert"
          data-creator-module="asset-upload-error"
          className="flex shrink-0 items-start justify-between gap-3 border-b border-red-200 bg-red-50 px-5 py-2 text-xs text-red-700"
        >
          <span className="leading-5">{uploadError}</span>
          <button
            type="button"
            aria-label={t("assets.dismissError")}
            onClick={() => setUploadError(null)}
            className="shrink-0 font-semibold text-red-500 hover:text-red-700"
          >
            ×
          </button>
        </div>
      )}

      <div
        data-onboarding-id="assets-filters"
        className="flex shrink-0 flex-wrap items-center gap-2 border-b border-[var(--color-border)] bg-[var(--color-bg-primary)] px-5 py-2.5"
      >
        <div className="flex flex-wrap gap-1.5">
          {FILTERS.map((candidate) => (
            <button
              key={candidate.key}
              type="button"
              onClick={() => setFilter(candidate.key)}
              className={`rounded-full px-3.5 py-1 text-xs transition ${
                filter === candidate.key
                  ? "bg-[var(--color-bg-secondary)] font-medium text-[var(--color-text-primary)]"
                  : "border border-[var(--color-border)] bg-white text-[var(--color-text-secondary)] hover:border-[var(--color-accent)]/50 dark:bg-[var(--color-bg-primary)]"
              }`}
            >
              {t(candidate.labelKey)}
            </button>
          ))}
        </div>
        <div data-assets-origin className="ml-auto">
          <Select
            size="small"
            className="w-[130px]"
            value={origin}
            onChange={(value) => setOrigin(value as OriginKey)}
            options={ORIGINS.map((candidate) => ({
              value: candidate.key,
              label: t(candidate.labelKey),
            }))}
          />
        </div>
        <div className="flex w-56 items-center rounded-lg border border-[var(--color-border)] bg-white px-2.5 dark:bg-[var(--color-bg-primary)]">
          <Search className="h-3.5 w-3.5 text-[var(--color-text-tertiary)]" />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("assets.searchNameOrId")}
            className="min-w-0 flex-1 border-0 bg-transparent px-2 py-1.5 text-xs outline-none"
          />
        </div>
        <span className="text-[11px] text-[var(--color-text-tertiary)]">
          {t("assets.items", { count: items.length })}
        </span>
      </div>

      {/* Size container for the grid/detail area; container queries cannot
          match the querying element itself. */}
      <div className="@container min-h-0 flex-1">
        <main className="relative grid h-full min-h-0 grid-cols-[minmax(0,1fr)_335px] gap-4 overflow-hidden p-4 @max-[719px]:grid-cols-1">
          <section
            data-onboarding-id="assets-grid"
            className="min-h-0 overflow-y-auto rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-primary)] p-3"
          >
            {items.length > 0 ? (
              <div className="grid grid-cols-[repeat(auto-fill,minmax(190px,1fr))] gap-3">
                {itemGroups.map((group) => (
                  <Fragment key={group.key}>
                    {group.label && (
                      <div
                        data-asset-group={group.key}
                        className="col-span-full flex items-center gap-2 border-b border-[var(--color-border)] pb-1.5 pt-1 text-xs font-semibold text-[var(--color-text-secondary)]"
                      >
                        {group.badge && (
                          <span className="rounded bg-[var(--color-bg-secondary)] px-1.5 py-0.5 text-[10px] font-bold text-[var(--color-text-tertiary)]">
                            {group.badge}
                          </span>
                        )}
                        <span>{group.label}</span>
                        {group.countLabel && (
                          <span className="font-normal text-[var(--color-text-tertiary)]">
                            {group.countLabel}
                          </span>
                        )}
                        {group.blueprint && (
                          <button
                            type="button"
                            data-asset-group-blueprint={group.key}
                            onClick={() => navigate(`/project/${id}`)}
                            className="ml-auto rounded px-1.5 py-0.5 text-[10px] font-semibold text-[var(--color-text-tertiary)] transition-colors hover:bg-[var(--color-accent-soft)] hover:text-[var(--color-accent)]"
                          >
                            {t("assets.viewInBlueprint")}
                          </button>
                        )}
                      </div>
                    )}
                    {group.items.map((item) => {
                      const display = displayedItem(item);
                      const Icon = mediaIcon(display.mediaKind);
                      return (
                        <button
                          key={`${item.kind}:${item.id}`}
                          type="button"
                          data-creator-module="asset-card"
                          data-creator-module-id={item.id}
                          onClick={() => selectItem(display)}
                          className={`group overflow-hidden rounded-xl border bg-[var(--color-bg-card)] text-left transition ${
                            selected?.id === item.id
                              ? "border-[var(--color-accent)] shadow-[0_0_0_1px_var(--color-accent)]"
                              : "border-[var(--color-border)] hover:border-[var(--color-border-strong)] hover:shadow-sm"
                          }`}
                        >
                          <div className="relative flex h-32 items-center justify-center overflow-hidden bg-[var(--color-bg-secondary)]">
                            <AssetMediaPreview
                              name={display.name}
                              mediaType={display.mediaKind}
                              previewUrl={display.previewUrl}
                              state={
                                display.previewUrl
                                  ? "ready"
                                  : display.kind === "visual"
                                  ? "planned"
                                  : "unavailable"
                              }
                              mediaClassName="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.02]"
                              placeholderClassName="flex flex-col items-center gap-1.5 text-[11px] text-[var(--color-text-tertiary)]"
                            />
                            {!display.previewUrl && (
                              <Icon className="pointer-events-none absolute h-6 w-6 -translate-y-3 text-[var(--color-text-tertiary)]" />
                            )}
                            {item.versions && (
                              <span
                                data-asset-version-switch={item.id}
                                className="absolute bottom-2 right-2 z-10 flex items-center gap-1 rounded-full bg-black/60 px-1.5 py-0.5 text-[10px] font-bold text-white backdrop-blur-md"
                                onClick={(event) => event.stopPropagation()}
                              >
                                <span
                                  role="button"
                                  tabIndex={0}
                                  className="cursor-pointer px-0.5 transition-transform hover:scale-125"
                                  onClick={() => stepVersion(item, -1)}
                                >
                                  ‹
                                </span>
                                <span className="tabular-nums">
                                  {(versionPick[item.id] ??
                                    Math.max(
                                      item.versions.findIndex(
                                        (version) => version.selected,
                                      ),
                                      0,
                                    )) + 1}
                                  /{item.versions.length}
                                </span>
                                <span
                                  role="button"
                                  tabIndex={0}
                                  className="cursor-pointer px-0.5 transition-transform hover:scale-125"
                                  onClick={() => stepVersion(item, 1)}
                                >
                                  ›
                                </span>
                              </span>
                            )}
                            <span className="absolute left-2 top-2 rounded bg-black/65 px-1.5 py-0.5 text-[10px] font-bold text-white">
                              {kindLabel(display, t)}
                            </span>
                            <div className="absolute right-2 top-2 flex flex-col items-end gap-1">
                              {item.variantState && (
                                <span
                                  className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                                    item.variantState === "active"
                                      ? "bg-emerald-500 text-white"
                                      : item.variantState === "history"
                                      ? "bg-black/60 text-white"
                                      : "bg-amber-500 text-white"
                                  }`}
                                >
                                  {item.variantState === "active"
                                    ? t("assets.active")
                                    : item.variantState === "history"
                                    ? t("assets.history")
                                    : t("assets.unselected")}
                                </span>
                              )}
                              {display.stale && (
                                <span className="rounded bg-amber-500 px-1.5 py-0.5 text-[10px] font-bold text-white">
                                  {t("assets.stale")}
                                </span>
                              )}
                            </div>
                            {characterVoice(item) && (
                              <span
                                title={t("assets.voiceBoundTitle")}
                                className="absolute bottom-2 right-2 flex items-center gap-1 rounded bg-black/65 px-1.5 py-0.5 text-[10px] font-bold text-white"
                              >
                                <Mic className="h-3 w-3" />
                                {t("assets.voiceBadge")}
                              </span>
                            )}
                            {item.kind === "source" &&
                              memoryBuilt.has(item.id) && (
                                <span
                                  data-creator-memory-badge={item.id}
                                  className="absolute bottom-2 right-2 rounded bg-emerald-600/90 px-1.5 py-0.5 text-[10px] font-bold text-white"
                                >
                                  {t("assets.memoryBuilt")}
                                </span>
                              )}
                          </div>
                          <div className="p-3">
                            <h3 className="truncate text-sm font-semibold text-[var(--color-text-primary)]">
                              {item.kind === "visual"
                                ? item.cardName || item.name
                                : display.name}
                            </h3>
                            <p className="mt-1 line-clamp-2 min-h-8 text-[11px] leading-4 text-[var(--color-text-secondary)]">
                              {item.description}
                            </p>
                            {item.kind === "artifact" && item.variantLabel && (
                              <p className="mt-2 truncate text-[10px] font-medium text-[var(--color-text-secondary)]">
                                {item.variantLabel}
                              </p>
                            )}
                            <p className="mt-2 truncate font-mono text-[10px] text-[var(--color-text-tertiary)]">
                              {item.id}
                            </p>
                          </div>
                        </button>
                      );
                    })}
                  </Fragment>
                ))}
              </div>
            ) : (
              <div className="flex h-full min-h-64 flex-col items-center justify-center text-center text-[var(--color-text-tertiary)]">
                <Paperclip className="mb-3 h-8 w-8 opacity-50" />
                <p className="text-sm font-medium text-[var(--color-text-secondary)]">
                  {t("assets.noAssets")}
                </p>
                <p className="mt-1 text-xs">{t("assets.noAssetsDesc")}</p>
              </div>
            )}
          </section>

          {/* On a narrow workspace the detail pane only appears once an asset
            is selected: with the dock open it portals into the right rail
            below the dock, otherwise it slides in as a drawer over the grid. */}
          {(() => {
            const assetDetailAside = (
              <aside
                data-onboarding-id="assets-detail"
                className={`min-h-0 overflow-y-auto rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-primary)] ${
                  selected
                    ? "@max-[719px]:absolute @max-[719px]:inset-y-4 @max-[719px]:right-4 @max-[719px]:z-40 @max-[719px]:w-[min(calc(100%-32px),420px)] @max-[719px]:shadow-2xl"
                    : "@max-[719px]:hidden"
                }`}
              >
                {selected ? (
                  <div>
                    <div
                      data-review-media-anchor={versionFromUrl ?? undefined}
                      className={
                        selectedOriginalGate
                          ? ""
                          : "m-3 mb-0 flex aspect-video items-center justify-center overflow-hidden rounded-lg bg-black"
                      }
                    >
                      {selectedOriginalGate ? (
                        <div className="p-4">
                          <SourceCacheGate status={sourceCache} />
                        </div>
                      ) : selected.mediaKind === "audio" &&
                        selected.previewUrl ? (
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
                          state={
                            selected.previewUrl
                              ? "ready"
                              : selected.kind === "visual"
                              ? "planned"
                              : "unavailable"
                          }
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
                            {kindLabel(selected, t)}
                          </span>
                          {selected.stale && (
                            <span className="text-[10px] font-semibold text-amber-600">
                              {t("assets.expired")}
                            </span>
                          )}
                          {characterVoice(selected) && (
                            <span className="flex items-center gap-1 rounded bg-[var(--color-accent-soft)] px-2 py-0.5 text-[10px] font-semibold text-[var(--color-accent)]">
                              <Mic className="h-3 w-3" />
                              {t("assets.voiceBound")}
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
                      {/* 字段行 (design 84:81503): 时长 / 创建时间. */}
                      <div className="space-y-1.5">
                        {[
                          [
                            t("common.duration"),
                            selected.durationSeconds == null
                              ? "—"
                              : `${selected.durationSeconds.toFixed(2)}s`,
                          ],
                          [
                            t("assets.createdTime"),
                            selected.createdAt
                              ? new Date(selected.createdAt).toLocaleString(
                                  "zh-CN",
                                )
                              : "—",
                          ],
                        ].map(([label, value]) => (
                          <div
                            key={label}
                            className="flex items-center justify-between gap-2 rounded-lg bg-[var(--color-bg-secondary)]/60 px-3 py-2 text-xs"
                          >
                            <span className="shrink-0 text-[var(--color-text-tertiary)]">
                              {label}
                            </span>
                            <span className="truncate text-[var(--color-text-primary)]">
                              {value}
                            </span>
                          </div>
                        ))}
                      </div>
                      {selected.kind === "source" &&
                        selected.mediaKind === "document" && (
                          <DocumentUnderstanding
                            projectId={id}
                            assetId={
                              (selected.raw as SourceAssetVersionDocument)
                                .logical_asset_id
                            }
                            intelligenceVersionId={
                              // Bind the panel to this exact source version; the
                              // versionless endpoint would show the current
                              // version's understanding on older cards.
                              intelligenceVersionForSource(
                                project,
                                selected.raw as SourceAssetVersionDocument,
                              )
                            }
                          />
                        )}
                      {(() => {
                        if (!project) return null;
                        const resolved = selected.provenanceRefs
                          .map((ref) => resolveProvenanceRef(project, ref))
                          .filter(Boolean) as NonNullable<
                          ReturnType<typeof resolveProvenanceRef>
                        >[];
                        if (!resolved.length) return null;
                        return (
                          <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] p-3">
                            <div className="mb-2 text-[11px] font-semibold text-[var(--color-text-secondary)]">
                              {t("assets.provenanceRef")}
                            </div>
                            <div className="flex flex-wrap gap-2">
                              {resolved.map((entry) => {
                                const target = allItems.find(
                                  (item) => item.ref === entry.ref,
                                );
                                return (
                                  <button
                                    key={entry.ref}
                                    type="button"
                                    title={entry.name}
                                    onClick={() => target && selectItem(target)}
                                    className="group flex w-24 flex-col gap-1 rounded-md border border-[var(--color-border)] bg-[var(--color-bg-primary)] p-1 text-left transition hover:border-[var(--color-accent)]"
                                  >
                                    <div className="aspect-video w-full overflow-hidden rounded bg-black/20">
                                      {entry.kind === "video" ? (
                                        <video
                                          src={entry.url}
                                          className="h-full w-full object-cover"
                                          muted
                                        />
                                      ) : (
                                        <img
                                          src={entry.url}
                                          alt={entry.name}
                                          className="h-full w-full object-cover"
                                          loading="lazy"
                                        />
                                      )}
                                    </div>
                                    <span className="truncate text-[10px] text-[var(--color-text-tertiary)] group-hover:text-[var(--color-accent)]">
                                      {entry.name}
                                    </span>
                                  </button>
                                );
                              })}
                            </div>
                          </div>
                        );
                      })()}
                      {(() => {
                        const isCharacter =
                          selected.kind === "visual" &&
                          (selected.raw as VisualEntityDocument).kind ===
                            "character" &&
                          !selected.ref.startsWith("lineup:");
                        const voice = characterVoice(selected);
                        if (!voice) {
                          if (!isCharacter) return null;
                          // 角色还没有专属音色：提供生成入口（音色注册只能由
                          // 创作助手的 create_character_voice 工具完成）。
                          return (
                            <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] p-3">
                              <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold text-[var(--color-text-secondary)]">
                                <Mic className="h-3.5 w-3.5" />
                                {t("assets.voiceTitle")}
                              </div>
                              <p className="text-xs leading-[1.6] text-[var(--color-text-tertiary)]">
                                {t("assets.voiceEmptyHint")}
                              </p>
                              <div className="mt-2.5 flex justify-end">
                                <RegeneratePill
                                  field={`voice:${
                                    selected.entityId ?? selected.id
                                  }`}
                                  label={t("assets.voiceGenerate")}
                                  onClick={() =>
                                    setVoiceModalEntity(
                                      selected.raw as VisualEntityDocument,
                                    )
                                  }
                                />
                              </div>
                            </div>
                          );
                        }
                        const sampleUrl = voice.sample_source_version_id
                          ? getAssetVersionMediaUrl(
                              voice.sample_source_version_id,
                            )
                          : null;
                        return (
                          <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] p-3">
                            <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold text-[var(--color-text-secondary)]">
                              <Mic className="h-3.5 w-3.5" />
                              {t("assets.voiceTitle")}
                            </div>
                            <dl className="space-y-1.5 text-xs">
                              {[
                                [
                                  t("assets.voiceName"),
                                  voice.preferred_name || "—",
                                ],
                                [t("assets.voiceModel"), voice.target_model],
                                [
                                  t("assets.voicePromptLabel"),
                                  voice.voice_prompt ||
                                    t("assets.voicePromptMissing"),
                                ],
                                [
                                  t("assets.createdTime"),
                                  voice.created_at
                                    ? new Date(voice.created_at).toLocaleString(
                                        "zh-CN",
                                      )
                                    : "—",
                                ],
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
                            {sampleUrl ? (
                              <audio
                                src={sampleUrl}
                                controls
                                className="mt-2 h-8 w-full"
                              />
                            ) : (
                              <p className="mt-2 rounded bg-[var(--color-bg-primary)] px-2 py-1.5 text-[10px] leading-4 text-[var(--color-text-tertiary)]">
                                {t("assets.voiceSampleMissing")}
                              </p>
                            )}
                            <div className="mt-2.5 flex justify-end">
                              <RegeneratePill
                                field={`voice:${
                                  selected.entityId ?? selected.id
                                }`}
                                label={t("assets.voiceRegenerate")}
                                onClick={() =>
                                  setVoiceModalEntity(
                                    selected.raw as VisualEntityDocument,
                                  )
                                }
                              />
                            </div>
                          </div>
                        );
                      })()}
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
                            regenerateLabel={
                              selected.mediaKind === "video"
                                ? t("r2v.regenerateVideo")
                                : selected.mediaKind === "audio"
                                ? t("assets.regenerateAudio")
                                : t("r2v.regenerateImage")
                            }
                            onRegenerate={(() => {
                              const nodeId = dispatchNodeIdForPrompt(
                                promptTarget.pointer,
                              );
                              if (!nodeId) return undefined;
                              return () => {
                                void dispatchWorkGraphNode(id, nodeId)
                                  .then((result) => {
                                    message.success(
                                      result.dispatched
                                        ? t("r2v.regenQueued")
                                        : t("r2v.regenUpToDate"),
                                    );
                                    void refreshTasks(id);
                                    void pollOnce(id);
                                  })
                                  .catch((error) =>
                                    message.error((error as Error).message),
                                  );
                              };
                            })()}
                            onSave={async (target, next, addedIds) => {
                              try {
                                const operations: Parameters<
                                  typeof patchProject
                                >[1] = [];
                                if (next !== target.value) {
                                  operations.push({
                                    op: "replace",
                                    path: target.pointer,
                                    before: target.value,
                                    value: next,
                                  });
                                }
                                const binding = target.referenceBinding;
                                if (binding && addedIds.length > 0 && project) {
                                  const addedAssets = addedIds.filter(
                                    (versionId) =>
                                      project.assets.source_versions_by_id[
                                        versionId
                                      ],
                                  );
                                  const addedArtifacts = addedIds.filter(
                                    (versionId) =>
                                      !addedAssets.includes(versionId),
                                  );
                                  if (addedAssets.length) {
                                    operations.push({
                                      op: "replace",
                                      path: `${binding.base}/reference_asset_version_ids`,
                                      before: binding.assetIds,
                                      value: [
                                        ...binding.assetIds,
                                        ...addedAssets,
                                      ],
                                    });
                                  }
                                  if (addedArtifacts.length) {
                                    operations.push({
                                      op: "replace",
                                      path: `${binding.base}/reference_artifact_version_ids`,
                                      before: binding.artifactIds,
                                      value: [
                                        ...binding.artifactIds,
                                        ...addedArtifacts,
                                      ],
                                    });
                                  }
                                }
                                if (!operations.length) return;
                                await patchProject(id, operations);
                                message.success(t("assets.promptSaved"));
                              } catch (error) {
                                message.error(
                                  t("assets.saveFailed", {
                                    detail: (error as Error).message,
                                  }),
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
                            {t("assets.enterR2VWorkbench")}
                          </Button>
                        )}
                    </div>
                  </div>
                ) : (
                  <div className="flex h-full min-h-64 flex-col items-center justify-center px-8 text-center">
                    <Box className="mb-3 h-8 w-8 text-[var(--color-text-tertiary)] opacity-50" />
                    <p className="text-sm font-medium text-[var(--color-text-secondary)]">
                      {t("assets.selectDetail")}
                    </p>
                    <p className="mt-1 text-xs leading-5 text-[var(--color-text-tertiary)]">
                      {t("assets.selectDetailDesc")}
                    </p>
                  </div>
                )}
              </aside>
            );
            return detailRail && selected
              ? createPortal(
                  <div className="grid h-full min-h-0 p-3">
                    {assetDetailAside}
                  </div>,
                  detailRail,
                )
              : assetDetailAside;
          })()}
        </main>
      </div>

      <VoiceGenerationModal
        open={voiceModalEntity !== null}
        projectId={id}
        entity={voiceModalEntity}
        onClose={() => setVoiceModalEntity(null)}
      />

      <Modal
        title={t("assets.addSourceAsset")}
        open={addOpen}
        confirmLoading={uploading}
        okText={t("assets.submitToAssets")}
        cancelText={t("common.cancel")}
        onOk={() => void addValue()}
        onCancel={() => setAddOpen(false)}
      >
        <Tabs
          activeKey={inputKind}
          onChange={(key) => setInputKind(key as "url" | "text")}
          items={[
            { key: "url", label: t("assets.link") },
            { key: "text", label: t("assets.text") },
          ]}
        />
        <div className="space-y-3">
          <Input
            value={inputName}
            onChange={(event) => setInputName(event.target.value)}
            placeholder={t("assets.assetName")}
          />
          <Input.TextArea
            value={inputValue}
            onChange={(event) => setInputValue(event.target.value)}
            autoSize={{ minRows: inputKind === "url" ? 2 : 6, maxRows: 10 }}
            placeholder={
              inputKind === "url"
                ? t("assets.linkPlaceholder")
                : t("assets.textPlaceholder")
            }
          />
        </div>
      </Modal>
    </div>
  );
}
