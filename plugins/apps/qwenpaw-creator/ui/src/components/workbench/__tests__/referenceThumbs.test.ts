import { describe, expect, it } from "vitest";
import type { ProjectDocument } from "@/contracts/creator";
import { storyboardOfOwner } from "../referenceThumbs";

function projectWith(slots: Record<string, unknown>): ProjectDocument {
  return {
    assets: {
      artifact_slots_by_id: slots,
      artifact_versions_by_id: {
        // Key-sorted map: the revised version's id sorts BEFORE the first
        // one, which is exactly how the field bug hid v2 (shot3, 2026-09-11).
        "artifact-version-0415-v2": {
          version_id: "artifact-version-0415-v2",
          owner_ref: "element:elem:shot3",
          kind: "r2v_storyboard_image",
        },
        "artifact-version-aac3-v1": {
          version_id: "artifact-version-aac3-v1",
          owner_ref: "element:elem:shot3",
          kind: "r2v_storyboard_image",
        },
      },
    },
  } as unknown as ProjectDocument;
}

describe("storyboardOfOwner", () => {
  it("returns the slot's selected version, not the last map entry", () => {
    const project = projectWith({
      "element:elem:shot3:storyboard": {
        slot_id: "element:elem:shot3:storyboard",
        kind: "r2v_storyboard_image",
        owner_ref: "element:elem:shot3",
        version_ids: ["artifact-version-aac3-v1", "artifact-version-0415-v2"],
        selected_version_id: "artifact-version-0415-v2",
        metadata: {},
      },
    });
    expect(storyboardOfOwner(project, "element:elem:shot3")).toBe(
      "artifact-version-0415-v2",
    );
  });

  it("falls back to the version scan for slotless legacy data", () => {
    const project = projectWith({});
    expect(storyboardOfOwner(project, "element:elem:shot3")).toBe(
      "artifact-version-aac3-v1",
    );
  });
});
