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
          Schedule <InlineHelp subject="Schedule">Scheduling help</InlineHelp>
        </label>
        <input id="schedule" onClick={activate} />
      </>,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Schedule · common.help" }),
    );
    expect(await screen.findByRole("tooltip")).toHaveTextContent(
      "Scheduling help",
    );
    expect(activate).not.toHaveBeenCalled();
  });
});

it("opens inline help with the keyboard and dismisses help before its parent", async () => {
  const parentKey = vi.fn();
  render(
    <div onKeyDown={parentKey}>
      <InlineHelp inline subject="Timeout">
        Timeout explanation
      </InlineHelp>
    </div>,
  );
  const trigger = screen.getByRole("button", { name: "Timeout · common.help" });
  fireEvent.keyDown(trigger, { key: "Enter" });
  expect(await screen.findByRole("tooltip")).toHaveTextContent(
    "Timeout explanation",
  );
  expect(parentKey).not.toHaveBeenCalled();
  fireEvent.keyDown(trigger, { key: "Escape" });
  expect(parentKey).not.toHaveBeenCalled();
  fireEvent.keyDown(trigger, { key: "Escape" });
  expect(parentKey).toHaveBeenCalledOnce();
});

it("uses the explanation as a readable fallback name", () => {
  render(<InlineHelp>Scheduling help</InlineHelp>);
  expect(
    screen.getByRole("button", { name: "Scheduling help" }),
  ).toBeInTheDocument();
});
