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

  it("forwards SDK card functions to stable memoized components", () => {
    const requestProps = { data: {} as never };
    const responseProps = { data: {} as never, isLast: false };

    const requestElement = HostRequestCard(requestProps);
    // The response card is wrapped so tool cards learn whether the turn
    // ended; its content must stay memoized behind that wrapper.
    const responseContent = HostResponseCard(responseProps).props.children;

    expect(requestElement.type).toBe(HostRequestCard(requestProps).type);
    expect(responseContent.type).toBe(
      HostResponseCard(responseProps).props.children.type,
    );
    expect(requestElement.type).toHaveProperty(
      "$$typeof",
      Symbol.for("react.memo"),
    );
    expect(responseContent.type).toHaveProperty(
      "$$typeof",
      Symbol.for("react.memo"),
    );
  });
});
