// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

import { FilePreviewLink } from "./FileAttachmentPreview";

describe("FilePreviewLink", () => {
  it("opens a relative tool file from a compact preview link", () => {
    const listener = vi.fn();
    window.addEventListener("qwenpaw:open-file-preview", listener);

    render(
      <FilePreviewLink
        content={{
          type: "tool_call",
          id: "write-1",
          name: "write_file",
          status: "done",
          params: { file_path: "src/result.txt" },
        }}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: /result\.txt.*files\.preview/ }),
    );

    const event = listener.mock.calls[0][0] as CustomEvent;
    expect(event.detail.target).toEqual({
      source: "workspace",
      path: "src/result.txt",
      root: "project",
    });
    window.removeEventListener("qwenpaw:open-file-preview", listener);
  });
});
