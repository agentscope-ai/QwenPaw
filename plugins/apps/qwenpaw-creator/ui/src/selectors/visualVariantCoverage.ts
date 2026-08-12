import type {
  ProjectDocument,
  R2VCreationDocument,
  VisualEntityDocument,
  VisualVariantDocument,
} from "@/contracts/creator";

export type VisualCoverageStatus =
  | "covered"
  | "missing_required_variant"
  | "unassigned_variant"
  | "missing_artifact";

export interface VisualVariantCoverage {
  variant: VisualVariantDocument;
  referencedElementIds: string[];
  generatedCount: number;
  selectedVersionId: string | null;
  selectedAvailable: boolean;
}

export interface VisualEntityCoverage {
  entity: VisualEntityDocument;
  referencedElementIds: string[];
  unassignedElementIds: string[];
  missingVariantIds: string[];
  definedRequiredCount: number;
  entitySelectedAvailable: boolean;
  variants: VisualVariantCoverage[];
  status: VisualCoverageStatus;
}

export interface VisualCoverageReport {
  items: VisualEntityCoverage[];
  covered: number;
  total: number;
  issueCount: number;
}

function referencedEntityIds(creation: R2VCreationDocument): string[] {
  return Array.from(
    new Set(
      [
        ...creation.character_refs,
        creation.scene_ref,
        ...creation.prop_refs,
      ].filter((value): value is string => Boolean(value)),
    ),
  );
}

function resolveEntity(
  project: ProjectDocument,
  ref: string,
): VisualEntityDocument | null {
  const exact = project.visual.entities.items[ref];
  if (exact) return exact;
  if (ref.startsWith("visual-entity:")) {
    return (
      project.visual.entities.items[ref.slice("visual-entity:".length)] ?? null
    );
  }
  return null;
}

function boundVariantId(
  creation: R2VCreationDocument,
  entityRef: string,
  entity: VisualEntityDocument,
): string | null {
  const explicit =
    creation.visual_variant_refs[entityRef] ??
    creation.visual_variant_refs[entity.entity_id];
  if (explicit) return explicit;
  return entity.variants.order.length === 1 ? entity.variants.order[0] : null;
}

export function selectVisualVariantCoverage(
  project: ProjectDocument,
): VisualCoverageReport {
  const references = new Map<
    string,
    {
      entity: VisualEntityDocument;
      elementIds: Set<string>;
      unassignedElementIds: Set<string>;
      variantElements: Map<string, Set<string>>;
    }
  >();

  for (const timelineId of project.timelines.order) {
    const timeline = project.timelines.items[timelineId];
    if (!timeline) continue;
    for (const element of Object.values(timeline.elements_by_id)) {
      if (element.creation.type !== "r2v") continue;
      for (const entityRef of referencedEntityIds(element.creation)) {
        const entity = resolveEntity(project, entityRef);
        if (!entity) continue;
        const entry = references.get(entity.entity_id) ?? {
          entity,
          elementIds: new Set<string>(),
          unassignedElementIds: new Set<string>(),
          variantElements: new Map<string, Set<string>>(),
        };
        entry.elementIds.add(element.element_id);
        const variantId = boundVariantId(element.creation, entityRef, entity);
        if (!variantId || !entity.variants.items[variantId]) {
          entry.unassignedElementIds.add(element.element_id);
        } else {
          const elements =
            entry.variantElements.get(variantId) ?? new Set<string>();
          elements.add(element.element_id);
          entry.variantElements.set(variantId, elements);
        }
        references.set(entity.entity_id, entry);
      }
    }
  }

  const items = project.visual.entities.order.flatMap((entityId) => {
    const entry = references.get(entityId);
    if (!entry) return [];
    const variants = entry.entity.variants.order.flatMap((variantId) => {
      const variant = entry.entity.variants.items[variantId];
      if (!variant) return [];
      const selectedVersionId = variant.selected_artifact_version_id;
      return [
        {
          variant,
          referencedElementIds: [
            ...(entry.variantElements.get(variantId) ?? []),
          ],
          generatedCount: variant.generated_artifact_version_ids.filter(
            (versionId) =>
              Boolean(project.assets.artifact_versions_by_id[versionId]),
          ).length,
          selectedVersionId,
          selectedAvailable: Boolean(
            selectedVersionId &&
              variant.generated_artifact_version_ids.includes(
                selectedVersionId,
              ) &&
              project.assets.artifact_versions_by_id[selectedVersionId],
          ),
        } satisfies VisualVariantCoverage,
      ];
    });
    const missingVariantIds = entry.entity.required_variant_ids.filter(
      (variantId) => !entry.entity.variants.items[variantId],
    );
    const requiredVariants = variants.filter((variant) =>
      entry.entity.required_variant_ids.includes(variant.variant.variant_id),
    );
    const entitySelectedVersionId = entry.entity.selected_artifact_version_id;
    const entitySelectedAvailable = Boolean(
      entitySelectedVersionId &&
        project.assets.artifact_versions_by_id[entitySelectedVersionId],
    );
    const status: VisualCoverageStatus =
      missingVariantIds.length > 0
        ? "missing_required_variant"
        : entry.unassignedElementIds.size > 0
        ? "unassigned_variant"
        : entry.entity.required_variant_ids.length > 0
        ? requiredVariants.some((variant) => !variant.selectedAvailable)
          ? "missing_artifact"
          : "covered"
        : entitySelectedAvailable
        ? "covered"
        : "missing_artifact";
    return [
      {
        entity: entry.entity,
        referencedElementIds: [...entry.elementIds],
        unassignedElementIds: [...entry.unassignedElementIds],
        missingVariantIds,
        definedRequiredCount:
          entry.entity.required_variant_ids.length - missingVariantIds.length,
        entitySelectedAvailable,
        variants,
        status,
      } satisfies VisualEntityCoverage,
    ];
  });
  const covered = items.filter((item) => item.status === "covered").length;
  return {
    items,
    covered,
    total: items.length,
    issueCount: items.length - covered,
  };
}
