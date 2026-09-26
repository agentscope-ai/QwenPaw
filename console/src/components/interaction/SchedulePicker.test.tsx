import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SchedulePicker } from "./SchedulePicker";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));

describe("SchedulePicker", () => {
  it("preserves advanced expressions until the user explicitly changes the schedule", () => {
    const onChange = vi.fn();
    render(<SchedulePicker value="0 9 * * 0" onChange={onChange} />);
    expect((screen.getByRole("textbox") as HTMLInputElement).value).toBe(
      "0 9 * * 0",
    );
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "*/15 * * * *" },
    });
    expect(onChange).toHaveBeenCalledWith("*/15 * * * *");
  });

  it("keeps the current time when changing daily to weekly", () => {
    const onChange = vi.fn();
    render(<SchedulePicker value="30 18 * * *" onChange={onChange} />);
    fireEvent.click(screen.getByText("cronJobs.cronTypeWeekly"));
    expect(onChange).toHaveBeenCalledWith("30 18 * * mon");
  });

  it("shows a disabled time without opening the wheel", () => {
    render(<SchedulePicker value="0 18 * * *" disabled />);
    const time = screen.getByRole("button", {
      name: "cronJobs.cronTime: 18:00",
    });
    expect((time as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
