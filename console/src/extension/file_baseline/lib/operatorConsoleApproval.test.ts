import { describe, expect, it } from "vitest";
import type { PendingApproval } from "../../../api/modules/console";
import {
  filterOperatorConsoleApprovals,
  isOperatorConsoleApproval,
  OPERATOR_CONSOLE_SESSION_PREFIX,
} from "./operatorConsoleApproval";

function sampleApproval(
  overrides: Partial<PendingApproval> = {},
): PendingApproval {
  return {
    request_id: "req-1",
    session_id: "sess-1",
    root_session_id: "sess-1",
    agent_id: "default",
    tool_name: "edit_file",
    severity: "high",
    findings_count: 0,
    findings_summary: "",
    tool_params: {},
    created_at: 100,
    timeout_seconds: 300,
    ...overrides,
  };
}

describe("operatorConsoleApproval", () => {
  it("matches operator_console_save tool", () => {
    expect(
      isOperatorConsoleApproval(
        sampleApproval({ tool_name: "operator_console_save" }),
      ),
    ).toBe(true);
  });

  it("matches persona-console session prefix", () => {
    expect(
      isOperatorConsoleApproval(
        sampleApproval({
          tool_name: "other",
          root_session_id: `${OPERATOR_CONSOLE_SESSION_PREFIX}default`,
        }),
      ),
    ).toBe(true);
  });

  it("does not match agent chat file baseline approvals", () => {
    expect(
      isOperatorConsoleApproval(
        sampleApproval({
          tool_name: "edit_file",
          approval_kind: "file_baseline_write",
          root_session_id: "1781583636495",
        }),
      ),
    ).toBe(false);
  });

  it("sorts operator queue oldest first", () => {
    const queue = filterOperatorConsoleApprovals([
      sampleApproval({
        request_id: "b",
        tool_name: "operator_console_save",
        created_at: 200,
      }),
      sampleApproval({
        request_id: "a",
        tool_name: "operator_console_save",
        created_at: 100,
      }),
    ]);
    expect(queue.map((item) => item.request_id)).toEqual(["a", "b"]);
  });
});
