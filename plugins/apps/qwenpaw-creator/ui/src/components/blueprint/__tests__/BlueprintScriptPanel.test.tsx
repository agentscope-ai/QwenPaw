import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import BlueprintScriptPanel from "@/components/blueprint/BlueprintScriptPanel";
import { projectDocument } from "@/test/creatorFixtures";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";

vi.mock("@/api/creator", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/creator")>()),
  getArtifactVersionMediaUrl: (id: string) => `https://media.test/${id}`,
}));

function scriptProject() {
  const project = structuredClone(projectDocument);
  project.timelines.items["timeline:main"].description = "较早的内联草稿";
  project.assets.artifact_slots_by_id["script:timeline:main"] = {
    slot_id: "script:timeline:main",
    kind: "timeline_script",
    owner_ref: "timeline:timeline:main",
    version_ids: ["script-v1"],
    selected_version_id: "script-v1",
    metadata: {},
  };
  project.assets.artifact_versions_by_id["script-v1"] = {
    ...project.assets.artifact_versions_by_id["cat-anchor-v1"],
    version_id: "script-v1",
    slot_id: "script:timeline:main",
    kind: "timeline_script",
    owner_ref: "timeline:timeline:main",
    file_id: "script-file",
    name: "序章",
    stale: true,
    stale_reason: "剧本创作依据已修改，需要重新起草",
  };
  return project;
}

afterEach(() => {
  vi.unstubAllGlobals();
  useProjectSnapshotStore.getState().reset();
});

describe("script synchronization status", () => {
  it("explains automatic input changes while preserving the selected script and backend stale fact", async () => {
    const project = scriptProject();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () => "# 序章正文\n已经生成的正式剧本。",
    });
    vi.stubGlobal("fetch", fetchMock);
    const patch = vi.spyOn(useProjectSnapshotStore.getState(), "patch");
    render(
      <BlueprintScriptPanel
        project={project}
        projectId="p1"
        timelineId="timeline:main"
        open
        onClose={vi.fn()}
        onOpenTimeline={vi.fn()}
        onOpenVisualEntity={vi.fn()}
      />,
    );

    expect(screen.getByText("待同步")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "生成过程中补全剧情分支或创作要求也会触发此状态",
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "更新原因：剧本创作依据已修改，需要重新起草",
    );
    expect(await screen.findByText("已经生成的正式剧本。")).toBeInTheDocument();
    expect(screen.queryByText("较早的内联草稿")).not.toBeInTheDocument();
    expect(project.assets.artifact_versions_by_id["script-v1"].stale).toBe(
      true,
    );
    expect(patch).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(
      "https://media.test/script-v1",
    );
  });

  it("removes the notice only when an updated snapshot selects a synchronized script", async () => {
    const project = scriptProject();
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, text: async () => "当前剧本正文" });
    vi.stubGlobal("fetch", fetchMock);
    const props = {
      projectId: "p1",
      timelineId: "timeline:main",
      open: true,
      onClose: vi.fn(),
      onOpenTimeline: vi.fn(),
      onOpenVisualEntity: vi.fn(),
    };
    const { rerender } = render(
      <BlueprintScriptPanel {...props} project={project} />,
    );
    await screen.findByText("当前剧本正文");
    const updated = structuredClone(project);
    updated.assets.artifact_versions_by_id["script-v1"].stale = false;
    updated.assets.artifact_versions_by_id["script-v1"].stale_reason = null;
    rerender(<BlueprintScriptPanel {...props} project={updated} />);
    await waitFor(() =>
      expect(screen.queryByRole("status")).not.toBeInTheDocument(),
    );
    expect(screen.getByText("当前剧本正文")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
