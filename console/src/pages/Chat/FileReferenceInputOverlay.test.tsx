// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import FileReferenceInputOverlay from "./FileReferenceInputOverlay";
import { compactFileReferenceLabel } from "./fileReferenceFormatting";
import { setTextareaValue } from "./utils";

describe("FileReferenceInputOverlay", () => {
  it("reads the live sender value and reattaches after replacement", async () => {
    const { rerender } = render(
      <>
        <div className="sender">
          <div>
            <textarea key="with-reference" defaultValue="@ /work/hello.txt" />
          </div>
        </div>
        <FileReferenceInputOverlay />
      </>,
    );

    await waitFor(() => {
      expect(screen.getByRole("button")).toHaveTextContent("hello.txt");
    });
    rerender(
      <>
        <div className="sender">
          <div>
            <textarea key="empty" defaultValue="" />
          </div>
        </div>
        <FileReferenceInputOverlay />
      </>,
    );

    await waitFor(() => {
      expect(screen.queryByRole("button")).not.toBeInTheDocument();
    });
  });

  it("opens a parsed Editor reference without changing the textarea", async () => {
    const onOpenReference = vi.fn();
    render(
      <>
        <div className="sender">
          <div>
            <textarea defaultValue="src/app.ts:12-18" />
          </div>
        </div>
        <FileReferenceInputOverlay onOpenReference={onOpenReference} />
      </>,
    );

    const reference = await screen.findByRole("button");
    fireEvent.click(reference);

    expect(onOpenReference).toHaveBeenCalledWith(
      {
        kind: "editor",
        path: "src/app.ts",
        startLine: 12,
        endLine: 18,
      },
      reference,
    );
    expect(screen.getByRole("textbox")).toHaveValue("src/app.ts:12-18");
  });

  it("syncs a reference inserted through a native input event", async () => {
    render(
      <>
        <div className="sender">
          <div>
            <textarea />
          </div>
        </div>
        <FileReferenceInputOverlay />
      </>,
    );

    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    setTextareaValue(
      textarea,
      "@ /Users/ray/.copaw/workspaces/default/random.md ",
    );

    expect(await screen.findByRole("button")).toHaveTextContent("random.md");
    expect(textarea).toHaveValue(
      "@ /Users/ray/.copaw/workspaces/default/random.md ",
    );
  });

  it("keeps its input marker when the sender rewrites className on focus", async () => {
    render(
      <>
        <div className="sender">
          <div>
            <textarea
              className="sender-input"
              defaultValue="@ /work/random.md"
            />
          </div>
        </div>
        <FileReferenceInputOverlay />
      </>,
    );

    const textarea = screen.getByRole("textbox");
    expect(await screen.findByRole("button")).toHaveTextContent("random.md");

    textarea.className = "sender-input sender-input-mouse-active";
    fireEvent.focus(textarea);

    expect(textarea).toHaveAttribute("data-qwenpaw-file-reference-input");
  });
});

describe("compactFileReferenceLabel", () => {
  it("shows only the file name for a file reference", () => {
    expect(
      compactFileReferenceLabel({
        kind: "file",
        path: "C:\\work\\src\\random.md",
      }),
    ).toBe("random.md");
  });

  it("shows a compact line range for an Editor reference", () => {
    expect(
      compactFileReferenceLabel({
        kind: "editor",
        path: "/work/src/app.ts",
        startLine: 12,
        endLine: 18,
      }),
    ).toBe("app.ts · 12–18");
  });
});
