import { describe, expect, it } from "vitest";
import { HostRequestCard, HostResponseCard } from "./HostBubbles";

describe("host card SDK contract", () => {
  it("exports callable card components", () => {
    // The SDK checks typeof Component === "function" before rendering a
    // registered custom card. React.memo returns an object and is incompatible
    // with that dispatcher even though JSX accepts memoized components.
    expect(typeof HostRequestCard).toBe("function");
    expect(typeof HostResponseCard).toBe("function");
  });
});
