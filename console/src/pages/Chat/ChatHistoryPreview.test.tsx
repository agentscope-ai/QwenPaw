import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ChatHistory } from "../../api/types";
import { ChatHistoryPreview } from "./ChatHistoryPreview";
import { groupPreviewTurns } from "./chatHistoryPreviewModel";

const history: ChatHistory = {
  messages: [
    {
      id: "user-1",
      role: "user",
      type: "message",
      content: [{ type: "text", text: "Inspect the repository" }],
    },
    {
      id: "reasoning-1",
      role: "assistant",
      type: "reasoning",
      content: [{ type: "text", text: "Plan the inspection" }],
    },
    {
      id: "tool-1",
      role: "assistant",
      type: "plugin_call",
      name: "read_file",
      content: [{ type: "data", data: "README.md" }],
    },
    {
      id: "result-1",
      role: "system",
      type: "plugin_call_output",
      content: [{ type: "text", text: "Repository details" }],
    },
    {
      id: "answer-1",
      role: "assistant",
      type: "message",
      content: [{ type: "text", text: "## Complete\n\nAll checks passed." }],
    },
  ],
};

describe("ChatHistoryPreview", () => {
  it("groups a complete tool-assisted turn without dropping output", () => {
    const turns = groupPreviewTurns(history.messages);

    expect(turns).toHaveLength(1);
    expect(turns[0].user?.id).toBe("user-1");
    expect(turns[0].output.map((message) => message.id)).toEqual([
      "reasoning-1",
      "tool-1",
      "result-1",
      "answer-1",
    ]);
  });

  it("renders final Markdown and keeps process messages collapsed", () => {
    render(<ChatHistoryPreview history={history} />);

    expect(screen.getByText("Inspect the repository")).toBeVisible();
    expect(
      screen.getByText("Completed 3 steps", { selector: "summary" }),
    ).toBeVisible();
    expect(screen.getByRole("heading", { name: "Complete" })).toBeVisible();
    expect(screen.getByText("All checks passed.")).toBeVisible();
    expect(screen.getByText("Plan the inspection")).not.toBeVisible();
  });
});
