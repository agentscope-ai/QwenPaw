// @vitest-environment jsdom
/**
 * InboxPage render tests — regression family: inbox badge accuracy and
 * message lifecycle (filter/paginate/batch-select/mark-read round trips).
 * Heavy children are stubbed so the page's orchestration logic executes
 * under test.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { renderWithProviders } from "@/test/common_setup";

// ---- Hoisted mocks ---------------------------------------------------------

const mocks = vi.hoisted(() => ({
  inboxData: null as unknown,
  pendingCount: 0,
  newArrival: false,
  approvals: [] as unknown[],
  sendApprovalCommand: vi.fn(),
  stopChat: vi.fn(),
  getRealIdForSession: vi.fn((id: string) => id),
  getInboxTrace: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key}:${JSON.stringify(opts)}` : key,
    i18n: { language: "en" },
  }),
}));

vi.mock("./hooks/useInboxData", () => ({
  useInboxData: () => mocks.inboxData,
}));

vi.mock("./hooks/useMailPendingCount", () => ({
  useMailPendingCount: () => ({
    pendingCount: mocks.pendingCount,
    refresh: vi.fn(),
    newArrival: mocks.newArrival,
    markSeen: vi.fn(),
  }),
}));

vi.mock("./hooks/useTraceViewer", () => ({
  useTraceViewer: (markRead: (id: string) => void) => ({
    detailOpen: false,
    selectedMessage: null,
    traceLoading: false,
    traceEvents: [],
    expandedTraceMap: {},
    traceContainerRef: { current: null },
    openMessageDetail: (m: { id: string; read: boolean }) => {
      if (!m.read) markRead(m.id);
    },
    closeDetail: vi.fn(),
    toggleTracePanel: vi.fn(),
    copyTraceBlock: vi.fn(),
    handleTraceScroll: vi.fn(),
  }),
}));

vi.mock("./components/MailAccessControlDrawer", () => ({
  MailAccessControlDrawer: ({ open }: { open?: boolean }) =>
    open ? <div data-testid="mail-acl-drawer" /> : null,
}));

vi.mock("./components", () => ({
  PushMessageCard: ({
    message,
    onView,
    onDelete,
    onMarkAsRead,
    selected,
    onSelectChange,
  }: {
    message: { id: string; title: string; read: boolean };
    onView: (id: string) => void;
    onDelete: (id: string) => void;
    onMarkAsRead: (id: string) => void;
    selected?: boolean;
    onSelectChange?: (id: string, checked: boolean) => void;
  }) => (
    <div data-testid={`push-card-${message.id}`}>
      <span>{message.title}</span>
      <button
        data-testid={`view-${message.id}`}
        onClick={() => onView(message.id)}
      >
        view
      </button>
      <button
        data-testid={`del-${message.id}`}
        onClick={() => onDelete(message.id)}
      >
        del
      </button>
      <button
        data-testid={`read-${message.id}`}
        onClick={() => onMarkAsRead(message.id)}
      >
        read
      </button>
      {onSelectChange && (
        <input
          type="checkbox"
          data-testid={`sel-${message.id}`}
          checked={Boolean(selected)}
          onChange={(e) => onSelectChange(message.id, e.target.checked)}
        />
      )}
    </div>
  ),
}));

vi.mock("../../components/ApprovalCard/ApprovalCard", () => ({
  ApprovalCard: ({ requestId }: { requestId: string }) => (
    <div data-testid={`approval-card-${requestId}`} />
  ),
}));

vi.mock("../../contexts/ApprovalContext", () => ({
  useApprovalContext: () => ({
    approvals: mocks.approvals,
    setApprovals: vi.fn(),
  }),
}));

vi.mock("../../hooks/useInboxWobble", () => ({
  useInboxWobble: () => [true, vi.fn()],
}));

vi.mock("../../api/modules/commands", () => ({
  commandsApi: {
    sendApprovalCommand: (...a: unknown[]) => mocks.sendApprovalCommand(...a),
  },
}));

vi.mock("../../api/modules/chat", () => ({
  chatApi: { stopChat: (...a: unknown[]) => mocks.stopChat(...a) },
}));

vi.mock("../Chat/sessionApi", () => ({
  default: {
    getRealIdForSession: (id: string) => mocks.getRealIdForSession(id),
  },
}));

vi.mock("../../stores/agentStore", () => ({
  useAgentStore: (selector?: (s: { agents: unknown[] }) => unknown) =>
    selector ? selector({ agents: [] }) : { agents: [] },
}));

vi.mock("react-markdown", () => ({ default: () => null }));
vi.mock("remark-gfm", () => ({ default: () => null }));
vi.mock("@/components/Markdown/externalLinkComponents", () => ({
  externalLinkMarkdownComponents: {},
}));
vi.mock("./utils/traceUtils", async () => {
  const actual = await vi.importActual<object>("./utils/traceUtils");
  return { ...actual };
});

vi.mock("lucide-react", () => {
  const make = (n: string) =>
    function Icon() {
      return <span data-testid={`icon-${n}`} />;
    };
  return {
    PackageOpen: make("pkg"),
    Bell: make("bell"),
    BellRing: make("bellring"),
  };
});

vi.mock("@ant-design/icons", () => ({
  BulbOutlined: () => null,
  CopyOutlined: () => null,
  DownOutlined: () => null,
  SafetyOutlined: () => null,
  ToolOutlined: () => null,
}));

// antd: keep Tabs functional enough to switch, stub the rest
vi.mock("antd", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("antd");
  const Tabs = ({
    activeKey,
    onChange,
    items = [],
  }: {
    activeKey?: string;
    onChange?: (k: string) => void;
    items?: Array<{
      key: string;
      label: React.ReactNode;
      children?: React.ReactNode;
    }>;
  }) => (
    <div>
      {items.map((item) => (
        <button
          key={item.key}
          data-testid={`inbox-tab-${item.key}`}
          data-active={item.key === activeKey}
          onClick={() => onChange?.(item.key)}
        >
          {item.label}
        </button>
      ))}
      {items.find((i) => i.key === activeKey)?.children}
    </div>
  );
  const Empty = ({ description }: { description?: React.ReactNode }) => (
    <div data-testid="inbox-empty">{description}</div>
  );
  const Pagination = ({
    current,
    onChange,
  }: {
    current?: number;
    onChange?: (p: number) => void;
  }) => (
    <button
      data-testid="inbox-next-page"
      onClick={() => onChange?.((current ?? 1) + 1)}
    >
      next
    </button>
  );
  const Popconfirm = ({
    children,
    onConfirm,
  }: {
    children?: React.ReactNode;
    onConfirm?: () => void;
  }) => <span onClick={onConfirm}>{children}</span>;
  return { ...actual, Tabs, Empty, Pagination, Popconfirm };
});

import InboxPage from "./index";
import type { PushMessage } from "./types";

// ---- Fixtures --------------------------------------------------------------

function pushMsg(
  id: string,
  overrides: Partial<PushMessage> = {},
): PushMessage {
  return {
    id,
    channelType: "email",
    channelName: "Mail",
    title: `msg-${id}`,
    content: "body",
    sender: { userId: "u", username: "U" },
    createdAt: new Date(0),
    read: false,
    metadata: { sourceType: "mail", agentId: "default" },
    ...overrides,
  } as PushMessage;
}

function makeInboxData(messages: PushMessage[], summaryUnread = 0) {
  mocks.inboxData = {
    summary: {
      approvals: { total: 0, urgent: 0 },
      pushMessages: { total: messages.length, unread: summaryUnread },
      harvests: { total: 0, active: 0 },
    },
    pushMessages: messages,
    harvests: [],
    markMessageAsRead: vi.fn(),
    markAllMessagesAsRead: vi.fn().mockResolvedValue(summaryUnread),
    deleteMessage: vi.fn(),
    deleteMessages: vi.fn().mockResolvedValue(0),
    triggerHarvest: vi.fn(),
    refreshPushMessages: vi.fn(),
  };
  return mocks.inboxData as {
    markMessageAsRead: ReturnType<typeof vi.fn>;
    markAllMessagesAsRead: ReturnType<typeof vi.fn>;
    deleteMessage: ReturnType<typeof vi.fn>;
    deleteMessages: ReturnType<typeof vi.fn>;
  };
}

beforeEach(() => {
  mocks.pendingCount = 0;
  mocks.newArrival = false;
  mocks.approvals = [];
  localStorage.clear();
});

// ---- Tests -----------------------------------------------------------------

describe("InboxPage", () => {
  it("renders the messages tab with push cards", async () => {
    makeInboxData([pushMsg("m1"), pushMsg("m2")]);
    renderWithProviders(<InboxPage />);
    await waitFor(() => {
      expect(screen.getByTestId("push-card-m1")).toBeTruthy();
      expect(screen.getByTestId("push-card-m2")).toBeTruthy();
    });
  });

  it("shows the empty state when there are no messages", async () => {
    makeInboxData([]);
    renderWithProviders(<InboxPage />);
    await waitFor(() => {
      expect(screen.getByTestId("inbox-empty")).toBeTruthy();
    });
  });

  it("persists the active tab to localStorage and restores it", async () => {
    localStorage.setItem("qwenpaw.inbox.activeTab", "approvals");
    makeInboxData([]);
    mocks.approvals = [{ request_id: "r1" }];
    renderWithProviders(<InboxPage />);
    await waitFor(() => {
      expect(screen.getByTestId("inbox-tab-approvals")).toBeTruthy();
    });
    expect(
      (screen.getByTestId("inbox-tab-approvals") as HTMLElement).dataset.active,
    ).toBe("true");
  });

  it("switches tabs and writes the choice back to localStorage", async () => {
    makeInboxData([pushMsg("m1")]);
    renderWithProviders(<InboxPage />);
    await waitFor(() => {
      expect(screen.getByTestId("inbox-tab-approvals")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("inbox-tab-approvals"));
    await waitFor(() => {
      expect(localStorage.getItem("qwenpaw.inbox.activeTab")).toBe("approvals");
    });
  });

  it("marks a message read when viewing it", async () => {
    const data = makeInboxData([pushMsg("m1", { read: false })]);
    renderWithProviders(<InboxPage />);
    await waitFor(() => {
      expect(screen.getByTestId("view-m1")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("view-m1"));
    expect(data.markMessageAsRead).toHaveBeenCalledWith("m1");
  });

  it("marks all read and reports the count", async () => {
    const data = makeInboxData([pushMsg("m1"), pushMsg("m2")], 2);
    renderWithProviders(<InboxPage />);
    await waitFor(() => {
      expect(screen.getByText("inbox.markAllRead")).toBeTruthy();
    });
    fireEvent.click(screen.getByText("inbox.markAllRead"));
    await waitFor(() => {
      expect(data.markAllMessagesAsRead).toHaveBeenCalled();
    });
  });

  it("explains there is nothing to mark when no unread messages", async () => {
    makeInboxData([pushMsg("m1", { read: true })], 0);
    renderWithProviders(<InboxPage />);
    await waitFor(() => {
      const btn = screen.getByText("inbox.markAllRead").closest("button");
      expect(btn?.disabled).toBe(true);
    });
  });

  it("enters batch mode, selects a message, and batch-deletes", async () => {
    const data = makeInboxData([pushMsg("m1")]);
    renderWithProviders(<InboxPage />);
    await waitFor(() => {
      expect(screen.getByText("inbox.batchOperation")).toBeTruthy();
    });
    fireEvent.click(screen.getByText("inbox.batchOperation"));
    await waitFor(() => {
      expect(screen.getByTestId("sel-m1")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("sel-m1"));
    await waitFor(() => {
      expect(screen.getByText("inbox.batchDeleteButton")).toBeTruthy();
    });
    // Popconfirm stub fires onConfirm directly on click of the wrapper
    fireEvent.click(screen.getByText("inbox.batchDeleteButton"));
    await waitFor(() => {
      expect(data.deleteMessages).toHaveBeenCalledWith(["m1"]);
    });
  });

  it("exits batch mode and clears the selection", async () => {
    makeInboxData([pushMsg("m1")]);
    renderWithProviders(<InboxPage />);
    fireEvent.click(screen.getByText("inbox.batchOperation"));
    await waitFor(() => {
      expect(screen.getByText("inbox.exitBatch")).toBeTruthy();
    });
    fireEvent.click(screen.getByText("inbox.exitBatch"));
    await waitFor(() => {
      expect(screen.getByText("inbox.batchOperation")).toBeTruthy();
      expect(screen.queryByTestId("sel-m1")).toBeNull();
    });
  });

  it("opens the mail access control drawer", async () => {
    makeInboxData([]);
    mocks.pendingCount = 3;
    renderWithProviders(<InboxPage />);
    // The drawer entry is a button in the page header area
    const entry = screen
      .getAllByRole("button")
      .find((b) => b.textContent?.includes("inbox.mailAccessControl"));
    expect(entry).toBeTruthy();
    fireEvent.click(entry!);
    await waitFor(() => {
      expect(screen.getByTestId("mail-acl-drawer")).toBeTruthy();
    });
  });

  it("shows approval cards on the approvals tab", async () => {
    makeInboxData([]);
    mocks.approvals = [
      { request_id: "r1", root_session_id: "s1", tool_name: "bash" },
    ];
    renderWithProviders(<InboxPage />);
    fireEvent.click(screen.getByTestId("inbox-tab-approvals"));
    await waitFor(() => {
      expect(screen.getByTestId("approval-card-r1")).toBeTruthy();
    });
  });
});
