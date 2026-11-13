import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import { useIsMobile } from "./useIsMobile";
import { OsWindowSizeContext } from "../os/osWindowSizeContext";

function withWidth(width: number | null) {
  return ({ children }: { children: React.ReactNode }) => (
    <OsWindowSizeContext.Provider value={width}>
      {children}
    </OsWindowSizeContext.Provider>
  );
}

describe("useIsMobile", () => {
  it("uses container width when inside an OS window (narrow)", () => {
    const { result } = renderHook(() => useIsMobile(), {
      wrapper: withWidth(500),
    });
    expect(result.current).toBe(true);
  });

  it("uses container width when inside an OS window (wide)", () => {
    const { result } = renderHook(() => useIsMobile(), {
      wrapper: withWidth(1000),
    });
    expect(result.current).toBe(false);
  });

  it("falls back to viewport width without a provider", () => {
    // jsdom default innerWidth is 1024 (> 768).
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(false);
  });

  it("null container width falls back to viewport", () => {
    const { result } = renderHook(() => useIsMobile(), {
      wrapper: withWidth(null),
    });
    expect(result.current).toBe(false);
  });
});
