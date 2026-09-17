import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import BlueprintPrepDrawer from "@/components/blueprint/BlueprintPrepDrawer";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { makeReviewOperation, makeReviewRecord } from "@/test/agentFixtures";
import { projectDocument } from "@/test/creatorFixtures";

// VisualDetail reaches into the AssetsPage prompt editor; stub the heavy page
// and return a null prompt target so the design detail renders without it.
vi.mock("@/pages/AssetsPage", () => ({
  GenerationPromptEditor: () => null,
  buildPromptSaveOperations: () => [],
  dispatchNodeIdForPrompt: () => null,
  visualEntityPromptTarget: () => null,
}));

vi.mock("@/api/creator", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/creator")>();
  return {
    ...actual,
    getArtifactVersionMediaUrl: (versionId: string) =>
      `https://media.test/${versionId}`,
    getAssetVersionMediaUrl: (versionId: string) =>
      `https://media.test/${versionId}`,
  };
});

/** The creative auto-review gating the cat design image (cat-anchor-v1). */
const catDesignReview = () =>
  makeReviewRecord({
    review_id: "review-cat",
    operations: [
      makeReviewOperation({
        kind: "create",
        json_pointer: "/assets/artifact_versions_by_id/cat-anchor-v1",
        before: null,
        after: { version_id: "cat-anchor-v1" },
        operation_id: "op-version",
        ui_locator: {
          page: "assets",
          assetId: "cat",
          mediaType: "image",
          artifactKind: "visual_anchor",
          artifactVersionId: "cat-anchor-v1",
        },
      }),
      makeReviewOperation({
        kind: "update",
        json_pointer:
          "/assets/artifact_slots_by_id/visual:cat:anchor/selected_version_id",
        before: "cat-anchor-v0",
        after: "cat-anchor-v1",
        operation_id: "op-slot",
        ui_locator: {
          page: "assets",
          assetId: "cat",
          mediaType: "image",
          artifactVersionId: "cat-anchor-v1",
        },
      }),
    ],
  });

let unmountDrawer: (() => void) | undefined;

function setup(reviews = [catDesignReview()]) {
  const decide = vi.fn(async () => catDesignReview());
  useFileProjectReviewStore.setState({
    projectId: "p1",
    reviews,
    etag: '"token-1"',
    syncStatus: "healthy",
    syncError: null,
    decisionInFlight: false,
    decide,
  });
  const pollOnce = vi.fn(async () => undefined);
  useProjectSnapshotStore.setState({ pollOnce });
  const view = render(
    <BlueprintPrepDrawer
      project={projectDocument}
      projectId="p1"
      open
      tab="visual"
      focus={{ type: "visual", entityId: "cat" }}
      onClose={vi.fn()}
      onTabChange={vi.fn()}
    />,
  );
  unmountDrawer = view.unmount;
  return { decide, pollOnce };
}

afterEach(() => {
  // Unmount before resetting the stores: a reset re-notifies the still-mounted
  // detail view's store subscriptions, which React would flag as an update
  // outside act().
  unmountDrawer?.();
  unmountDrawer = undefined;
  useFileProjectReviewStore.getState().reset();
  useProjectSnapshotStore.getState().reset();
});

describe("BlueprintPrepDrawer design review override (#7720)", () => {
  it("accepts the displayed design in place when a creative review gates it", async () => {
    const { decide, pollOnce } = setup();

    fireEvent.click(
      screen.getByRole("button", { name: "接受此图，忽略自动审阅" }),
    );

    // Accepting keeps every pending operation of the review, which is what
    // flips it to RESOLVED and clears the media review-admission block.
    await waitFor(() =>
      expect(decide).toHaveBeenCalledWith("p1", "review-cat", [
        { operation_id: "op-version", decision: "ACCEPT" },
        { operation_id: "op-slot", decision: "ACCEPT" },
      ]),
    );
    await waitFor(() => expect(pollOnce).toHaveBeenCalledWith("p1"));
  });

  it("keeps the edit-only hint when no review gates the displayed design", () => {
    setup([]);
    expect(
      screen.getByText("设计确认在创作助手的待决策卡中完成，此处仅编辑"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "接受此图，忽略自动审阅" }),
    ).toBeNull();
  });

  it("does not offer the override for an unrelated pending review", () => {
    setup([
      makeReviewRecord({
        review_id: "review-other",
        operations: [
          makeReviewOperation({
            kind: "create",
            json_pointer: "/assets/artifact_versions_by_id/some-other-v1",
            before: null,
            after: { version_id: "some-other-v1" },
            operation_id: "op-other",
            ui_locator: {
              page: "assets",
              mediaType: "image",
              artifactVersionId: "some-other-v1",
            },
          }),
        ],
      }),
    ]);
    expect(
      screen.getByText("设计确认在创作助手的待决策卡中完成，此处仅编辑"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "接受此图，忽略自动审阅" }),
    ).toBeNull();
  });
});
