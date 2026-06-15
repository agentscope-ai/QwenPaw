import { describe, expect, it } from "vitest";
import {
  coerceFileBaselineWriteDetails,
  isFileBaselineWriteApproval,
  resolveFileBaselineWriteCurrentContent,
  resolveFileBaselineWriteProposedContent,
} from "./fileBaselineWriteApproval";

describe("fileBaselineWriteApproval helpers", () => {
  it("prefers proposed_content over content_preview", () => {
    const details = {
      proposal_id: "p1",
      relative_path: "SOUL.md",
      operation: "write",
      old_sha256: "old",
      new_sha256: "new",
      proposed_content: "full proposed",
      content_preview: "preview",
    };

    expect(resolveFileBaselineWriteProposedContent(details)).toBe("full proposed");
    expect(resolveFileBaselineWriteCurrentContent(details)).toBe("");
    expect(isFileBaselineWriteApproval(details)).toBe(true);
  });

  it("falls back to content_preview when proposed_content is missing", () => {
    const details = {
      proposal_id: "p2",
      relative_path: "SOUL.md",
      operation: "append",
      old_sha256: "old",
      new_sha256: "new",
      content_preview: "preview only",
    };

    expect(resolveFileBaselineWriteProposedContent(details)).toBe("preview only");
    expect(isFileBaselineWriteApproval(details)).toBe(true);
  });

  it("builds persona preview details from tool_params when persona_write missing", () => {
    const details = coerceFileBaselineWriteDetails(undefined, "write_file", {
      file_path: "SOUL.md",
      content: "new soul text",
      current_content: "old soul text",
      operation: "write",
    });
    expect(details?.relative_path).toBe("SOUL.md");
    expect(details?.proposed_content).toBe("new soul text");
    expect(details?.current_content).toBe("old soul text");
  });

  it("recognizes execute_shell_command persona_write payload", () => {
    const details = {
      proposal_id: "",
      relative_path: "SOUL.md",
      operation: "command_execute",
      old_sha256: "",
      new_sha256: "",
      current_content: "baseline",
      proposed_content: "[IO.File]::WriteAllText('SOUL.md', $c)",
    };
    expect(isFileBaselineWriteApproval(details)).toBe(true);
    expect(resolveFileBaselineWriteCurrentContent(details)).toBe("baseline");
  });
});
