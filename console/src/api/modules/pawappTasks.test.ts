import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../request", () => ({ request: vi.fn() }));

import { request } from "../request";
import { answerPawAppTask, openPawAppSetup } from "./pawappTasks";

const setupAction = {
  schema_version: 1 as const,
  app_id: "qwenpaw-creator",
  request_id: "setup/1",
  entry_id: "creator.video-model-settings",
  presentation: "app_entry" as const,
  path: "/apps/qwenpaw-creator?setup=video&setupRequest=setup-1",
};

beforeEach(() => {
  vi.mocked(request).mockReset();
});

describe("PawApp task interactions", () => {
  it("opens setup through the scoped Host route", async () => {
    vi.mocked(request).mockResolvedValue({ open_action: setupAction });

    await expect(
      openPawAppSetup("qwenpaw-creator", "main agent", "setup/1"),
    ).resolves.toEqual(setupAction);
    expect(request).toHaveBeenCalledWith(
      "/pawapps/qwenpaw-creator/workspaces/main%20agent/setup-requests/setup%2F1/open",
      { method: "POST", headers: { "X-Agent-Id": "main agent" } },
    );
  });

  it.each([
    "https://untrusted.test/apps/qwenpaw-creator",
    "/apps/qwenpaw-creator/../other",
    "/apps/other?setup=video",
  ])("rejects unsafe setup path %s", async (path) => {
    vi.mocked(request).mockResolvedValue({
      open_action: { ...setupAction, path },
    });

    await expect(
      openPawAppSetup("qwenpaw-creator", "main", "setup/1"),
    ).rejects.toThrow("invalid_open_setup_response");
  });

  it("submits an exact answer command and validates its identity", async () => {
    const command = {
      protocol_version: 1 as const,
      task_id: "task/1",
      command_id: "command-1",
      kind: "answer" as const,
      request_id: "approval-1",
      state: "accepted" as const,
      reason: null,
    };
    const answers = [
      {
        question: "Run this generation?",
        selected_options: ["Approve once"],
        custom_text: null,
      },
    ];
    vi.mocked(request).mockResolvedValue({ command });

    await expect(
      answerPawAppTask(
        "qwenpaw-creator",
        "main agent",
        "task/1",
        "command-1",
        "approval-1",
        answers,
      ),
    ).resolves.toEqual(command);
    expect(request).toHaveBeenCalledWith(
      "/pawapps/qwenpaw-creator/workspaces/main%20agent/tasks/task%2F1/answer",
      {
        method: "POST",
        headers: { "X-Agent-Id": "main agent" },
        body: JSON.stringify({
          command_id: "command-1",
          request_id: "approval-1",
          answers,
        }),
      },
    );

    vi.mocked(request).mockResolvedValue({
      command: { ...command, request_id: "other" },
    });
    await expect(
      answerPawAppTask(
        "qwenpaw-creator",
        "main agent",
        "task/1",
        "command-1",
        "approval-1",
        answers,
      ),
    ).rejects.toThrow("invalid_task_answer_response");
  });
});
