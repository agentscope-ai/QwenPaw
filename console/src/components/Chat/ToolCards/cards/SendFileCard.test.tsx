// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock("../shared", () => ({
  ToolCardShell: ({
    children,
    defaultExpanded,
  }: {
    children?: React.ReactNode;
    defaultExpanded?: boolean;
  }) => <div data-expanded={String(Boolean(defaultExpanded))}>{children}</div>,
  MediaPreview: ({
    onFileOpen,
  }: {
    onFileOpen?: (trigger: HTMLElement) => void;
  }) => (
    <button
      type="button"
      onClick={(event) => onFileOpen?.(event.currentTarget)}
    >
      open file
    </button>
  ),
}));

vi.mock("../shared/utils", () => ({
  shortFileName: (path: string) => path.split("/").pop() ?? path,
  getMediaInfo: () => ({
    url: "/api/files/preview/hello.txt",
    name: "hello.txt",
    type: "file",
  }),
}));

import SendFileCard from "./SendFileCard";

describe("SendFileCard", () => {
  it("expands a text attachment by default and opens it", () => {
    const listener = vi.fn();
    window.addEventListener("qwenpaw:open-file-preview", listener);

    render(
      <SendFileCard
        content={{
          type: "tool_call",
          id: "send-file-1",
          name: "send_file_to_user",
          status: "done",
          params: { file_path: "hello.txt" },
        }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "open file" }));

    expect(screen.getByRole("button").parentElement).toHaveAttribute(
      "data-expanded",
      "true",
    );
    expect(listener).toHaveBeenCalledTimes(1);
    const event = listener.mock.calls[0][0] as CustomEvent;
    expect(event.detail.target).toEqual({
      source: "attachment",
      path: "/hello.txt",
      artifactUrl: "/api/files/preview/hello.txt",
    });

    window.removeEventListener("qwenpaw:open-file-preview", listener);
  });
});
