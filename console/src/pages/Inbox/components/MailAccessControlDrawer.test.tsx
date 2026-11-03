// @vitest-environment jsdom
/**
 * MailAccessControlDrawer render tests — regression family: mail sender
 * approval workflow (approve/deny/dismiss + whitelist/blacklist CRUD).
 * antd Table/Drawer/Tabs are stubbed into queryable DOM so cell renders
 * and action handlers are exercised under test.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { renderWithProviders } from "@/test/common_setup";

// ---- Hoisted mocks ---------------------------------------------------------

const mocks = vi.hoisted(() => ({
  getMailPendingAll: vi.fn(),
  getMailAclAll: vi.fn(),
  getMailAgents: vi.fn(),
  approveMailPending: vi.fn(),
  denyMailPending: vi.fn(),
  dismissMailPending: vi.fn(),
  removeMailWhitelist: vi.fn(),
  removeMailBlacklist: vi.fn(),
  addMailWhitelist: vi.fn(),
  addMailBlacklist: vi.fn(),
  updateMailPendingRemark: vi.fn(),
  messageSuccess: vi.fn(),
  messageError: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: {
      success: mocks.messageSuccess,
      error: mocks.messageError,
      info: vi.fn(),
      warning: vi.fn(),
    },
  }),
}));

vi.mock("../../../api/modules/mailAccessControl", () => ({
  mailAccessControlApi: {
    getMailPendingAll: (...a: unknown[]) => mocks.getMailPendingAll(...a),
    getMailAclAll: (...a: unknown[]) => mocks.getMailAclAll(...a),
    getMailAgents: (...a: unknown[]) => mocks.getMailAgents(...a),
    approveMailPending: (...a: unknown[]) => mocks.approveMailPending(...a),
    denyMailPending: (...a: unknown[]) => mocks.denyMailPending(...a),
    dismissMailPending: (...a: unknown[]) => mocks.dismissMailPending(...a),
    removeMailWhitelist: (...a: unknown[]) => mocks.removeMailWhitelist(...a),
    removeMailBlacklist: (...a: unknown[]) => mocks.removeMailBlacklist(...a),
    addMailWhitelist: (...a: unknown[]) => mocks.addMailWhitelist(...a),
    addMailBlacklist: (...a: unknown[]) => mocks.addMailBlacklist(...a),
    updateMailPendingRemark: (...a: unknown[]) =>
      mocks.updateMailPendingRemark(...a),
  },
}));

vi.mock("lucide-react", () => {
  const make = (n: string) =>
    function Icon() {
      return React.createElement("span", { "data-testid": "icon-" + n });
    };
  return {
    Check: make("check"),
    Plus: make("plus"),
    Trash2: make("trash"),
    X: make("x"),
  };
});

// antd stubs: Drawer renders inline; Table renders rows via column render
// functions so cell logic executes; Tabs/Modal/Select/Popconfirm are
// minimal but functional for the flows under test.
vi.mock("antd", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("antd");
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
          { "data-testid": "mail-acl-drawer" },
          React.createElement("div", null, title),
          children,
        )
      : null;
  const Table = ({
    dataSource = [],
    columns = [],
    rowKey,
    rowSelection,
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
  }) =>
    React.createElement(
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
    okButtonProps,
  }: {
    open?: boolean;
    children?: React.ReactNode;
    onOk?: () => void;
    onCancel?: () => void;
    title?: React.ReactNode;
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
              onClick: onOk,
              disabled: okButtonProps?.disabled,
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
  }: {
    children?: React.ReactNode;
    onConfirm?: () => void;
  }) =>
    React.createElement(
      "span",
      { onClick: onConfirm, "data-testid": "popconfirm-wrap" },
      children,
    );
  const Select = ({ placeholder }: { placeholder?: string }) =>
    React.createElement("select", {
      "data-testid": "acl-select",
      title: placeholder,
    });
  const Typography = {
    Text: ({
      children,
      copyable,
    }: {
      children?: React.ReactNode;
      copyable?: unknown;
    }) =>
      React.createElement(
        "span",
        { "data-copyable": copyable ? "1" : undefined },
        children,
      ),
  };
  return {
    ...actual,
    Drawer,
    Table,
    Tabs,
    Modal,
    Popconfirm,
    Select,
    Typography,
  };
});

import { MailAccessControlDrawer } from "./MailAccessControlDrawer";

// ---- Fixtures --------------------------------------------------------------

const pendingEntry = {
  agent_id: "agent-a",
  sender_address: "news@blog.com",
  display_name: "Newsletter <news@blog.com>",
  subject: "Weekly digest",
  body_preview: "This week in…",
  timestamp: 1700000000,
  remark: "",
};

const aclData = {
  "agent-a": {
    whitelist: {
      "ok@mail.com": { display_name: "Ok Sender", remark: "trusted" },
    },
    blacklist: {
      "spam@mail.com": { display_name: "", remark: "" },
    },
  },
};

beforeEach(() => {
  mocks.getMailPendingAll.mockReset().mockResolvedValue([]);
  mocks.getMailAclAll.mockReset().mockResolvedValue({});
  mocks.getMailAgents.mockReset().mockResolvedValue({ agents: [] });
  mocks.approveMailPending.mockReset().mockResolvedValue({});
  mocks.denyMailPending.mockReset().mockResolvedValue({});
  mocks.dismissMailPending.mockReset().mockResolvedValue({});
  mocks.removeMailWhitelist.mockReset().mockResolvedValue({});
  mocks.removeMailBlacklist.mockReset().mockResolvedValue({});
  mocks.addMailWhitelist.mockReset().mockResolvedValue({});
  mocks.addMailBlacklist.mockReset().mockResolvedValue({});
  mocks.updateMailPendingRemark.mockReset().mockResolvedValue({});
  mocks.messageSuccess.mockClear();
  mocks.messageError.mockClear();
});

function renderDrawer(open = true) {
  const onClose = vi.fn();
  renderWithProviders(
    <MailAccessControlDrawer open={open} onClose={onClose} />,
  );
  return { onClose };
}

// ---- Tests -----------------------------------------------------------------

describe("MailAccessControlDrawer", () => {
  it("renders nothing when closed", () => {
    renderDrawer(false);
    expect(screen.queryByTestId("mail-acl-drawer")).toBeNull();
  });

  it("fetches pending, lists and mail agents on open", async () => {
    renderDrawer();
    await waitFor(() => {
      expect(mocks.getMailPendingAll).toHaveBeenCalled();
      expect(mocks.getMailAclAll).toHaveBeenCalled();
      expect(mocks.getMailAgents).toHaveBeenCalled();
    });
  });

  it("renders pending senders with parsed display names", async () => {
    mocks.getMailPendingAll.mockResolvedValue([pendingEntry]);
    renderDrawer();
    await waitFor(() => {
      expect(screen.getByText("news@blog.com")).toBeTruthy();
    });
    // "Newsletter <news@blog.com>" parses to the nickname "Newsletter"
    expect(screen.getByText("Newsletter")).toBeTruthy();
  });

  it("shows a dash for senders whose name equals their address", async () => {
    mocks.getMailPendingAll.mockResolvedValue([
      { ...pendingEntry, display_name: "news@blog.com" },
    ]);
    renderDrawer();
    await waitFor(() => {
      expect(screen.getByText("news@blog.com")).toBeTruthy();
    });
    expect(screen.getAllByText("-").length).toBeGreaterThan(0);
  });

  it("approves a pending sender and refreshes", async () => {
    mocks.getMailPendingAll.mockResolvedValue([pendingEntry]);
    renderDrawer();
    await waitFor(() => {
      expect(screen.getByText("inbox.approveSender")).toBeTruthy();
    });
    fireEvent.click(screen.getByText("inbox.approveSender"));
    await waitFor(() => {
      expect(mocks.approveMailPending).toHaveBeenCalledWith([
        { agent_id: "agent-a", address: "news@blog.com" },
      ]);
    });
    expect(mocks.messageSuccess).toHaveBeenCalledWith("inbox.approve");
  });

  it("denies a pending sender", async () => {
    mocks.getMailPendingAll.mockResolvedValue([pendingEntry]);
    renderDrawer();
    await waitFor(() => {
      expect(screen.getByText("inbox.deny")).toBeTruthy();
    });
    fireEvent.click(screen.getByText("inbox.deny"));
    await waitFor(() => {
      expect(mocks.denyMailPending).toHaveBeenCalled();
    });
  });

  it("dismisses a pending sender", async () => {
    mocks.getMailPendingAll.mockResolvedValue([pendingEntry]);
    renderDrawer();
    await waitFor(() => {
      expect(screen.getByText("inbox.dismiss")).toBeTruthy();
    });
    fireEvent.click(screen.getByText("inbox.dismiss"));
    await waitFor(() => {
      expect(mocks.dismissMailPending).toHaveBeenCalled();
    });
  });

  it("reports an error toast when an action fails", async () => {
    mocks.getMailPendingAll.mockResolvedValue([pendingEntry]);
    mocks.approveMailPending.mockRejectedValue(new Error("no"));
    renderDrawer();
    await waitFor(() => {
      expect(screen.getByText("inbox.approveSender")).toBeTruthy();
    });
    fireEvent.click(screen.getByText("inbox.approveSender"));
    await waitFor(() => {
      expect(mocks.messageError).toHaveBeenCalledWith("common.operationFailed");
    });
  });

  it("batch-approves selected pending senders", async () => {
    mocks.getMailPendingAll.mockResolvedValue([
      pendingEntry,
      { ...pendingEntry, sender_address: "two@blog.com" },
    ]);
    renderDrawer();
    await waitFor(() => {
      expect(
        screen.getByTestId("row-select-agent-a:news@blog.com"),
      ).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("row-select-agent-a:news@blog.com"));
    fireEvent.click(screen.getByTestId("row-select-agent-a:two@blog.com"));
    await waitFor(() => {
      expect(screen.getByText("inbox.batchApprove")).toBeTruthy();
    });
    fireEvent.click(screen.getByText("inbox.batchApprove"));
    await waitFor(() => {
      expect(mocks.approveMailPending).toHaveBeenCalledWith([
        { agent_id: "agent-a", address: "news@blog.com" },
        { agent_id: "agent-a", address: "two@blog.com" },
      ]);
    });
    expect(mocks.messageSuccess).toHaveBeenCalledWith("inbox.batchApprove");
  });

  it("renders the merged whitelist across agents when no agent is selected", async () => {
    mocks.getMailAclAll.mockResolvedValue(aclData);
    renderDrawer();
    await waitFor(() => {
      expect(screen.getByText("ok@mail.com")).toBeTruthy();
    });
    expect(screen.getByText("Ok Sender")).toBeTruthy();
  });

  it("switches to the blacklist tab", async () => {
    mocks.getMailAclAll.mockResolvedValue(aclData);
    renderDrawer();
    await waitFor(() => {
      expect(screen.getByText("ok@mail.com")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("tab-blacklist"));
    await waitFor(() => {
      expect(screen.getByText("spam@mail.com")).toBeTruthy();
      expect(screen.queryByText("ok@mail.com")).toBeNull();
    });
  });

  it("opens the add-sender modal and validates the address", async () => {
    mocks.getMailAgents.mockResolvedValue({ agents: ["agent-a"] });
    renderDrawer();
    fireEvent.click(screen.getByText("inbox.addSender"));
    await waitFor(() => {
      expect(screen.getByTestId("acl-modal")).toBeTruthy();
    });
    // OK disabled with empty address
    expect(
      (screen.getByTestId("acl-modal-ok") as HTMLButtonElement).disabled,
    ).toBe(true);
    const inputs = screen.getByTestId("acl-modal").querySelectorAll("input");
    fireEvent.change(inputs[0], { target: { value: "not-an-email" } });
    fireEvent.click(screen.getByTestId("acl-modal-ok"));
    await waitFor(() => {
      expect(mocks.messageError).toHaveBeenCalledWith("inbox.invalidAddress");
    });
    expect(mocks.addMailWhitelist).not.toHaveBeenCalled();
  });

  it("adds a valid address to the active list", async () => {
    renderDrawer();
    fireEvent.click(screen.getByText("inbox.addSender"));
    await waitFor(() => {
      expect(screen.getByTestId("acl-modal")).toBeTruthy();
    });
    const inputs = screen.getByTestId("acl-modal").querySelectorAll("input");
    fireEvent.change(inputs[0], { target: { value: "new@friend.com" } });
    fireEvent.change(inputs[1], { target: { value: "Friend" } });
    fireEvent.change(inputs[2], { target: { value: "a note" } });
    fireEvent.click(screen.getByTestId("acl-modal-ok"));
    await waitFor(() => {
      expect(mocks.addMailWhitelist).toHaveBeenCalledWith([
        {
          agent_id: "",
          address: "new@friend.com",
          display_name: "Friend",
          remark: "a note",
        },
      ]);
    });
    expect(mocks.messageSuccess).toHaveBeenCalledWith("inbox.addedToAllAgents");
  });

  it("accepts a domain wildcard address", async () => {
    renderDrawer();
    fireEvent.click(screen.getByText("inbox.addSender"));
    await waitFor(() => {
      expect(screen.getByTestId("acl-modal")).toBeTruthy();
    });
    const inputs = screen.getByTestId("acl-modal").querySelectorAll("input");
    fireEvent.change(inputs[0], { target: { value: "*@partner.io" } });
    fireEvent.click(screen.getByTestId("acl-modal-ok"));
    await waitFor(() => {
      expect(mocks.addMailWhitelist).toHaveBeenCalledWith([
        expect.objectContaining({ address: "*@partner.io" }),
      ]);
    });
  });

  it("cancels the add modal and clears the form", async () => {
    renderDrawer();
    fireEvent.click(screen.getByText("inbox.addSender"));
    await waitFor(() => {
      expect(screen.getByTestId("acl-modal")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("acl-modal-cancel"));
    expect(screen.queryByTestId("acl-modal")).toBeNull();
  });

  it("routes adds on the blacklist tab to the blacklist API", async () => {
    renderDrawer();
    fireEvent.click(screen.getByTestId("tab-blacklist"));
    fireEvent.click(screen.getByText("inbox.addSender"));
    await waitFor(() => {
      expect(screen.getByTestId("acl-modal")).toBeTruthy();
    });
    const inputs = screen.getByTestId("acl-modal").querySelectorAll("input");
    fireEvent.change(inputs[0], { target: { value: "bad@actor.com" } });
    fireEvent.click(screen.getByTestId("acl-modal-ok"));
    await waitFor(() => {
      expect(mocks.addMailBlacklist).toHaveBeenCalled();
    });
    expect(mocks.addMailWhitelist).not.toHaveBeenCalled();
  });
});
