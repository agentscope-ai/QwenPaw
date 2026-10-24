import { useRef, useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useSettingsSearchTarget } from "./useSettingsSearchTarget";

function SearchFixture() {
  const root = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  useSettingsSearchTarget(
    root,
    { page: "runtime", label: "Cache size" },
    "runtime",
  );
  return (
    <div ref={root}>
      <div className="ant-collapse-item">
        <div role="button" aria-expanded="false">
          Unrelated section
        </div>
        <span>Other setting</span>
      </div>
      <div className="ant-collapse-item">
        <div role="button" aria-expanded={open} onClick={() => setOpen(true)}>
          Cache
        </div>
        <div hidden={!open}>
          <label>Cache size</label>
          <input aria-label="Cache size" />
        </div>
      </div>
    </div>
  );
}

describe("settings search disclosure targeting", () => {
  it("opens the disclosure containing a matched field without opening unrelated sections", async () => {
    render(<SearchFixture />);
    await waitFor(() =>
      expect(
        screen
          .getByRole("button", { name: "Cache" })
          .getAttribute("aria-expanded"),
      ).toBe("true"),
    );
    expect(
      screen
        .getByRole("button", { name: "Unrelated section" })
        .getAttribute("aria-expanded"),
    ).toBe("false");
    expect(screen.getByRole("textbox", { name: "Cache size" })).toBeTruthy();
  });
});
