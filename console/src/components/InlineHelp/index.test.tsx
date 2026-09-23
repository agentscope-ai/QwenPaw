import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import InlineHelp from "./index";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("InlineHelp inside a form label", () => {
  it("opens help without activating the associated field", async () => {
    const activate = vi.fn();
    render(
      <>
        <label htmlFor="schedule">
          Schedule <InlineHelp>Scheduling help</InlineHelp>
        </label>
        <input id="schedule" onClick={activate} />
      </>,
    );
    fireEvent.click(screen.getByRole("button", { name: "common.help" }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent(
      "Scheduling help",
    );
    expect(activate).not.toHaveBeenCalled();
  });
});
