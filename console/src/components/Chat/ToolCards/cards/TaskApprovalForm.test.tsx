// @vitest-environment jsdom
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import TaskApprovalForm from "./TaskApprovalForm";
import {
  decidePawAppTask,
  type ApprovalRequest,
} from "../../../../api/modules/pawappTasks";
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../../../../api/modules/pawappTasks", () => ({
  decidePawAppTask: vi.fn(),
}));
const api = vi.mocked(decidePawAppTask);
const request: ApprovalRequest = {
  schema_version: 1,
  request_id: "review-1",
  kind: "review",
  subject_digest: `sha256:${"a".repeat(64)}`,
  title: "Review story",
  summary: "Approve this revision only.",
  choices: [
    { decision_id: "approve_once", label: "通过" },
    { decision_id: "request_changes", label: "修改", requires_comment: true },
  ],
};
const props = {
  appId: "neutral-app",
  workspaceId: "main",
  taskId: "task-1",
  request,
  onSettled: vi.fn(),
};
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
describe("explicit approval", () => {
  it("requires user action and feedback; sends stable decision IDs", async () => {
    api.mockResolvedValue({ state: "accepted" } as Awaited<
      ReturnType<typeof decidePawAppTask>
    >);
    render(<TaskApprovalForm {...props} />);
    expect(api).not.toHaveBeenCalled();
    expect((screen.getByText("修改") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Keep the ending quiet" },
    });
    await act(async () => {
      fireEvent.click(screen.getByText("修改"));
    });
    expect(api.mock.calls[0][4]).toEqual({
      request_id: "review-1",
      subject_digest: request.subject_digest,
      decision_id: "request_changes",
      comment: "Keep the ending quiet",
    });
    expect((screen.getByText("通过") as HTMLButtonElement).disabled).toBe(true);
  });
  it("freezes the intent and reuses it after an uncertain response", async () => {
    api.mockRejectedValueOnce(new Error("connection lost"));
    api.mockResolvedValueOnce({ state: "accepted" } as Awaited<
      ReturnType<typeof decidePawAppTask>
    >);
    render(<TaskApprovalForm {...props} />);
    await act(async () => {
      fireEvent.click(screen.getByText("通过"));
    });
    expect((screen.getByText("修改") as HTMLButtonElement).disabled).toBe(true);
    await act(async () => {
      fireEvent.click(screen.getByText("tool.pawappTask.approvalRetry"));
    });
    expect(api.mock.calls[1]).toEqual(api.mock.calls[0]);
    expect(props.onSettled).toHaveBeenCalledTimes(2);
  });
  it("does not submit expired requests", async () => {
    render(
      <TaskApprovalForm {...props} request={{ ...request, expires_at: 1 }} />,
    );
    await act(async () => {
      fireEvent.click(screen.getByText("通过"));
    });
    expect(api).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toContain("approvalExpired");
  });
  it("restores an accepted receipt after reload without offering another decision", () => {
    render(
      <TaskApprovalForm
        {...props}
        receipt={{
          command_id: "prior-user-click",
          state: "accepted",
          actor: { principal_id: "alice", source: "user_interface" },
          decision: {
            request_id: request.request_id,
            subject_digest: request.subject_digest,
            decision_id: "approve_once",
          },
        }}
      />,
    );
    expect((screen.getByText("通过") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole("status").textContent).toContain(
      "approvalAccepted",
    );
    expect(api).not.toHaveBeenCalled();
  });
});
