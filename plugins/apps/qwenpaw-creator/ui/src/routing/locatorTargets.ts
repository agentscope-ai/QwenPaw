import type { ProjectDocument } from "@/contracts/creator";

/** Resolve authored-field ownership from the durable RFC 6901 pointer. */
export function resolveCreatorLocator(
  locator: Record<string, string>,
  project?: ProjectDocument | null,
  field = locator.field,
): Record<string, string> {
  const resolved = { ...locator };
  const tokens =
    field?.startsWith("/") && !/~(?:[^01]|$)/u.test(field)
      ? field
          .slice(1)
          .split("/")
          .map((part) => part.replace(/~1/gu, "/").replace(/~0/gu, "~"))
      : [];
  if (
    tokens[0] === "visual" &&
    tokens[1] === "entities" &&
    tokens[2] === "items" &&
    tokens[3]
  ) {
    resolved.page = "assets";
    resolved.assetId = tokens[3];
    if (tokens[4] === "variants" && tokens[5] === "items" && tokens[6])
      resolved.variantId = tokens[6];
  } else if (tokens[0] === "timelines" && tokens[1] === "items" && tokens[2]) {
    resolved.timelineId = tokens[2];
    if (["title", "synopsis", "description"].includes(tokens[3])) {
      resolved.page = "blueprint";
      delete resolved.elementId;
    }
    if (tokens[3] === "elements_by_id" && tokens[4]) {
      resolved.elementId = tokens[4];
      // Plan exposes intent/narrative; generation prompts and shot editing
      // exist in the dedicated Element workbench, not Plan's compact rail.
      if (
        tokens[5] === "creation" &&
        [
          "storyboard_prompt",
          "video_prompt",
          "narrative",
          "storyboard_reference_version_ids",
          "video_reference_version_ids",
        ].includes(tokens[6])
      )
        resolved.page = "element";
      else if (resolved.page !== "element") resolved.page = "plan";
    }
  }
  // Ref search and production cards also supply entity@variant asset keys.
  // Resolve only against a real entity, so an unrelated source id containing
  // '@' is never split by guesswork.
  if (resolved.assetId && !resolved.variantId && project) {
    const separator = resolved.assetId.lastIndexOf("@");
    const entityId = resolved.assetId.slice(0, separator);
    const variantId = resolved.assetId.slice(separator + 1);
    if (
      separator > 0 &&
      project.visual?.entities.items[entityId]?.variants.items[variantId]
    ) {
      resolved.assetId = entityId;
      resolved.variantId = variantId;
    }
  }
  if (resolved.elementId && !resolved.timelineId && project) {
    const owners = Object.entries(project.timelines?.items ?? {}).filter(
      ([id, timeline]) =>
        !id.startsWith("snapshot:") &&
        timeline.elements_by_id?.[resolved.elementId],
    );
    if (owners.length === 1) resolved.timelineId = owners[0][0];
  }
  return resolved;
}
