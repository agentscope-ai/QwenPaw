// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import FileReferenceInputOverlay from "./FileReferenceInputOverlay";

describe("FileReferenceInputOverlay", () => {
  it("renders the controlled sender value and clears with that value", async () => {
    const { rerender } = render(
      <>
        <div className="sender">
          <div>
            <textarea defaultValue="@ /work/hello.txt" />
          </div>
        </div>
        <FileReferenceInputOverlay value="@ /work/hello.txt" />
      </>,
    );

    await waitFor(() => {
      expect(screen.getByRole("button")).toHaveTextContent("@ /work/hello.txt");
    });
    rerender(
      <>
        <div className="sender">
          <div>
            <textarea defaultValue="" />
          </div>
        </div>
        <FileReferenceInputOverlay value="" />
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
        <FileReferenceInputOverlay
          value="src/app.ts:12-18"
          onOpenReference={onOpenReference}
        />
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
});
