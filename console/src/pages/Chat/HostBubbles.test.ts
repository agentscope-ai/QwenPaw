import { describe, expect, it } from "vitest";
import { AgentScopeRuntimeMessageType } from "@agentscope-ai/chat";
import { HostRequestCard, HostResponseCard } from "./HostBubbles";
import { isToolLikeResponseMessageType } from "./responseMessageTypes";

describe("host card SDK contract", () => {
  it("exports a callable response card component", () => {
    // The SDK checks typeof Component === "function" before rendering a
    // registered custom card. React.memo returns an object and is incompatible
    // with that dispatcher even though JSX accepts memoized components.
    expect(typeof HostResponseCard).toBe("function");
    expect(typeof HostRequestCard).toBe("function");
  });

  it("forwards the SDK card function to a stable memoized component", () => {
    const responseProps = {
      id: "assistant-message-1",
      data: {} as never,
      isLast: false,
    };

    const requestProps = { data: {} };
    const requestElement = HostRequestCard(requestProps);
    const responseElement = HostResponseCard(responseProps);
    // The response card is wrapped so tool cards learn whether the turn
    // ended; its content must stay memoized behind that wrapper.
    const responseContent = responseElement.props.children;

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

  it.each([
    AgentScopeRuntimeMessageType.PLUGIN_CALL,
    AgentScopeRuntimeMessageType.PLUGIN_CALL_OUTPUT,
    AgentScopeRuntimeMessageType.TOOL_CALL,
    AgentScopeRuntimeMessageType.TOOL_CALL_OUTPUT,
    AgentScopeRuntimeMessageType.FUNCTION_CALL,
    AgentScopeRuntimeMessageType.FUNCTION_CALL_OUTPUT,
    AgentScopeRuntimeMessageType.COMPONENT_CALL,
    AgentScopeRuntimeMessageType.COMPONENT_CALL_OUTPUT,
    AgentScopeRuntimeMessageType.MCP_CALL,
    AgentScopeRuntimeMessageType.MCP_CALL_OUTPUT,
  ])("renders %s through the tool-card path", (type) => {
    expect(isToolLikeResponseMessageType(type)).toBe(true);
  });

  it("keeps ordinary assistant messages out of the tool-card path", () => {
    expect(
      isToolLikeResponseMessageType(AgentScopeRuntimeMessageType.MESSAGE),
    ).toBe(false);
  });
});
