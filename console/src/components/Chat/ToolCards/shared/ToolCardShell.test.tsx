// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ToolCardShell from "./ToolCardShell";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

const content = {
  type: "tool_call" as const,
  id: "file-tool-1",
  name: "send_file_to_user",
  params: {},
  status: "done" as const,
};

describe("ToolCardShell", () => {
  it("opens file-facing results by default when requested", () => {
    render(
      <ToolCardShell
        content={content}
        icon={<span />}
        title="Send file"
        defaultExpanded
      >
        <div>hello.txt</div>
      </ToolCardShell>,
    );

    const details = screen.getByText("hello.txt").closest("details");
    expect(details).toHaveAttribute("open");
  });

  it("keeps ordinary tool details collapsed", () => {
    render(
      <ToolCardShell content={content} icon={<span />} title="Ordinary tool">
        <div>raw output</div>
      </ToolCardShell>,
    );

    const details = screen.getByText("raw output").closest("details");
    expect(details).not.toHaveAttribute("open");
  });

  it("does not toggle the tool when its summary action is clicked", () => {
    render(
      <ToolCardShell
        content={content}
        icon={<span />}
        title="Read file"
        summaryAction={
          <button
            type="button"
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
            }}
          >
            Preview
          </button>
        }
      >
        <div>raw output</div>
      </ToolCardShell>,
    );

    const details = screen.getByText("raw output").closest("details");
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(details).not.toHaveAttribute("open");
  });
});
