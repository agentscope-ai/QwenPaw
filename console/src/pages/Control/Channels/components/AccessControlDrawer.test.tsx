vi.mock("@/components/interaction/SettingsDrawer", () => ({
  SettingsDrawer: ({
    children,
    title,
    open,
  }: {
    children: React.ReactNode;
    title: React.ReactNode;
    open: boolean;
  }) =>
    open ? (
      <section data-testid="acl-drawer">
        <h2>{title}</h2>
        {children}
      </section>
    ) : null,
}));
// @vitest-environment jsdom
/**
 * AccessControlDrawer — channel access control management. Covers ACL
 * loading with channel auto-selection, the empty/silent-failure states,
 * whitelist/blacklist tab switching, adding users through the modal
 * (with validation, trimming and failure handling), single and batch
 * removal, editable username/remark persistence, and the channel
 * selector behaviour.
 *
 * antd Drawer/Table/Tabs/Modal/Select/Popconfirm are stubbed into
 * queryable DOM (same approach as MailAccessControlDrawer tests) so cell
 * renders and action handlers execute under test.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  act,
  screen,
  fireEvent,
  waitFor,
  render,
} from "@testing-library/react";
import React from "react";

const mocks = vi.hoisted(() => ({
  getAclAll: vi.fn(),
  addAclWhitelist: vi.fn(),
  addAclBlacklist: vi.fn(),
  removeAclWhitelist: vi.fn(),
  removeAclBlacklist: vi.fn(),
  updateAclRemark: vi.fn(),
  updateUsername: vi.fn(),
  messageSuccess: vi.fn(),
  messageError: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key}:${JSON.stringify(opts)}` : key,
    i18n: { resolvedLanguage: "en", changeLanguage: vi.fn(), language: "en" },
  }),
}));

vi.mock("../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: {
      success: mocks.messageSuccess,
      error: mocks.messageError,
      info: vi.fn(),
      warning: vi.fn(),
    },
  }),
}));

vi.mock("../../../../api/modules/accessControl", () => ({
  accessControlApi: {
    getAclAll: (...a: unknown[]) => mocks.getAclAll(...a),
    addAclWhitelist: (...a: unknown[]) => mocks.addAclWhitelist(...a),
    addAclBlacklist: (...a: unknown[]) => mocks.addAclBlacklist(...a),
    removeAclWhitelist: (...a: unknown[]) => mocks.removeAclWhitelist(...a),
    removeAclBlacklist: (...a: unknown[]) => mocks.removeAclBlacklist(...a),
    updateAclRemark: (...a: unknown[]) => mocks.updateAclRemark(...a),
    updateUsername: (...a: unknown[]) => mocks.updateUsername(...a),
  },
}));

vi.mock("@ant-design/icons", () => ({
  DeleteOutlined: () => React.createElement("span"),
  PlusOutlined: () => React.createElement("span"),
}));

// antd stubs: Drawer renders inline; Table renders rows via column render
// functions so cell logic executes; Tabs/Modal/Select/Popconfirm are
// minimal but functional for the flows under test.
vi.mock("antd", () => {
  const Drawer = ({
    open,
    children,
    title,
  }: {
    open?: boolean;
    children?: React.ReactNode;
    title?: React.ReactNode;
  }) =>
    open
      ? React.createElement(
          "div",
          { "data-testid": "acl-drawer" },
          React.createElement("div", null, title),
          children,
        )
      : null;

  const Table = ({
    dataSource = [],
    columns = [],
    rowKey,
    rowSelection,
    locale,
  }: {
    dataSource?: Array<Record<string, unknown>>;
    columns?: Array<{
      key: string;
      dataIndex?: string;
      render?: (value: unknown, record: unknown) => React.ReactNode;
    }>;
    rowKey?: (record: unknown) => string;
    rowSelection?: {
      selectedRowKeys: string[];
      onChange: (keys: string[]) => void;
    };
    locale?: { emptyText?: React.ReactNode };
  }) =>
    dataSource.length === 0
      ? React.createElement(
          "div",
          { "data-testid": "acl-table-empty" },
          locale?.emptyText,
        )
      : React.createElement(
          "div",
          { "data-testid": "acl-table" },
          dataSource.map((record) => {
            const key = rowKey ? rowKey(record) : String(record);
            return React.createElement(
              "div",
              { key, "data-row-key": key },
              rowSelection &&
                React.createElement("input", {
                  type: "checkbox",
                  "data-testid": `row-select-${key}`,
                  checked: rowSelection.selectedRowKeys.includes(key),
                  onChange: () =>
                    rowSelection.onChange(
                      rowSelection.selectedRowKeys.includes(key)
                        ? rowSelection.selectedRowKeys.filter((k) => k !== key)
                        : [...rowSelection.selectedRowKeys, key],
                    ),
                }),
              columns.map((col) =>
                React.createElement(
                  "span",
                  { key: col.key, "data-col": col.key },
                  col.render
                    ? col.render(record[col.dataIndex ?? ""], record)
                    : String(record[col.dataIndex ?? ""] ?? ""),
                ),
              ),
            );
          }),
        );

  const Tabs = ({
    activeKey,
    onChange,
    items = [],
    tabBarExtraContent,
  }: {
    activeKey?: string;
    onChange?: (k: string) => void;
    items?: Array<{ key: string; label: React.ReactNode }>;
    tabBarExtraContent?: React.ReactNode;
  }) =>
    React.createElement(
      "div",
      null,
      items.map((item) =>
        React.createElement(
          "button",
          {
            key: item.key,
            "data-testid": `tab-${item.key}`,
            "data-active": item.key === activeKey,
            onClick: () => onChange?.(item.key),
          },
          item.label,
        ),
      ),
      tabBarExtraContent,
    );

  const Modal = ({
    open,
    children,
    onOk,
    onCancel,
    title,
    confirmLoading,
    okButtonProps,
  }: {
    open?: boolean;
    children?: React.ReactNode;
    onOk?: () => void;
    onCancel?: () => void;
    title?: React.ReactNode;
    confirmLoading?: boolean;
    okButtonProps?: { disabled?: boolean };
  }) =>
    open
      ? React.createElement(
          "div",
          { "data-testid": "acl-modal" },
          React.createElement("div", null, title),
          children,
          React.createElement(
            "button",
            {
              "data-testid": "acl-modal-ok",
              "data-loading": confirmLoading ? "true" : "false",
              onClick: onOk,
              disabled: okButtonProps?.disabled || confirmLoading,
            },
            "ok",
          ),
          React.createElement(
            "button",
            { "data-testid": "acl-modal-cancel", onClick: onCancel },
            "cancel",
          ),
        )
      : null;

  const Popconfirm = ({
    children,
    onConfirm,
    disabled,
  }: {
    children?: React.ReactNode;
    onConfirm?: () => void;
    disabled?: boolean;
  }) =>
    React.createElement(
      "span",
      {
        onClick: disabled ? undefined : onConfirm,
        "data-testid": "popconfirm-wrap",
      },
      children,
    );

  const Select = ({
    value,
    onChange,
    options = [],
    disabled,
    placeholder,
  }: {
    value?: string | null;
    onChange?: (value: string) => void;
    options?: Array<{ value: string; label: React.ReactNode }>;
    disabled?: boolean;
    placeholder?: string;
  }) =>
    React.createElement(
      "select",
      {
        "data-testid": "acl-select",
        "aria-label": placeholder,
        value: value ?? "",
        disabled,
        onChange: (event: React.ChangeEvent<HTMLSelectElement>) =>
          onChange?.(event.target.value),
      },
      React.createElement("option", { value: "", disabled: true }, ""),
      options.map((option) =>
        React.createElement(
          "option",
          { key: option.value, value: option.value },
          option.label,
        ),
      ),
    );

  const Input = ({
    value,
    onChange,
    placeholder,
  }: {
    value?: string;
    onChange?: (e: { target: { value: string } }) => void;
    placeholder?: string;
  }) => React.createElement("input", { value, onChange, placeholder });

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

  const Space = ({ children }: { children?: React.ReactNode }) =>
    React.createElement("div", null, children);

  const Typography = {
    Text: ({
      children,
      editable,
      copyable,
    }: {
      children?: React.ReactNode;
      editable?: { onChange?: (value: string) => void; text?: string };
      copyable?: unknown;
    }) =>
      React.createElement(
        "span",
        null,
        children,
        editable &&
          React.createElement(
            "button",
            {
              "data-testid": "editable-trigger",
              onClick: () => editable.onChange?.("edited-value"),
            },
            "edit",
          ),
        copyable ? React.createElement("span", null, "copy") : null,
      ),
  };

  return {
    Drawer,
    Table,
    Tabs,
    Modal,
    Popconfirm,
    Select,
    Input,
    Button,
    Space,
    Typography,
  };
});

import { AccessControlDrawer } from "./AccessControlDrawer";

function makeAclAll() {
  return {
    dingtalk: {
      whitelist: {
        "u-1": { remark: "boss", username: "alice" },
        "u-2": { remark: "", username: "" },
      },
      blacklist: { "b-1": { remark: "spammer", username: "bob" } },
      pending: [],
    },
    telegram: {
      whitelist: {},
      blacklist: {},
      pending: [],
    },
  };
}

function renderDrawer(
  open = true,
  options: {
    canMutate?: (ownerAgentId: string) => boolean;
    onStale?: () => void;
  } = {},
) {
  const onClose = vi.fn();
  const onStale = options.onStale ?? vi.fn();
  render(
    <AccessControlDrawer
      open={open}
      ownerAgentId="agent-a"
      canMutate={options.canMutate ?? (() => true)}
      onStale={onStale}
      onClose={onClose}
    />,
  );
  return { onClose, onStale };
}

describe("AccessControlDrawer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getAclAll.mockResolvedValue(makeAclAll());
    mocks.addAclWhitelist.mockResolvedValue({});
    mocks.addAclBlacklist.mockResolvedValue({});
    mocks.removeAclWhitelist.mockResolvedValue({});
    mocks.removeAclBlacklist.mockResolvedValue({});
    mocks.updateAclRemark.mockResolvedValue({});
    mocks.updateUsername.mockResolvedValue({});
  });

  it("renders nothing while closed", () => {
    renderDrawer(false);
    expect(screen.queryByTestId("acl-drawer")).not.toBeInTheDocument();
    expect(mocks.getAclAll).not.toHaveBeenCalled();
  });

  it("loads ACLs and auto-selects the first channel", async () => {
    renderDrawer();
    await waitFor(() => expect(mocks.getAclAll).toHaveBeenCalled());
    await waitFor(() => {
      const select = screen.getByTestId("acl-select");
      expect((select as HTMLSelectElement).value).toBe("dingtalk");
    });
    expect(screen.getByText("alice")).toBeInTheDocument();
    expect(screen.getByText("boss")).toBeInTheDocument();
    // Empty username/remark render as a dash placeholder.
    expect(screen.getAllByText("-").length).toBeGreaterThan(0);
  });

  it("disables the add button and select when no channels exist", async () => {
    mocks.getAclAll.mockResolvedValue({});
    renderDrawer();
    await waitFor(() => expect(mocks.getAclAll).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByTestId("acl-select")).toBeDisabled(),
    );
    expect(screen.getByText("channels.addUser")).toBeDisabled();
    expect(screen.getByText("channels.noWhitelistUsers")).toBeInTheDocument();
  });

  it("swallows ACL fetch failures silently", async () => {
    mocks.getAclAll.mockRejectedValue(new Error("down"));
    renderDrawer();
    await waitFor(() => expect(mocks.getAclAll).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByText("channels.noWhitelistUsers")).toBeInTheDocument(),
    );
    expect(mocks.messageError).not.toHaveBeenCalled();
  });

  it("keeps the selected channel across refetches while it exists", async () => {
    renderDrawer();
    await waitFor(() => expect(mocks.getAclAll).toHaveBeenCalled());
    await waitFor(() => {
      const select = screen.getByTestId("acl-select");
      expect((select as HTMLSelectElement).value).toBe("dingtalk");
    });
    // Switching the channel triggers a refetch; since the channel still
    // exists afterwards, the selection must be preserved.
    fireEvent.change(screen.getByTestId("acl-select"), {
      target: { value: "telegram" },
    });
    await waitFor(() => expect(mocks.getAclAll).toHaveBeenCalledTimes(3));
    expect((screen.getByTestId("acl-select") as HTMLSelectElement).value).toBe(
      "telegram",
    );
  });

  it("falls back to the first channel when the selected one disappears", async () => {
    renderDrawer();
    await waitFor(() => expect(mocks.getAclAll).toHaveBeenCalled());
    await waitFor(() => {
      expect(
        (screen.getByTestId("acl-select") as HTMLSelectElement).value,
      ).toBe("dingtalk");
    });

    // Switch to telegram; the refetch that switch triggers returns data
    // without telegram, so the selection must fall back to the first
    // available channel.
    mocks.getAclAll.mockResolvedValueOnce({
      dingtalk: makeAclAll().dingtalk,
    });
    fireEvent.change(screen.getByTestId("acl-select"), {
      target: { value: "telegram" },
    });
    await waitFor(() => {
      expect(
        (screen.getByTestId("acl-select") as HTMLSelectElement).value,
      ).toBe("dingtalk");
    });
  });

  it("adds a whitelist user through the modal with trimmed fields", async () => {
    renderDrawer();
    await waitFor(() => expect(mocks.getAclAll).toHaveBeenCalled());

    fireEvent.click(screen.getByText("channels.addUser"));
    fireEvent.change(
      screen.getByPlaceholderText("channels.addUserPlaceholder"),
      { target: { value: "  u-9  " } },
    );
    fireEvent.change(
      screen.getByPlaceholderText("channels.usernamePlaceholder"),
      { target: { value: " carol " } },
    );
    fireEvent.change(
      screen.getByPlaceholderText("channels.remarkPlaceholder"),
      { target: { value: " new user " } },
    );

    fireEvent.click(screen.getByTestId("acl-modal-ok"));
    await waitFor(() =>
      expect(mocks.addAclWhitelist).toHaveBeenCalledWith([
        {
          channel: "dingtalk",
          user_id: "u-9",
          username: "carol",
          remark: "new user",
        },
      ]),
    );
    expect(mocks.messageSuccess).toHaveBeenCalledWith("channels.userAdded");
    // Modal closes and the form resets.
    await waitFor(() =>
      expect(screen.queryByTestId("acl-modal")).not.toBeInTheDocument(),
    );
  });

  it("submits one add request when OK is clicked twice", async () => {
    let resolveAdd!: () => void;
    const addRequest = new Promise<void>((resolve) => {
      resolveAdd = resolve;
    });
    mocks.addAclWhitelist.mockReturnValue(addRequest);
    renderDrawer();
    await waitFor(() => expect(mocks.getAclAll).toHaveBeenCalled());

    fireEvent.click(screen.getByText("channels.addUser"));
    fireEvent.change(
      screen.getByPlaceholderText("channels.addUserPlaceholder"),
      { target: { value: "u-once" } },
    );
    const ok = screen.getByTestId("acl-modal-ok");
    fireEvent.click(ok);
    fireEvent.click(ok);

    expect(mocks.addAclWhitelist).toHaveBeenCalledOnce();
    expect(ok).toBeDisabled();
    expect(ok).toHaveAttribute("data-loading", "true");

    await act(async () => {
      resolveAdd();
      await addRequest;
    });
    await waitFor(() =>
      expect(screen.queryByTestId("acl-modal")).not.toBeInTheDocument(),
    );
  });

  it("does not let agent A add completion clear agent B loading", async () => {
    let resolveAgentA!: () => void;
    let resolveAgentB!: () => void;
    const agentAAdd = new Promise<void>((resolve) => {
      resolveAgentA = resolve;
    });
    const agentBAdd = new Promise<void>((resolve) => {
      resolveAgentB = resolve;
    });
    mocks.addAclWhitelist
      .mockReturnValueOnce(agentAAdd)
      .mockReturnValueOnce(agentBAdd);

    let currentAgent = "agent-a";
    const drawer = (ownerAgentId: string) => (
      <AccessControlDrawer
        open
        ownerAgentId={ownerAgentId}
        canMutate={(owner) => owner === currentAgent}
        onStale={vi.fn()}
        onClose={vi.fn()}
      />
    );
    const view = render(drawer("agent-a"));
    await screen.findByText("alice");
    fireEvent.click(screen.getByText("channels.addUser"));
    fireEvent.change(
      screen.getByPlaceholderText("channels.addUserPlaceholder"),
      { target: { value: "u-a" } },
    );
    fireEvent.click(screen.getByTestId("acl-modal-ok"));

    currentAgent = "agent-b";
    view.rerender(drawer("agent-b"));
    await screen.findByText("alice");
    fireEvent.click(screen.getByText("channels.addUser"));
    fireEvent.change(
      screen.getByPlaceholderText("channels.addUserPlaceholder"),
      { target: { value: "u-b" } },
    );
    const agentBOk = screen.getByTestId("acl-modal-ok");
    fireEvent.click(agentBOk);
    expect(mocks.addAclWhitelist).toHaveBeenCalledTimes(2);
    expect(agentBOk).toHaveAttribute("data-loading", "true");

    await act(async () => {
      resolveAgentA();
      await agentAAdd;
    });
    expect(agentBOk).toBeDisabled();
    expect(agentBOk).toHaveAttribute("data-loading", "true");

    await act(async () => {
      resolveAgentB();
      await agentBAdd;
    });
    await waitFor(() =>
      expect(screen.queryByTestId("acl-modal")).not.toBeInTheDocument(),
    );
  });

  it("rejects captured add, remove, and edit callbacks after ownership changes", async () => {
    let currentAgent = "agent-a";
    const onStale = vi.fn();
    renderDrawer(true, {
      canMutate: (ownerAgentId) => currentAgent === ownerAgentId,
      onStale,
    });
    await waitFor(() => expect(mocks.getAclAll).toHaveBeenCalled());

    fireEvent.click(screen.getByText("channels.addUser"));
    fireEvent.change(
      screen.getByPlaceholderText("channels.addUserPlaceholder"),
      { target: { value: "u-stale" } },
    );
    const add = screen.getByTestId("acl-modal-ok");
    const row = screen.getByText("alice").closest("[data-row-key]")!;
    const remove = row.querySelector("[data-testid='popconfirm-wrap'] button")!;
    const edit = row.querySelector(
      "[data-col='remark'] [data-testid='editable-trigger']",
    )!;

    currentAgent = "agent-b";
    fireEvent.click(add);
    fireEvent.click(remove);
    fireEvent.click(edit);

    expect(mocks.addAclWhitelist).not.toHaveBeenCalled();
    expect(mocks.removeAclWhitelist).not.toHaveBeenCalled();
    expect(mocks.updateAclRemark).not.toHaveBeenCalled();
    expect(onStale).toHaveBeenCalledTimes(3);
  });

  it("does not let agent A removal clear agent B removal loading", async () => {
    let resolveAgentA!: () => void;
    let resolveAgentB!: () => void;
    const agentARemoval = new Promise<void>((resolve) => {
      resolveAgentA = resolve;
    });
    const agentBRemoval = new Promise<void>((resolve) => {
      resolveAgentB = resolve;
    });
    mocks.removeAclWhitelist
      .mockReturnValueOnce(agentARemoval)
      .mockReturnValueOnce(agentBRemoval);

    let currentAgent = "agent-a";
    const drawer = (ownerAgentId: string) => (
      <AccessControlDrawer
        open
        ownerAgentId={ownerAgentId}
        canMutate={(owner) => owner === currentAgent}
        onStale={vi.fn()}
        onClose={vi.fn()}
      />
    );
    const view = render(drawer("agent-a"));
    await screen.findByText("alice");
    const agentARow = screen.getByText("alice").closest("[data-row-key]")!;
    fireEvent.click(
      agentARow.querySelector("[data-testid='popconfirm-wrap'] button")!,
    );
    expect(mocks.removeAclWhitelist).toHaveBeenCalledTimes(1);

    currentAgent = "agent-b";
    view.rerender(drawer("agent-b"));
    await screen.findByText("alice");
    const agentBRow = screen.getByText("alice").closest("[data-row-key]")!;
    const agentBRemove = agentBRow.querySelector(
      "[data-testid='popconfirm-wrap'] button",
    )!;
    fireEvent.click(agentBRemove);
    expect(mocks.removeAclWhitelist).toHaveBeenCalledTimes(2);
    expect(agentBRemove).toBeDisabled();
    fireEvent.click(agentBRemove);
    expect(mocks.removeAclWhitelist).toHaveBeenCalledTimes(2);

    await act(async () => {
      resolveAgentA();
      await agentARemoval;
    });
    expect(agentBRemove).toBeDisabled();

    await act(async () => {
      resolveAgentB();
      await agentBRemoval;
    });
    await waitFor(() => expect(agentBRemove).toBeEnabled());
  });

  it("keeps the OK button disabled until a user id is typed", async () => {
    renderDrawer();
    await waitFor(() => expect(mocks.getAclAll).toHaveBeenCalled());
    fireEvent.click(screen.getByText("channels.addUser"));
    expect(screen.getByTestId("acl-modal-ok")).toBeDisabled();
    fireEvent.change(
      screen.getByPlaceholderText("channels.addUserPlaceholder"),
      { target: { value: "u-1" } },
    );
    expect(screen.getByTestId("acl-modal-ok")).toBeEnabled();
  });

  it("cancels the add modal and clears the draft fields", async () => {
    renderDrawer();
    await waitFor(() => expect(mocks.getAclAll).toHaveBeenCalled());
    fireEvent.click(screen.getByText("channels.addUser"));
    fireEvent.change(
      screen.getByPlaceholderText("channels.addUserPlaceholder"),
      { target: { value: "u-1" } },
    );
    fireEvent.click(screen.getByTestId("acl-modal-cancel"));
    await waitFor(() =>
      expect(screen.queryByTestId("acl-modal")).not.toBeInTheDocument(),
    );
    expect(mocks.addAclWhitelist).not.toHaveBeenCalled();
  });

  it("adds to the blacklist when the blacklist tab is active", async () => {
    renderDrawer();
    await waitFor(() => expect(mocks.getAclAll).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("tab-blacklist"));
    await waitFor(() => expect(screen.getByText("bob")).toBeInTheDocument());

    fireEvent.click(screen.getByText("channels.addUser"));
    fireEvent.change(
      screen.getByPlaceholderText("channels.addUserPlaceholder"),
      { target: { value: "u-bad" } },
    );
    fireEvent.click(screen.getByTestId("acl-modal-ok"));
    await waitFor(() =>
      expect(mocks.addAclBlacklist).toHaveBeenCalledWith([
        {
          channel: "dingtalk",
          user_id: "u-bad",
          username: "",
          remark: "",
        },
      ]),
    );
  });

  it("reports add failures", async () => {
    mocks.addAclWhitelist.mockRejectedValue(new Error("nope"));
    renderDrawer();
    await waitFor(() => expect(mocks.getAclAll).toHaveBeenCalled());
    fireEvent.click(screen.getByText("channels.addUser"));
    fireEvent.change(
      screen.getByPlaceholderText("channels.addUserPlaceholder"),
      { target: { value: "u-9" } },
    );
    fireEvent.click(screen.getByTestId("acl-modal-ok"));
    await waitFor(() =>
      expect(mocks.messageError).toHaveBeenCalledWith(
        "channels.operationFailed",
      ),
    );
  });

  it("removes a single user through the row popconfirm", async () => {
    renderDrawer();
    await waitFor(() => expect(mocks.getAclAll).toHaveBeenCalled());
    const row = screen.getByText("alice").closest("[data-row-key]");
    const popconfirm = row!.querySelector("[data-testid='popconfirm-wrap']");
    fireEvent.click(popconfirm!.querySelector("button")!);
    await waitFor(() =>
      expect(mocks.removeAclWhitelist).toHaveBeenCalledWith([
        { channel: "dingtalk", user_id: "u-1" },
      ]),
    );
    expect(mocks.messageSuccess).toHaveBeenCalledWith("channels.userRemoved");
  });

  it("removes from the blacklist on the blacklist tab", async () => {
    renderDrawer();
    await waitFor(() => expect(mocks.getAclAll).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("tab-blacklist"));
    await waitFor(() => expect(screen.getByText("bob")).toBeInTheDocument());
    const row = screen.getByText("bob").closest("[data-row-key]");
    const popconfirm = row!.querySelector("[data-testid='popconfirm-wrap']");
    fireEvent.click(popconfirm!.querySelector("button")!);
    await waitFor(() =>
      expect(mocks.removeAclBlacklist).toHaveBeenCalledWith([
        { channel: "dingtalk", user_id: "b-1" },
      ]),
    );
  });

  it("batch removes the selected rows and clears the selection", async () => {
    renderDrawer();
    await waitFor(() => expect(mocks.getAclAll).toHaveBeenCalled());

    fireEvent.click(screen.getByTestId("row-select-u-1"));
    fireEvent.click(screen.getByTestId("row-select-u-2"));
    expect(screen.getByText(/channels\.selectedCount/)).toBeInTheDocument();

    // The batch remove button lives in the toolbar, outside any table row;
    // row-level remove buttons share the same label, so scope by that.
    const batchButton = screen
      .getAllByText("channels.batchRemove")
      .find((el) => !el.closest("[data-row-key]"));
    const batchWrap = batchButton!.closest("[data-testid='popconfirm-wrap']");
    fireEvent.click(batchWrap!);
    await waitFor(() =>
      expect(mocks.removeAclWhitelist).toHaveBeenCalledWith([
        { channel: "dingtalk", user_id: "u-1" },
        { channel: "dingtalk", user_id: "u-2" },
      ]),
    );
    expect(mocks.messageSuccess).toHaveBeenCalledWith(
      expect.stringContaining("channels.batchSuccess"),
    );
  });

  it("keeps the batch remove button disabled without a selection", async () => {
    renderDrawer();
    await waitFor(() => expect(mocks.getAclAll).toHaveBeenCalled());
    const batchButton = screen
      .getAllByText("channels.batchRemove")
      .find((el) => !el.closest("[data-row-key]"));
    expect(batchButton!.closest("button")).toBeDisabled();
  });

  it("saves an edited remark and reflects it immediately", async () => {
    renderDrawer();
    await waitFor(() => expect(mocks.getAclAll).toHaveBeenCalled());
    // Find the editable trigger in the remark column of the boss row.
    const row = screen.getByText("alice").closest("[data-row-key]");
    const remarkCell = row!.querySelector("[data-col='remark']");
    fireEvent.click(
      remarkCell!.querySelector("[data-testid='editable-trigger']")!,
    );
    await waitFor(() =>
      expect(mocks.updateAclRemark).toHaveBeenCalledWith(
        "dingtalk",
        "u-1",
        "edited-value",
      ),
    );
    expect(screen.getByText("edited-value")).toBeInTheDocument();
  });

  it("saves an edited username", async () => {
    renderDrawer();
    await waitFor(() => expect(mocks.getAclAll).toHaveBeenCalled());
    const row = screen.getByText("boss").closest("[data-row-key]");
    const usernameCell = row!.querySelector("[data-col='username']");
    fireEvent.click(
      usernameCell!.querySelector("[data-testid='editable-trigger']")!,
    );
    await waitFor(() =>
      expect(mocks.updateUsername).toHaveBeenCalledWith(
        "dingtalk",
        "u-1",
        "edited-value",
      ),
    );
    expect(screen.getByText("edited-value")).toBeInTheDocument();
  });

  it.each([
    ["remark", "updateAclRemark"],
    ["username", "updateUsername"],
  ] as const)("deduplicates overlapping %s edits", async (column, apiName) => {
    let resolveEdit!: () => void;
    const editRequest = new Promise<void>((resolve) => {
      resolveEdit = resolve;
    });
    mocks[apiName].mockReturnValue(editRequest);
    renderDrawer();
    await screen.findByText("alice");
    const row = screen.getByText("alice").closest("[data-row-key]")!;
    const trigger = row.querySelector(
      `[data-col='${column}'] [data-testid='editable-trigger']`,
    )!;

    fireEvent.click(trigger);
    fireEvent.click(trigger);
    expect(mocks[apiName]).toHaveBeenCalledOnce();

    await act(async () => {
      resolveEdit();
      await editRequest;
    });
  });

  it("reports remark and username save failures", async () => {
    mocks.updateAclRemark.mockRejectedValue(new Error("nope"));
    renderDrawer();
    await waitFor(() => expect(mocks.getAclAll).toHaveBeenCalled());
    const row = screen.getByText("alice").closest("[data-row-key]");
    const remarkCell = row!.querySelector("[data-col='remark']");
    fireEvent.click(
      remarkCell!.querySelector("[data-testid='editable-trigger']")!,
    );
    await waitFor(() =>
      expect(mocks.messageError).toHaveBeenCalledWith(
        "channels.operationFailed",
      ),
    );
  });

  it("switching channels resets the selection and swaps the table", async () => {
    renderDrawer();
    await waitFor(() => expect(mocks.getAclAll).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("row-select-u-1"));
    expect(screen.getByText(/channels\.selectedCount/)).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("acl-select"), {
      target: { value: "telegram" },
    });
    expect(
      screen.queryByText(/channels\.selectedCount/),
    ).not.toBeInTheDocument();
    expect(screen.getByText("channels.noWhitelistUsers")).toBeInTheDocument();
  });

  it("resets the selection when switching tabs", async () => {
    renderDrawer();
    await waitFor(() => expect(mocks.getAclAll).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("row-select-u-1"));
    expect(screen.getByText(/channels\.selectedCount/)).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("tab-blacklist"));
    expect(
      screen.queryByText(/channels\.selectedCount/),
    ).not.toBeInTheDocument();
    // The blacklist tab shows the blacklist rows (bob), not the whitelist.
    expect(screen.getByText("bob")).toBeInTheDocument();
    expect(screen.queryByText("alice")).not.toBeInTheDocument();
  });
});
