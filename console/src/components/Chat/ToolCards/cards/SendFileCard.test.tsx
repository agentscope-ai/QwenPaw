// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

/**
 * Models the real ToolCardShell lazy-mount semantics: children stay unmounted
 * until the card is expanded (`ToolCardShell` gates them behind `bodyMounted`).
 * Flipping this flag simulates the user opening the `<details>`.
 */
const userExpanded = vi.hoisted(() => ({ current: false }));

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
  }) => {
    const open = Boolean(defaultExpanded) || userExpanded.current;
    return (
      <div data-testid="shell" data-expanded={String(open)}>
        {open ? children : null}
      </div>
    );
  },
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
  const sentFile = {
    type: "tool_call" as const,
    id: "send-file-1",
    name: "send_file_to_user",
    status: "done" as const,
    params: { file_path: "hello.txt" },
  };

  it("stays collapsed by default and does not mount the preview", () => {
    userExpanded.current = false;
    render(<SendFileCard content={sentFile} />);

    expect(screen.getByTestId("shell")).toHaveAttribute(
      "data-expanded",
      "false",
    );
    // The real shell lazy-mounts its body, so a collapsed card has no preview.
    expect(screen.queryByRole("button", { name: "open file" })).toBeNull();
  });

  it("opens the file preview once the user expands the card", () => {
    userExpanded.current = true;
    const listener = vi.fn();
    window.addEventListener("qwenpaw:open-file-preview", listener);

    render(<SendFileCard content={sentFile} />);
    fireEvent.click(screen.getByRole("button", { name: "open file" }));

    expect(screen.getByTestId("shell")).toHaveAttribute(
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
    userExpanded.current = false;
  });
});
