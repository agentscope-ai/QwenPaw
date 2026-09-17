import { describe, expect, it, vi, beforeEach } from "vitest";
import { pathForLocator, navigateToLocator } from "@/routing/locators";
import { useNavigationStore } from "@/store/navigationStore";

vi.mock("@/routing/navigation", () => ({
  navigate: vi.fn(),
}));

import { navigate } from "@/routing/navigation";

describe("pathForLocator", () => {
  it("maps element workbench locators to plan/element/:id", () => {
    expect(
      pathForLocator("p1", {
        page: "element",
        elementId: "el-42",
      }),
    ).toBe("/project/p1/plan/element/el-42");
  });

  it("maps asset locators to the assets page", () => {
    expect(pathForLocator("p1", { page: "assets" })).toBe("/project/p1/assets");
  });

  it("defaults unknown pages to plan", () => {
    expect(pathForLocator("p1", { page: "plan" })).toBe("/project/p1/plan");
  });
});

describe("navigateToLocator", () => {
  beforeEach(() => {
    vi.mocked(navigate).mockClear();
    useNavigationStore.getState().clear();
    window.location.hash = "#/project/p1/plan";
  });

  it("passes artifactVersionId as version query for media reviews", () => {
    navigateToLocator(
      "p1",
      {
        page: "element",
        elementId: "el-1",
        artifactVersionId: "ver-9",
        mediaType: "video",
      },
      { review: true, field: "/assets/artifact_versions_by_id/ver-9" },
    );
    expect(navigate).toHaveBeenCalledWith(
      expect.stringContaining("/project/p1/plan/element/el-1"),
    );
    const target = vi.mocked(navigate).mock.calls[0][0] as string;
    expect(target).toContain("version=ver-9");
    expect(target).toContain("review=1");
    expect(target).toContain("field=");
  });
});
