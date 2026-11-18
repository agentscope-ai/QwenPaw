import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { Modal } from "antd";
import { afterEach, expect, it, vi } from "vitest";
import ProductionStageControl from "../ProductionStageControl";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { projectDocument } from "@/test/creatorFixtures";
import { installMockFetch } from "@/test/mockFetch";

afterEach(() => {
  vi.restoreAllMocks();
  useProjectSnapshotStore.getState().reset();
});

it("confirms the displayed script snapshot even when polling updates behind the dialog", async () => {
  const project = structuredClone(projectDocument);
  project.settings.production_stage = "script";
  const pollOnce = vi.fn(async () => {});
  useProjectSnapshotStore.setState({
    projectId: "p1",
    project,
    etag: '"displayed"',
    patching: false,
    pollOnce,
  });
  const confirm = vi.spyOn(Modal, "confirm").mockImplementation(() => ({
    destroy: vi.fn(),
    update: vi.fn(),
  }));
  const { calls } = installMockFetch([
    {
      match: "/projects/p1/production-stage",
      response: { json: { ok: true } },
    },
  ]);
  render(<ProductionStageControl projectId="p1" />);
  fireEvent.click(screen.getByRole("button", { name: "确认剧本并继续" }));
  expect(calls).toHaveLength(0);
  act(() => useProjectSnapshotStore.setState({ etag: '"newer"' }));
  await act(async () => {
    await confirm.mock.calls[0][0].onOk?.();
  });
  await waitFor(() => expect(pollOnce).toHaveBeenCalledWith("p1"));
  expect(calls[0].body).toEqual({ stage: "media", projectEtag: '"displayed"' });
});
