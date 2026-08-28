import { describe, expect, it } from "vitest";
import { AgentScopeRuntimeMessageType } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/types";
import { HostRequestCard, HostResponseCard } from "./HostBubbles";
import { isToolLikeResponseMessageType } from "./responseMessageTypes";

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
    const responseProps = {
      id: "assistant-message-1",
      data: {} as never,
      isLast: false,
    };

    const requestElement = HostRequestCard(requestProps);
    const responseElement = HostResponseCard(responseProps);

    expect(requestElement.type).toBe(HostRequestCard(requestProps).type);
    expect(responseElement.type).toBe(HostResponseCard(responseProps).type);
    expect(requestElement.type).toHaveProperty(
      "$$typeof",
      Symbol.for("react.memo"),
    );
    expect(responseElement.type).toHaveProperty(
      "$$typeof",
      Symbol.for("react.memo"),
    );
    expect(responseElement.props.id).toBe("assistant-message-1");
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
