import { describe, expect, it } from "vitest";
import {
  AgentScopeRuntimeMessageType,
  AgentScopeRuntimeRunStatus,
} from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/types";
import {
  countCollapsedSteps,
  findActiveStepBlockIndex,
  findLastStepBlockIndex,
  getCollapsedGroupStatus,
  getCollapsedStepPresentation,
  getCollapsedStepRenderKey,
  getResponseMessageDisplayMode,
  groupResponseMessages,
} from "./messageDisplay";

function message(
  id: string,
  type: AgentScopeRuntimeMessageType,
  status: AgentScopeRuntimeRunStatus = AgentScopeRuntimeRunStatus.Completed,
) {
  return {
    id,
    type,
    content: [],
    role: "assistant",
    status,
  } as never;
}

describe("message display mode", () => {
  it("keeps text, approvals, and errors in text-only mode", () => {
    const messages = [
      message("reasoning", AgentScopeRuntimeMessageType.REASONING),
      message("first", AgentScopeRuntimeMessageType.MESSAGE),
      message("tool", AgentScopeRuntimeMessageType.TOOL_CALL),
      message("approval", AgentScopeRuntimeMessageType.MCP_APPROVAL_REQUEST),
      message("error", AgentScopeRuntimeMessageType.ERROR),
      message("last", AgentScopeRuntimeMessageType.MESSAGE),
    ];

    expect(
      groupResponseMessages(messages, "text-only").flatMap((block) =>
        block.kind === "message" ? [block.message.id] : [],
      ),
    ).toEqual(["first", "approval", "error", "last"]);
  });

  it("keeps only the latest text plus approvals and errors in result mode", () => {
    const messages = [
      message("first", AgentScopeRuntimeMessageType.MESSAGE),
      message("tool", AgentScopeRuntimeMessageType.TOOL_CALL),
      message("approval", AgentScopeRuntimeMessageType.MCP_APPROVAL_REQUEST),
      message("last", AgentScopeRuntimeMessageType.MESSAGE),
      message("error", AgentScopeRuntimeMessageType.ERROR),
    ];

    expect(
      groupResponseMessages(messages, "result-only").flatMap((block) =>
        block.kind === "message" ? [block.message.id] : [],
      ),
    ).toEqual(["approval", "last", "error"]);
  });

  it("derives the display mode only from the response SSE status", () => {
    expect(
      getResponseMessageDisplayMode(AgentScopeRuntimeRunStatus.Created),
    ).toBe("text-only");
    expect(
      getResponseMessageDisplayMode(AgentScopeRuntimeRunStatus.InProgress),
    ).toBe("text-only");
    expect(
      getResponseMessageDisplayMode(AgentScopeRuntimeRunStatus.Completed),
    ).toBe("result-only");
    expect(
      getResponseMessageDisplayMode(AgentScopeRuntimeRunStatus.Canceled),
    ).toBe("result-only");
    expect(
      getResponseMessageDisplayMode(AgentScopeRuntimeRunStatus.Failed),
    ).toBe("result-only");
  });

  it("remounts collapsed steps when streaming enters the result phase", () => {
    const streamingKey = getCollapsedStepRenderKey(
      "reasoning",
      "text-only",
      "finished",
    );
    const resultKey = getCollapsedStepRenderKey(
      "reasoning",
      "result-only",
      "finished",
    );

    expect(resultKey).not.toBe(streamingKey);
  });

  it("returns critical messages when a result has no text", () => {
    const messages = [
      message("tool", AgentScopeRuntimeMessageType.TOOL_CALL),
      message("error", AgentScopeRuntimeMessageType.ERROR),
    ];

    expect(
      groupResponseMessages(messages, "result-only").flatMap((block) =>
        block.kind === "message" ? [block.message.id] : [],
      ),
    ).toEqual(["error"]);
  });

  it("keeps filtered process messages available for manual expansion", () => {
    const messages = [
      message("first", AgentScopeRuntimeMessageType.MESSAGE),
      message("reasoning", AgentScopeRuntimeMessageType.REASONING),
      message("tool", AgentScopeRuntimeMessageType.TOOL_CALL),
      message("last", AgentScopeRuntimeMessageType.MESSAGE),
    ];

    const collapsedIds = (mode: "text-only" | "result-only") =>
      groupResponseMessages(messages, mode).flatMap((block) =>
        block.kind === "steps" ? block.messages.map((item) => item.id) : [],
      );

    expect(collapsedIds("text-only")).toEqual(["reasoning", "tool"]);
    expect(collapsedIds("result-only")).toEqual(["first", "reasoning", "tool"]);
    expect(
      countCollapsedSteps(
        groupResponseMessages(messages, "result-only").flatMap((block) =>
          block.kind === "steps" ? block.messages : [],
        ),
      ),
    ).toBe(2);
  });

  it("identifies an earlier pure-text run as having no process steps", () => {
    const blocks = groupResponseMessages(
      [
        message("first", AgentScopeRuntimeMessageType.MESSAGE),
        message("last", AgentScopeRuntimeMessageType.MESSAGE),
      ],
      "result-only",
    );

    expect(blocks[0].kind).toBe("steps");
    if (blocks[0].kind !== "steps") throw new Error("Expected a steps block");
    expect(countCollapsedSteps(blocks[0].messages)).toBe(0);
  });

  it("groups consecutive steps around each visible text message", () => {
    const messages = [
      message("reasoning-1", AgentScopeRuntimeMessageType.REASONING),
      message("tool-1", AgentScopeRuntimeMessageType.TOOL_CALL),
      message("text-1", AgentScopeRuntimeMessageType.MESSAGE),
      message("reasoning-2", AgentScopeRuntimeMessageType.REASONING),
      message("tool-2", AgentScopeRuntimeMessageType.TOOL_CALL),
      message("tool-3", AgentScopeRuntimeMessageType.TOOL_CALL),
      message("text-2", AgentScopeRuntimeMessageType.MESSAGE),
    ];

    const blocks = groupResponseMessages(messages, "text-only");
    expect(
      blocks.map((block) =>
        block.kind === "message"
          ? `message:${block.message.id}`
          : `steps:${block.messages.map((item) => item.id).join(",")}`,
      ),
    ).toEqual([
      "steps:reasoning-1,tool-1",
      "message:text-1",
      "steps:reasoning-2,tool-2,tool-3",
      "message:text-2",
    ]);
  });

  it("uses approvals and errors as visible group boundaries", () => {
    const messages = [
      message("tool", AgentScopeRuntimeMessageType.TOOL_CALL),
      message("approval", AgentScopeRuntimeMessageType.MCP_APPROVAL_REQUEST),
      message("reasoning", AgentScopeRuntimeMessageType.REASONING),
      message("error", AgentScopeRuntimeMessageType.ERROR),
    ];

    expect(
      groupResponseMessages(messages, "text-only").map((block) =>
        block.kind === "message"
          ? `message:${block.message.id}`
          : `steps:${block.messages.length}`,
      ),
    ).toEqual(["steps:1", "message:approval", "steps:1", "message:error"]);
  });

  it("uses only the response SSE status for the active step group", () => {
    expect(
      getCollapsedGroupStatus(AgentScopeRuntimeRunStatus.InProgress, false),
    ).toBe(AgentScopeRuntimeRunStatus.Completed);
    expect(
      getCollapsedGroupStatus(AgentScopeRuntimeRunStatus.InProgress, true),
    ).toBe(AgentScopeRuntimeRunStatus.InProgress);
    expect(
      getCollapsedGroupStatus(AgentScopeRuntimeRunStatus.Canceled, true),
    ).toBe(AgentScopeRuntimeRunStatus.Canceled);
    expect(
      getCollapsedGroupStatus(AgentScopeRuntimeRunStatus.Failed, true),
    ).toBe(AgentScopeRuntimeRunStatus.Failed);
  });

  it("keeps the latest step group active until following text arrives", () => {
    const runningBlocks = groupResponseMessages(
      [
        message("text-1", AgentScopeRuntimeMessageType.MESSAGE),
        message("tool-1", AgentScopeRuntimeMessageType.TOOL_CALL),
        message("tool-2", AgentScopeRuntimeMessageType.TOOL_CALL_OUTPUT),
      ],
      "text-only",
    );
    expect(findActiveStepBlockIndex(runningBlocks)).toBe(1);

    const completedBlocks = groupResponseMessages(
      [
        message("text-1", AgentScopeRuntimeMessageType.MESSAGE),
        message("tool", AgentScopeRuntimeMessageType.TOOL_CALL),
        message("text-2", AgentScopeRuntimeMessageType.MESSAGE),
      ],
      "text-only",
    );
    expect(findActiveStepBlockIndex(completedBlocks)).toBe(-1);
    expect(findLastStepBlockIndex(completedBlocks)).toBe(1);
  });

  it.each([
    [
      AgentScopeRuntimeRunStatus.InProgress,
      "generating",
      "chat.messageDisplay.stepsRunning",
      true,
    ],
    [
      AgentScopeRuntimeRunStatus.Canceled,
      "interrupted",
      "chat.messageDisplay.stepsCanceled",
      false,
    ],
    [
      AgentScopeRuntimeRunStatus.Failed,
      "error",
      "chat.messageDisplay.stepsFailed",
      false,
    ],
    [
      AgentScopeRuntimeRunStatus.Completed,
      "finished",
      "chat.messageDisplay.stepsCompleted",
      false,
    ],
  ])(
    "maps %s responses to the collapsed step state",
    (runStatus, status, key, defaultOpen) => {
      expect(getCollapsedStepPresentation(runStatus)).toEqual({
        status,
        titleKey: key,
        defaultOpen,
      });
    },
  );
});
