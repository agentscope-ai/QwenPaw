import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import ArtifactPanel from "./ArtifactPanel";
const list = vi.hoisted(() => vi.fn());
const copyArtifact = vi.hoisted(() => vi.fn());
const collect = vi.hoisted(() => vi.fn());
vi.mock("../../api/modules/artifacts", () => ({artifactsApi: {list, collect, download: vi.fn(), remove: vi.fn()}}));
vi.mock("../../api/modules/personalLibrary", () => ({personalLibraryApi: {copyArtifact}}));

beforeEach(() => {
  list.mockReset();
  copyArtifact.mockReset();
  collect.mockReset();
});

it("refreshes registered outputs when the artifacts tab is revisited", async () => {
  list.mockResolvedValueOnce([]).mockResolvedValueOnce([{id: "new", original_name: "shandong_cards.md", size: 20, source_tool: "session_artifact_collector"}]);
  const {rerender} = render(<ArtifactPanel requestContext={{agentId: "agent-a"}} refreshToken={0} />);
  await screen.findByText("暂无已登记产物");
  rerender(<ArtifactPanel requestContext={{agentId: "agent-a"}} refreshToken={1} />);
  expect(await screen.findByText("shandong_cards.md")).toBeVisible();
});

it("collects missing outputs for the selected agent and refreshes the list", async () => {
  list.mockResolvedValueOnce([]).mockResolvedValueOnce([{id: "artifact-2", original_name: "result.md", relative_path: "artifacts/result.md", size: 20, source_tool: "session_output", conversation_id: "11111111-1111-4111-8111-111111111111"}]);
  collect.mockResolvedValueOnce({ collected: 1, failures: [] });
  render(<ArtifactPanel requestContext={{ agentId: "agent-a" }} />);

  await userEvent.click(await screen.findByRole("button", {name: "检查未登记文件"}));

  expect(collect).toHaveBeenCalledWith({agentId: "agent-a"});
  expect(await screen.findByText("result.md")).toBeVisible();
});

it("shows a retryable load error instead of claiming the user's artifacts disappeared", async () => {
  list.mockRejectedValueOnce(new Error("network down")).mockResolvedValueOnce([]);
  render(<ArtifactPanel requestContext={{ agentId: "agent-a" }} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("产物加载失败");
  expect(screen.queryByText("暂无已登记产物")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", {name: "重试"}));
  expect(await screen.findByText("暂无已登记产物")).toBeInTheDocument();
});

it("saves an artifact to the personal library and reports the new document", async () => {
  const onLibraryChanged = vi.fn();
  list.mockResolvedValueOnce([{id: "artifact-1", original_name: "report.pdf", relative_path: "artifacts/report.pdf", size: 12, source_tool: "send_file_to_user"}]);
  copyArtifact.mockResolvedValueOnce({relative_path: "artifacts/report.pdf"});
  render(<ArtifactPanel requestContext={{ agentId: "agent-a" }} onLibraryChanged={onLibraryChanged} />);

  await userEvent.click(await screen.findByRole("button", {name: "保存到个人资料库"}));

  expect(copyArtifact).toHaveBeenCalledWith(
    {sourcePath: "artifacts/report.pdf", destinationPath: "artifacts/report.pdf"},
    {agentId: "agent-a"},
  );
  expect(onLibraryChanged).toHaveBeenCalledOnce();
});

it("shows an understandable origin and source conversation", async () => {
  list.mockResolvedValueOnce([{id: "artifact-1", original_name: "report.pdf", relative_path: "artifacts/report.pdf", size: 12, source_tool: "send_file_to_user", conversation_id: "conversation-123"}]);

  render(<ArtifactPanel requestContext={{ agentId: "agent-a" }} />);

  expect(await screen.findByText(/Agent 发送给我的文件/)).toBeVisible();
  expect(screen.getByText(/会话 conversation-123/)).toBeVisible();
  expect(screen.queryByText(/send_file_to_user/)).not.toBeInTheDocument();
  expect(list).toHaveBeenCalledWith({agentId: "agent-a"});
});
