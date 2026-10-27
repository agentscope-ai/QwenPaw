import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import WallpaperPicker from "./WallpaperPicker";
import { DEFAULT_WALLPAPER_ID, WALLPAPERS } from "./wallpapers";
import { useOsWallpaper } from "./osWallpaperStore";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));

/** The <svg> a wallpaper item renders only while it is the selected one. */
function selectedMark(name: string): Element | null {
  return screen.getByRole("button", { name }).querySelector("svg");
}

describe("WallpaperPicker", () => {
  beforeEach(() => {
    useOsWallpaper.setState({ wallpaperId: DEFAULT_WALLPAPER_ID });
  });

  it("opens as a modal dialog and lists every preset wallpaper", () => {
    renderWithProviders(<WallpaperPicker onClose={vi.fn()} />);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleName("Wallpaper");

    for (const wallpaper of WALLPAPERS) {
      expect(
        screen.getByRole("button", { name: wallpaper.name }),
      ).toBeInTheDocument();
    }
  });

  it("marks the persisted wallpaper as selected on open", () => {
    useOsWallpaper.setState({ wallpaperId: WALLPAPERS[2].id });
    renderWithProviders(<WallpaperPicker onClose={vi.fn()} />);

    expect(selectedMark(WALLPAPERS[2].name)).not.toBeNull();
    expect(selectedMark(WALLPAPERS[0].name)).toBeNull();
  });

  it("selects the clicked wallpaper and moves the selection mark to it", () => {
    renderWithProviders(<WallpaperPicker onClose={vi.fn()} />);
    const target = WALLPAPERS[3];

    fireEvent.click(screen.getByRole("button", { name: target.name }));

    expect(useOsWallpaper.getState().wallpaperId).toBe(target.id);
    expect(selectedMark(target.name)).not.toBeNull();
    expect(selectedMark(WALLPAPERS[0].name)).toBeNull();
  });

  it("selects a wallpaper through the keyboard affordance", () => {
    renderWithProviders(<WallpaperPicker onClose={vi.fn()} />);
    const target = WALLPAPERS[1];
    const item = screen.getByRole("button", { name: target.name });

    // Unrelated keys must not change the selection.
    fireEvent.keyDown(item, { key: "a" });
    expect(useOsWallpaper.getState().wallpaperId).toBe(DEFAULT_WALLPAPER_ID);

    fireEvent.keyDown(item, { key: "Enter" });
    expect(useOsWallpaper.getState().wallpaperId).toBe(target.id);

    useOsWallpaper.setState({ wallpaperId: DEFAULT_WALLPAPER_ID });
    fireEvent.keyDown(item, { key: " " });
    expect(useOsWallpaper.getState().wallpaperId).toBe(target.id);
  });

  it("closes on a backdrop press but not on a press inside the panel", () => {
    const onClose = vi.fn();
    renderWithProviders(<WallpaperPicker onClose={onClose} />);

    fireEvent.pointerDown(screen.getByRole("button", { name: "Close" }));
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.pointerDown(screen.getByRole("dialog"));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("closes from the header close button without changing the wallpaper", () => {
    const onClose = vi.fn();
    renderWithProviders(<WallpaperPicker onClose={onClose} />);

    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    expect(onClose).toHaveBeenCalledOnce();
    expect(useOsWallpaper.getState().wallpaperId).toBe(DEFAULT_WALLPAPER_ID);
  });
});
