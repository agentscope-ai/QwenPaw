/**
 * MCPAccessModal — per-client MCP access policy editor. Covers the load
 * matrix (policy/tools/principals/channel-types success and failures,
 * disabled client), the save flow (validation errors, unknown-user
 * warnings, save result handling), dirty-state close confirmation, and the
 * panel callbacks that mutate the policy (default effect, client/tool rule
 * add/update/delete and the subject-value reset rule).
 *
 * The client and tool panels are stubbed: their props are captured and
 * driver buttons expose the callbacks so policy mutations can be driven
 * deterministically.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";

const apiMocks = vi.hoisted(() => ({
  getMCPPolicy: vi.fn(),
  listChannelTypes: vi.fn(),
  listMCPAccessPrincipals: vi.fn(),
  listMCPTools: vi.fn(),
}));

vi.mock("../../../../api", () => ({ default: apiMocks }));

const messageMocks = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  info: vi.fn(),
}));

vi.mock("../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: messageMocks }),
}));

// The t function must be a stable reference: MCPAccessModal lists it in a
// useEffect dependency array, and a fresh function per render would re-run
// the load effect forever.
const stableT = vi.hoisted(() => (key: string) => key);

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: stableT,
    i18n: { resolvedLanguage: "en", changeLanguage: vi.fn(), language: "en" },
  }),
}));

const confirmSpy = vi.hoisted(() => vi.fn());
const clientPanelProps = vi.hoisted(() => ({ current: null as any }));
const toolPanelProps = vi.hoisted(() => ({ current: null as any }));

// The design package's Modal is a plain container here; the imperative
// confirm is captured via a spy.
vi.mock("@agentscope-ai/design", () => {
  const Modal = ({
    open,
    children,
    title,
    footer,
  }: {
    open?: boolean;
    children?: React.ReactNode;
    title?: React.ReactNode;
    footer?: React.ReactNode;
  }) =>
    open
      ? React.createElement(
          "div",
          { "data-testid": "mcp-modal" },
          React.createElement("div", null, title),
          children,
          footer,
        )
      : null;
  (Modal as any).confirm = confirmSpy;

  const Button = ({
    children,
    onClick,
    disabled,
    loading,
  }: {
    children?: React.ReactNode;
    onClick?: () => void;
    disabled?: boolean;
    loading?: boolean;
  }) =>
    React.createElement(
      "button",
      { onClick, disabled: disabled || loading },
      children,
    );

  const Empty = ({ description }: { description?: React.ReactNode }) =>
    React.createElement("div", { "data-testid": "mcp-empty" }, description);

  return { Modal, Button, Empty };
});

vi.mock("./MCPAccessClientPanel", () => ({
  MCPAccessClientPanel: (props: any) => {
    clientPanelProps.current = props;
    return React.createElement(
      "div",
      { "data-testid": "client-panel" },
      React.createElement(
        "button",
        { onClick: () => props.setDefaultEffect("allow") },
        "set-default-allow",
      ),
      React.createElement(
        "button",
        { onClick: () => props.addClientAccessRule() },
        "add-client-rule",
      ),
      props.policy.client_overrides.length > 0 &&
        React.createElement(
          "button",
          {
            onClick: () =>
              props.updateClientRule(props.policy.client_overrides[0], {
                subject_type: "user",
              }),
          },
          "patch-client-rule",
        ),
      props.policy.client_overrides.length > 0 &&
        React.createElement(
          "button",
          {
            onClick: () =>
              props.setClientRuleEffect(
                props.policy.client_overrides[0],
                "deny",
              ),
          },
          "set-client-rule-effect",
        ),
      props.policy.client_overrides.length > 0 &&
        React.createElement(
          "button",
          {
            onClick: () =>
              props.deleteClientRule(props.policy.client_overrides[0]),
          },
          "delete-client-rule",
        ),
    );
  },
}));

vi.mock("./MCPAccessToolPanel", () => ({
  MCPAccessToolPanel: (props: any) => {
    toolPanelProps.current = props;
    const firstRules = props.groups[0]?.rules ?? [];
    return React.createElement(
      "div",
      { "data-testid": "tool-panel" },
      React.createElement(
        "button",
        {
          onClick: () =>
            props.setToolDefaultEffect(props.groups[0].toolName, "ask"),
        },
        "set-tool-default",
      ),
      React.createElement(
        "button",
        { onClick: () => props.addRule(props.groups[0].toolName) },
        "add-tool-rule",
      ),
      firstRules.length > 0 &&
        React.createElement(
          "button",
          {
            onClick: () =>
              props.updateRule(firstRules[0], { subject_type: "user" }),
          },
          "patch-tool-rule",
        ),
      firstRules.length > 0 &&
        React.createElement(
          "button",
          { onClick: () => props.setRuleEffect(firstRules[0], "deny") },
          "set-tool-rule-effect",
        ),
      firstRules.length > 0 &&
        React.createElement(
          "button",
          { onClick: () => props.deleteRule(firstRules[0]) },
          "delete-tool-rule",
        ),
    );
  },
}));

import { MCPAccessModal } from "./MCPAccessModal";

function makePolicy(overrides: Record<string, unknown> = {}) {
  return {
    default_effect: "deny",
    client_overrides: [],
    tool_defaults: [],
    tool_overrides: [],
    unmanaged_rules_count: 0,
    ...overrides,
  };
}

function makeClient(overrides: Record<string, unknown> = {}) {
  return {
    key: "fs-client",
    name: "Filesystem",
    description: "",
    enabled: true,
    transport: "stdio",
    url: "",
    headers: {},
    ...overrides,
  };
}

function makeTool(name: string) {
  return { name, description: `desc ${name}`, enabled: true, input_schema: {} };
}

function setupDefaultMocks() {
  apiMocks.getMCPPolicy.mockResolvedValue(makePolicy());
  apiMocks.listChannelTypes.mockResolvedValue(["console", "myplugin"]);
  apiMocks.listMCPAccessPrincipals.mockResolvedValue([]);
  apiMocks.listMCPTools.mockResolvedValue([
    makeTool("read_file"),
    makeTool("write_file"),
  ]);
}

function renderModal(
  client = makeClient(),
  onSave = vi.fn().mockResolvedValue(true),
) {
  const onClose = vi.fn();
  render(
    <MCPAccessModal
      client={client as never}
      open
      onClose={onClose}
      onSave={onSave}
    />,
  );
  return { onClose, onSave };
}

describe("MCPAccessModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clientPanelProps.current = null;
    toolPanelProps.current = null;
    setupDefaultMocks();
  });

  it("loads the policy and tools and renders both panels", async () => {
    renderModal();
    await waitFor(() =>
      expect(apiMocks.getMCPPolicy).toHaveBeenCalledWith("fs-client"),
    );
    expect(screen.getByText("Filesystem - mcp.tools")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("client-panel")).toBeInTheDocument();
      expect(screen.getByTestId("tool-panel")).toBeInTheDocument();
    });
    expect(toolPanelProps.current.groups.map((g: any) => g.toolName)).toEqual([
      "read_file",
      "write_file",
    ]);
    // Channel values merge the built-ins with the available channel types.
    expect(clientPanelProps.current.channelSourceValues).toContain("myplugin");
    expect(clientPanelProps.current.channelSourceValues).toContain("console");
    expect(clientPanelProps.current.effectLabel("allow")).toBe(
      "mcp.access.effect.allow",
    );
  });

  it("shows the spinner while the policy is loading and disables save", async () => {
    apiMocks.getMCPPolicy.mockReturnValue(new Promise(() => {}));
    renderModal();
    await waitFor(() =>
      expect(document.querySelector(".ant-spin")).toBeInTheDocument(),
    );
    expect(screen.getByText("common.save")).toBeDisabled();
  });

  it("shows the load error and disables save when the policy fetch fails", async () => {
    apiMocks.getMCPPolicy.mockRejectedValue(new Error("down"));
    renderModal();
    await waitFor(() =>
      expect(screen.getByText("mcp.access.loadError")).toBeInTheDocument(),
    );
    expect(screen.getByText("common.save")).toBeDisabled();
    expect(screen.queryByTestId("client-panel")).not.toBeInTheDocument();
  });

  it("flags disabled clients and skips tool loading", async () => {
    renderModal(makeClient({ enabled: false }));
    await waitFor(() =>
      expect(screen.getByText("mcp.access.disabledTools")).toBeInTheDocument(),
    );
    expect(apiMocks.listMCPTools).not.toHaveBeenCalled();
    expect(screen.queryByTestId("tool-panel")).not.toBeInTheDocument();
  });

  it("shows the tool load failure message from the error", async () => {
    apiMocks.listMCPTools.mockRejectedValue(new Error("boom"));
    renderModal();
    await waitFor(() => expect(screen.getByText("boom")).toBeInTheDocument());
    expect(screen.getByTestId("client-panel")).toBeInTheDocument();
  });

  it("falls back to the generic tool error when the message is empty", async () => {
    apiMocks.listMCPTools.mockRejectedValue(new Error(""));
    renderModal();
    await waitFor(() =>
      expect(screen.getByText("mcp.toolsLoadError")).toBeInTheDocument(),
    );
  });

  it("keeps loading principals when the channel type listing fails", async () => {
    apiMocks.listChannelTypes.mockRejectedValue(new Error("nope"));
    apiMocks.listMCPAccessPrincipals.mockResolvedValue([
      {
        source_type: "channel",
        source_value: "console",
        subject_type: "user",
        subject_value: "alice",
        label: "alice",
      },
    ]);
    renderModal();
    await waitFor(() =>
      expect(screen.getByTestId("client-panel")).toBeInTheDocument(),
    );
    // Defaults remain available and principals still load.
    expect(clientPanelProps.current.channelSourceValues).toContain("telegram");
    expect(clientPanelProps.current.principalOptions).toHaveLength(1);
  });

  it("ignores principal load failures", async () => {
    apiMocks.listMCPAccessPrincipals.mockRejectedValue(new Error("nope"));
    renderModal();
    await waitFor(() =>
      expect(screen.getByTestId("client-panel")).toBeInTheDocument(),
    );
    expect(clientPanelProps.current.principalOptions).toEqual([]);
    expect(messageMocks.error).not.toHaveBeenCalled();
  });

  it("shows the empty state when there are no tools or rules", async () => {
    apiMocks.listMCPTools.mockResolvedValue([]);
    renderModal();
    await waitFor(() =>
      expect(screen.getByTestId("mcp-empty")).toHaveTextContent("mcp.noTools"),
    );
    expect(screen.queryByTestId("tool-panel")).not.toBeInTheDocument();
  });

  it("saves a valid policy and closes on success", async () => {
    const user = userEvent.setup();
    const { onClose, onSave } = renderModal();
    await waitFor(() =>
      expect(screen.getByTestId("client-panel")).toBeInTheDocument(),
    );

    await user.click(screen.getByText("common.save"));
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith(
        expect.objectContaining({ default_effect: "deny" }),
      ),
    );
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("blocks saving when a user rule misses its value", async () => {
    apiMocks.getMCPPolicy.mockResolvedValue(
      makePolicy({
        client_overrides: [
          {
            source_type: "channel",
            source_value: "console",
            subject_type: "user",
            subject_value: "",
            effect: "allow",
          },
        ],
      }),
    );
    const user = userEvent.setup();
    const { onSave } = renderModal();
    await waitFor(() =>
      expect(screen.getByTestId("client-panel")).toBeInTheDocument(),
    );

    await user.click(screen.getByText("common.save"));
    await waitFor(() =>
      expect(messageMocks.error).toHaveBeenCalledWith(
        "mcp.access.validation.missingUserValue",
      ),
    );
    expect(onSave).not.toHaveBeenCalled();
  });

  it("warns about unknown user values but still saves", async () => {
    apiMocks.getMCPPolicy.mockResolvedValue(
      makePolicy({
        client_overrides: [
          {
            source_type: "channel",
            source_value: "console",
            subject_type: "user",
            subject_value: "unknown-user",
            effect: "allow",
          },
        ],
      }),
    );
    apiMocks.listMCPAccessPrincipals.mockResolvedValue([
      {
        source_type: "channel",
        source_value: "console",
        subject_type: "user",
        subject_value: "known-user",
        label: "known-user",
      },
    ]);
    const user = userEvent.setup();
    const { onSave } = renderModal();
    await waitFor(() =>
      expect(screen.getByTestId("client-panel")).toBeInTheDocument(),
    );

    await user.click(screen.getByText("common.save"));
    await waitFor(() =>
      expect(messageMocks.warning).toHaveBeenCalledWith(
        "mcp.access.validation.unknownUserValue",
      ),
    );
    await waitFor(() => expect(onSave).toHaveBeenCalled());
  });

  it("keeps the modal open when onSave reports a failure", async () => {
    const onSave = vi.fn().mockResolvedValue(false);
    const user = userEvent.setup();
    const { onClose } = renderModal(makeClient(), onSave);
    await waitFor(() =>
      expect(screen.getByTestId("client-panel")).toBeInTheDocument(),
    );

    await user.click(screen.getByText("common.save"));
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onClose).not.toHaveBeenCalled();
    // Saving state resets so the button becomes usable again.
    expect(screen.getByText("common.save")).toBeEnabled();
  });

  it("closes directly when there are no changes", async () => {
    const user = userEvent.setup();
    const { onClose } = renderModal();
    await waitFor(() =>
      expect(screen.getByTestId("client-panel")).toBeInTheDocument(),
    );

    await user.click(screen.getByText("common.cancel"));
    expect(onClose).toHaveBeenCalled();
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  it("asks for confirmation before discarding unsaved changes", async () => {
    const user = userEvent.setup();
    const { onClose } = renderModal();
    await waitFor(() =>
      expect(screen.getByTestId("client-panel")).toBeInTheDocument(),
    );

    // Mutate the policy so the modal becomes dirty.
    await user.click(screen.getByText("set-default-allow"));
    await waitFor(() =>
      expect(clientPanelProps.current.policy.default_effect).toBe("allow"),
    );

    await user.click(screen.getByText("common.cancel"));
    expect(onClose).not.toHaveBeenCalled();
    expect(confirmSpy).toHaveBeenCalledWith(
      expect.objectContaining({ title: "mcp.access.discardTitle" }),
    );

    // Confirming the discard closes the modal.
    const call = confirmSpy.mock.calls[confirmSpy.mock.calls.length - 1][0];
    call.onOk();
    expect(onClose).toHaveBeenCalled();
  });

  it("adds a client access rule through the panel", async () => {
    const user = userEvent.setup();
    renderModal();
    await waitFor(() =>
      expect(screen.getByTestId("client-panel")).toBeInTheDocument(),
    );

    await user.click(screen.getByText("add-client-rule"));
    await waitFor(() =>
      expect(clientPanelProps.current.policy.client_overrides).toHaveLength(1),
    );
  });

  it("resets the subject value when switching a client rule subject type", async () => {
    apiMocks.getMCPPolicy.mockResolvedValue(
      makePolicy({
        client_overrides: [
          {
            source_type: "channel",
            source_value: "console",
            subject_type: "all",
            subject_value: "",
            effect: "allow",
          },
        ],
      }),
    );
    const user = userEvent.setup();
    renderModal();
    await waitFor(() =>
      expect(screen.getByTestId("client-panel")).toBeInTheDocument(),
    );

    await user.click(screen.getByText("patch-client-rule"));
    await waitFor(() => {
      const rule = clientPanelProps.current.policy.client_overrides[0];
      expect(rule.subject_type).toBe("user");
      expect(rule.subject_value).toBe("");
    });
  });

  it("updates and deletes client rules through the panel", async () => {
    apiMocks.getMCPPolicy.mockResolvedValue(
      makePolicy({
        client_overrides: [
          {
            source_type: "channel",
            source_value: "console",
            subject_type: "all",
            subject_value: "",
            effect: "allow",
          },
        ],
      }),
    );
    const user = userEvent.setup();
    renderModal();
    await waitFor(() =>
      expect(screen.getByTestId("client-panel")).toBeInTheDocument(),
    );

    await user.click(screen.getByText("set-client-rule-effect"));
    await waitFor(() =>
      expect(clientPanelProps.current.policy.client_overrides[0].effect).toBe(
        "deny",
      ),
    );

    await user.click(screen.getByText("delete-client-rule"));
    await waitFor(() =>
      expect(clientPanelProps.current.policy.client_overrides).toHaveLength(0),
    );
  });

  it("sets a per-tool default effect through the panel", async () => {
    const user = userEvent.setup();
    renderModal();
    await waitFor(() =>
      expect(screen.getByTestId("tool-panel")).toBeInTheDocument(),
    );

    await user.click(screen.getByText("set-tool-default"));
    await waitFor(() =>
      expect(toolPanelProps.current.groups[0]).toMatchObject({
        toolName: "read_file",
        defaultEffect: "ask",
        hasExplicitDefault: true,
      }),
    );
  });

  it("adds, patches and removes tool rules through the panel", async () => {
    const user = userEvent.setup();
    renderModal();
    await waitFor(() =>
      expect(screen.getByTestId("tool-panel")).toBeInTheDocument(),
    );

    await user.click(screen.getByText("add-tool-rule"));
    await waitFor(() =>
      expect(toolPanelProps.current.groups[0].rules).toHaveLength(1),
    );

    // Patching the subject type resets the subject value (withRuleDefaults).
    await user.click(screen.getByText("patch-tool-rule"));
    await waitFor(() => {
      const rule = toolPanelProps.current.groups[0].rules[0];
      expect(rule.subject_type).toBe("user");
      expect(rule.subject_value).toBe("");
    });

    await user.click(screen.getByText("delete-tool-rule"));
    await waitFor(() =>
      expect(toolPanelProps.current.groups[0].rules).toHaveLength(0),
    );
  });

  it("merges saved channel rules into the channel source values", async () => {
    apiMocks.getMCPPolicy.mockResolvedValue(
      makePolicy({
        client_overrides: [
          {
            source_type: "channel",
            source_value: "legacychan",
            subject_type: "all",
            subject_value: "",
            effect: "allow",
          },
        ],
      }),
    );
    renderModal();
    await waitFor(() =>
      expect(screen.getByTestId("client-panel")).toBeInTheDocument(),
    );
    expect(clientPanelProps.current.channelSourceValues).toContain(
      "legacychan",
    );
  });
});
