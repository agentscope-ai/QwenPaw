import { act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import BootScreen from "./BootScreen";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));

describe("BootScreen", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("calls onDone once after the boot and fade durations", () => {
    const onDone = vi.fn();
    renderWithProviders(<BootScreen onDone={onDone} durationMs={1000} />);

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(onDone).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(400);
    });
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("does not call onDone after unmounting before the boot ends", () => {
    const onDone = vi.fn();
    const { unmount } = renderWithProviders(
      <BootScreen onDone={onDone} durationMs={1000} />,
    );

    act(() => {
      vi.advanceTimersByTime(500);
    });
    unmount();
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(onDone).not.toHaveBeenCalled();
  });

  it("does not call onDone after unmounting mid-fade", () => {
    const onDone = vi.fn();
    const { unmount } = renderWithProviders(
      <BootScreen onDone={onDone} durationMs={1000} />,
    );

    // Boot finished, fade timer scheduled.
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    unmount();
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(onDone).not.toHaveBeenCalled();
  });
});
