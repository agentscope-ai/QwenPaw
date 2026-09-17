import {
  getArtifactVersionMediaUrl,
  getAssetVersionMediaUrl,
} from "@/api/creator";
import type { ProjectDocument, R2VCreationDocument } from "@/contracts/creator";

/**
 * Pure helpers to resolve a preview thumbnail for a reference string
 * (visual-entity: / artifact-version: / asset-version: / bare version id).
 * Extracted from R2VWorkbenchPage so the prompt token renderer and the
 * reference panel share one resolution path.
 */

export interface RefThumb {
  kind: "image" | "video";
  url: string;
}

/** Artifact version chosen to represent a visual entity for this creation. */
export function entityThumbVersionId(
  project: ProjectDocument,
  creation: Pick<R2VCreationDocument, "visual_variant_refs"> | null,
  entityRef: string,
  entityId: string,
): string | null {
  const entity = project.visual.entities.items[entityId];
  if (!entity) return null;
  const variantId =
    creation?.visual_variant_refs[entityRef] ??
    creation?.visual_variant_refs[entityId] ??
    (entity.variants.order.length === 1 ? entity.variants.order[0] : null);
  if (variantId) {
    return (
      entity.variants.items[variantId]?.selected_artifact_version_id ?? null
    );
  }
  return entity.variants.order.length === 0
    ? entity.selected_artifact_version_id
    : null;
}

export function versionMediaKind(
  project: ProjectDocument,
  versionId: string,
): "image" | "video" | null {
  const artifact = project.assets.artifact_versions_by_id[versionId];
  if (artifact) {
    const mediaType =
      (artifact.file_id &&
        project.assets.files_by_id[artifact.file_id]?.media_type) ||
      "";
    if (mediaType.startsWith("video") || `${artifact.kind}`.includes("video"))
      return "video";
    return "image";
  }
  const source = project.assets.source_versions_by_id[versionId];
  if (source) {
    if (source.media_kind === "video") return "video";
    if (source.media_kind === "image") return "image";
    return null;
  }
  return null;
}

/** Storyboard image produced by the same element; video thumbnails prefer it over keyframes. */
export function storyboardOfOwner(
  project: ProjectDocument,
  ownerRef: string,
): string | null {
  if (!ownerRef.startsWith("element:")) return null;
  const candidates = Object.values(
    project.assets.artifact_versions_by_id,
  ).filter(
    (version) =>
      version.owner_ref === ownerRef &&
      `${version.kind}`.includes("storyboard"),
  );
  if (!candidates.length) return null;
  return candidates[candidates.length - 1].version_id;
}

/**
 * Preview for a reference: images render directly; videos use the sibling
 * storyboard image or a keyframe; null when nothing was produced.
 */
export function refThumbInfo(
  project: ProjectDocument,
  creation: Pick<R2VCreationDocument, "visual_variant_refs"> | null,
  ref: string,
): RefThumb | null {
  const entityId = ref.replace(/^visual-entity:/, "");
  if (project.visual.entities.items[entityId]) {
    const versionId = entityThumbVersionId(project, creation, ref, entityId);
    return versionId
      ? { kind: "image", url: getArtifactVersionMediaUrl(versionId) }
      : null;
  }
  const versionId = ref.replace(/^(?:artifact-version|asset-version):/, "");
  const media = versionMediaKind(project, versionId);
  if (!media) return null;
  const artifact = project.assets.artifact_versions_by_id[versionId];
  const url = artifact
    ? getArtifactVersionMediaUrl(versionId)
    : getAssetVersionMediaUrl(versionId);
  if (media === "video") {
    const storyboardId = artifact
      ? storyboardOfOwner(project, artifact.owner_ref ?? "")
      : null;
    if (storyboardId)
      return {
        kind: "image",
        url: getArtifactVersionMediaUrl(storyboardId),
      };
    return { kind: "video", url };
  }
  return { kind: "image", url };
}

/** Image-only thumbnail URL (tokens can't render a <video> inside a pill). */
export function refImageThumbUrl(
  project: ProjectDocument,
  creation: Pick<R2VCreationDocument, "visual_variant_refs"> | null,
  ref: string,
): string | null {
  const thumb = refThumbInfo(project, creation, ref);
  return thumb?.kind === "image" ? thumb.url : null;
}
