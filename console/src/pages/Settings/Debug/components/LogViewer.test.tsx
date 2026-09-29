// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LogViewer } from "./LogViewer";
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("LogViewer reading continuity", () => {
  it.each([true, false])(
    "retains the reading snapshot until resuming (newestFirst=%s)",
    (newestFirst) => {
      const onDisplayedLines = vi.fn();
      const props = {
        query: "",
        loading: false,
        newestFirst,
        onDisplayedLines,
      };
      const view = render(<LogViewer {...props} lines={["old line"]} />);
      const viewport = screen.getByRole("region");
      Object.defineProperties(viewport, {
        scrollHeight: { configurable: true, value: 1000 },
        clientHeight: { configurable: true, value: 200 },
      });
      viewport.scrollTop = 300;
      fireEvent.scroll(viewport);
      view.rerender(<LogViewer {...props} lines={["new line", "old line"]} />);
      expect(screen.queryByText("new line")).not.toBeInTheDocument();
      expect(screen.getByText("old line")).toBeVisible();
      expect(onDisplayedLines).toHaveBeenLastCalledWith(["old line"]);
      fireEvent.click(
        screen.getByRole("button", { name: "debug.backend.newLogsAvailable" }),
      );
      expect(screen.getByText("new line")).toBeVisible();
      expect(onDisplayedLines).toHaveBeenLastCalledWith([
        "new line",
        "old line",
      ]);
      expect(viewport.scrollTop).toBe(newestFirst ? 0 : 1000);
    },
  );
});
