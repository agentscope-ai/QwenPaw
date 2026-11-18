import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import WorldMap from "./WorldMap";
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
describe("time-zone map", () => {
  it("reports the selected UTC offset for direct time-zone selection", () => {
    const onOffsetChange = vi.fn();
    render(
      <WorldMap
        value="Asia/Shanghai"
        offset={null}
        label={(value) => value}
        onOffsetChange={onOffsetChange}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "UTC+8" }));
    expect(onOffsetChange).toHaveBeenCalledWith(480);
    expect(screen.queryByRole("button", { name: "Asia/Shanghai" })).toBeNull();
    fireEvent.keyDown(screen.getByRole("button", { name: "UTC+5" }), {
      key: "Enter",
    });
    expect(onOffsetChange).toHaveBeenLastCalledWith(300);
  });
  it("previews Beijing on hover without selecting a new time zone", () => {
    const onOffsetChange = vi.fn();
    render(
      <WorldMap
        value="UTC"
        offset={0}
        label={(value) => value}
        onOffsetChange={onOffsetChange}
      />,
    );
    fireEvent.pointerEnter(screen.getByRole("button", { name: "UTC+8" }));
    expect(
      within(screen.getByRole("status")).getByText("UTC+08:00"),
    ).toBeTruthy();
    expect(
      within(screen.getByRole("status")).getByText("runtimeDesign.mapPlaces.8"),
    ).toBeTruthy();
    expect(onOffsetChange).not.toHaveBeenCalled();
    fireEvent.pointerLeave(screen.getByRole("button", { name: "UTC+8" }));
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("respects disabled state for keyboard and pointer selection", () => {
    const onOffsetChange = vi.fn();
    render(
      <WorldMap
        value="Asia/Shanghai"
        offset={480}
        disabled
        label={(value) => value}
        onOffsetChange={onOffsetChange}
      />,
    );
    const band = screen.getByRole("button", { name: "UTC+8" });
    fireEvent.click(band);
    fireEvent.keyDown(band, { key: "Enter" });
    expect(onOffsetChange).not.toHaveBeenCalled();
    expect(band.getAttribute("tabindex")).toBe("-1");
  });
});
