import { describe, expect, it } from "vitest";
import type { MCPAccessPolicy, MCPToolInfo } from "../../../api/types";
import {
  addClientRule,
  addToolRule,
  buildMCPAccessToolGroups,
  removeClientRule,
  removeToolRule,
  upsertClientRule,
  upsertToolDefault,
  upsertToolRule,
} from "./accessPolicy";

const tools: MCPToolInfo[] = [
  {
    name: "echo",
    description: "Echo text",
    enabled: true,
    input_schema: { type: "object" },
  },
  {
    name: "search",
    description: "Search",
    enabled: true,
    input_schema: {},
  },
];

const consoleEchoRule = {
  tool_name: "echo",
  source_type: "channel" as const,
  source_value: "console",
  subject_type: "all" as const,
  subject_value: "",
  effect: "allow" as const,
};

const dingtalkSearchRule = {
  tool_name: "search",
  source_type: "channel" as const,
  source_value: "dingtalk",
  subject_type: "all" as const,
  subject_value: "",
  effect: "deny" as const,
};

const policy: MCPAccessPolicy = {
  default_effect: "ask",
  client_overrides: [
    {
      source_type: "channel",
      source_value: "console",
      subject_type: "all",
      subject_value: "",
      effect: "allow",
    },
  ],
  tool_defaults: [{ tool_name: "search", effect: "deny" }],
  tool_overrides: [
    consoleEchoRule,
    {
      ...consoleEchoRule,
      tool_name: "old_tool",
      effect: "deny",
    },
    dingtalkSearchRule,
  ],
  unmanaged_rules_count: 1,
};

describe("MCP access policy helpers", () => {
  it("groups current tools and stale saved rules by tool", () => {
    const groups = buildMCPAccessToolGroups(tools, policy);

    expect(groups).toEqual([
      expect.objectContaining({
        toolName: "echo",
        description: "Echo text",
        stale: false,
        defaultEffect: "ask",
        hasExplicitDefault: false,
        rules: [consoleEchoRule],
      }),
      expect.objectContaining({
        toolName: "search",
        stale: false,
        defaultEffect: "deny",
        hasExplicitDefault: true,
        rules: [dingtalkSearchRule],
      }),
      expect.objectContaining({
        toolName: "old_tool",
        stale: true,
        defaultEffect: "ask",
        hasExplicitDefault: false,
        rules: [
          {
            ...consoleEchoRule,
            tool_name: "old_tool",
            effect: "deny",
          },
        ],
      }),
    ]);
  });

  it("adds and updates MCP-wide client rules independently from tool rules", () => {
    const added = addClientRule({
      ...policy,
      client_overrides: [],
    });

    expect(added.client_overrides).toContainEqual({
      source_type: "channel",
      source_value: "console",
      subject_type: "all",
      subject_value: "",
      effect: "ask",
    });

    const updated = upsertClientRule(
      added,
      {
        source_type: "channel",
        source_value: "dingtalk",
        subject_type: "user",
        subject_value: "alice",
        effect: "deny",
      },
      added.client_overrides[0],
    );

    expect(updated.client_overrides).toEqual([
      {
        source_type: "channel",
        source_value: "dingtalk",
        subject_type: "user",
        subject_value: "alice",
        effect: "deny",
      },
    ]);
    expect(
      removeClientRule(updated, updated.client_overrides[0]).client_overrides,
    ).toEqual([]);
  });

  it("preserves custom source selectors instead of coercing them", () => {
    const normalized = addClientRule({
      ...policy,
      client_overrides: [
        {
          source_type: "channel",
          source_value: "custom-channel",
          subject_type: "all",
          subject_value: "",
          effect: "allow",
        },
        {
          source_type: "future-source",
          source_value: "",
          subject_type: "user",
          subject_value: "alice",
          effect: "deny",
        },
      ],
      tool_overrides: [],
    });

    expect(normalized.client_overrides).toContainEqual({
      source_type: "channel",
      source_value: "custom-channel",
      subject_type: "all",
      subject_value: "",
      effect: "allow",
    });
    expect(normalized.client_overrides).toContainEqual({
      source_type: "future-source",
      source_value: "",
      subject_type: "user",
      subject_value: "alice",
      effect: "deny",
    });
  });

  it("sets a per-tool default policy without adding a source rule", () => {
    const next = upsertToolDefault(policy, "echo", "deny");

    expect(next.tool_defaults).toContainEqual({
      tool_name: "echo",
      effect: "deny",
    });
    expect(next.tool_overrides).toContainEqual(consoleEchoRule);
  });

  it("adds a default console source rule under the selected tool", () => {
    const next = addToolRule(policy, "search");

    expect(next.tool_overrides).toContainEqual({
      tool_name: "search",
      source_type: "channel",
      source_value: "console",
      subject_type: "all",
      subject_value: "",
      effect: "ask",
    });
  });

  it("updates a rule selector or effect without duplicating the same tool rule", () => {
    const renamed = upsertToolRule(
      policy,
      {
        ...dingtalkSearchRule,
        source_type: "channel",
        source_value: "feishu",
        subject_type: "user",
        subject_value: "alice",
        effect: "allow",
      },
      dingtalkSearchRule,
    );

    expect(renamed.tool_overrides).not.toContainEqual(dingtalkSearchRule);
    expect(renamed.tool_overrides).toContainEqual({
      tool_name: "search",
      source_type: "channel",
      source_value: "feishu",
      subject_type: "user",
      subject_value: "alice",
      effect: "allow",
    });

    const changedEffect = upsertToolRule(renamed, {
      tool_name: "search",
      source_type: "channel",
      source_value: "feishu",
      subject_type: "user",
      subject_value: "alice",
      effect: "deny",
    });
    expect(
      changedEffect.tool_overrides.filter(
        (item) =>
          item.tool_name === "search" &&
          item.source_type === "channel" &&
          item.source_value === "feishu" &&
          item.subject_type === "user" &&
          item.subject_value === "alice",
      ),
    ).toEqual([
      {
        tool_name: "search",
        source_type: "channel",
        source_value: "feishu",
        subject_type: "user",
        subject_value: "alice",
        effect: "deny",
      },
    ]);
  });

  it("removes one structured rule from a tool", () => {
    const next = removeToolRule(policy, consoleEchoRule);

    expect(next.tool_overrides).not.toContainEqual(consoleEchoRule);
    expect(next.tool_overrides).toContainEqual(dingtalkSearchRule);
  });
});
