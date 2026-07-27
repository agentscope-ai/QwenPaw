// @vitest-environment jsdom
import { render, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
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
      expect(document.querySelector('[aria-hidden="true"]')).toHaveTextContent(
        "@ /work/hello.txt",
      );
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
      expect(document.querySelector('[aria-hidden="true"]')?.textContent).toBe(
        "",
      );
    });
  });
});
