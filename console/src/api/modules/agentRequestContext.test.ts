import { describe, expect, it } from "vitest";
import { withAgentRequestContext } from "./agentRequestContext";

describe("withAgentRequestContext", () => {
  it("adds an explicit governance target without dropping existing headers", () => {
    expect(
      withAgentRequestContext(
        { headers: { "If-Match": '"7"' } },
        {
          agentId: "governed-agent",
          governance: true,
        },
      ),
    ).toMatchObject({
      headers: {
        "If-Match": '"7"',
        "X-Agent-Id": "governed-agent",
        "X-Agent-Governance": "runtime-config",
      },
    });
  });

  it("adds the explicit target without enabling governance", () => {
    expect(withAgentRequestContext(undefined, undefined)).toBeUndefined();
    expect(
      withAgentRequestContext({ method: "POST" }, { agentId: "selected" }),
    ).toEqual({
      method: "POST",
      headers: { "X-Agent-Id": "selected" },
    });
  });
});
