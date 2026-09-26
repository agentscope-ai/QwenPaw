import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SessionItem from ".";

const mocks = vi.hoisted(() => ({
  copyText: vi.fn(),
  error: vi.fn(),
  success: vi.fn(),
}));

vi.mock("../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { error: mocks.error, success: mocks.success },
  }),
}));

vi.mock("../../utils/clipboard", () => ({
  copyText: mocks.copyText,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) =>
      key === "appCenter.moreActions" ? "More actions" : key,
    i18n: { language: "en", resolvedLanguage: "en" },
  }),
}));

beforeEach(() => {
  mocks.copyText.mockReset();
  mocks.copyText.mockResolvedValue(undefined);
  mocks.error.mockReset();
  mocks.success.mockReset();
});

describe("SessionItem status indicator", () => {
  it.each([
    {
      name: "running takes priority",
      props: { chatStatus: "running" as const, unseenResult: true },
      label: "chat.statusInProgress",
    },
    {
      name: "completed but unseen",
      props: { chatStatus: "idle" as const, unseenResult: true },
      label: "chat.statusUnseenResult",
    },
    {
      name: "idle and seen",
      props: { chatStatus: "idle" as const, unseenResult: false },
      label: "chat.statusIdle",
    },
  ])("renders $name", ({ props, label }) => {
    render(<SessionItem sessionId="chat-1" name="Chat" {...props} />);

    expect(screen.getByRole("img", { name: label })).toBeInTheDocument();
  });
});

describe("SessionItem keyboard selection", () => {
  it.each(["Enter", " "])("selects the focused session with %s", (key) => {
    const onClick = vi.fn();
    render(
      <SessionItem
        sessionId="chat-keyboard"
        name="Keyboard chat"
        onClick={onClick}
      />,
    );
    const row = screen.getByText("Keyboard chat").closest('[role="button"]')!;
    fireEvent.keyDown(row, { key });
    fireEvent.keyDown(row, { key, repeat: true });
    expect(onClick).toHaveBeenCalledExactlyOnceWith("chat-keyboard");
  });

  it("does not select a session while submitting its rename input", () => {
    const onClick = vi.fn();
    const onEditSubmit = vi.fn();
    render(
      <SessionItem
        sessionId="chat-editing"
        name="Original"
        editing
        editValue="Renamed"
        onClick={onClick}
        onEditSubmit={onEditSubmit}
      />,
    );
    const input = screen.getByRole("textbox");
    expect(input).toBeEnabled();
    expect(input.closest('[aria-disabled="true"]')).toBeNull();
    fireEvent.change(input, { target: { value: "Renamed" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onEditSubmit).toHaveBeenCalledOnce();
    expect(onClick).not.toHaveBeenCalled();
  });

  it("keeps disabled sessions out of keyboard navigation", () => {
    const onClick = vi.fn();
    render(
      <SessionItem
        sessionId="chat-disabled"
        name="Disabled chat"
        disabled
        onClick={onClick}
      />,
    );
    const row = screen.getByText("Disabled chat").closest('[role="button"]')!;
    expect(row).toHaveAttribute("tabindex", "-1");
    expect(row).toHaveAttribute("aria-disabled", "true");
    fireEvent.keyDown(row, { key: "Enter" });
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe("SessionItem actions", () => {
  it("hides the drag hint while keeping the more actions menu", async () => {
    render(<SessionItem sessionId="chat-1" name="Chat" />);

    expect(document.querySelector("svg.lucide-grip-vertical")).toBeNull();

    const moreButton = screen.getByRole("button", { name: "More actions" });
    expect(moreButton).toBeInTheDocument();
    fireEvent.click(moreButton);

    expect(
      await screen.findByRole("menuitem", {
        name: "chat.contextMenu.rename",
      }),
    ).toBeInTheDocument();
  });

  it("closes the info card before opening the actions menu", async () => {
    render(<SessionItem sessionId="chat-1" name="Chat" />);

    const row = screen.getByText("Chat").closest('[role="button"]')!;
    fireEvent.focus(row);
    const info = await screen.findByRole("tooltip");
    expect(info).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    expect(
      await screen.findByRole("menuitem", {
        name: "chat.contextMenu.rename",
      }),
    ).toBeInTheDocument();
    await waitFor(() => {
      const closingPopover = info.closest(".ant-popover");
      expect(closingPopover).toHaveClass("ant-zoom-big-leave-active");
      expect(closingPopover).toHaveStyle({ pointerEvents: "none" });
    });
  });

  it("copies the current conversation ID from the actions menu", async () => {
    render(<SessionItem sessionId="chat-to-copy" name="Copy ID" />);

    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    fireEvent.click(
      await screen.findByRole("menuitem", {
        name: "chat.contextMenu.copyId",
      }),
    );

    await waitFor(() => {
      expect(mocks.copyText).toHaveBeenCalledExactlyOnceWith("chat-to-copy");
    });
    expect(mocks.success).toHaveBeenCalledWith("common.copied");
    expect(mocks.error).not.toHaveBeenCalled();
  });
});

describe("SessionItem name display", () => {
  it("keeps names intact up to 100 characters", () => {
    const name = "a".repeat(100);
    render(<SessionItem sessionId="chat-100" name={name} />);

    expect(screen.getByText(name)).toBeInTheDocument();
    expect(screen.queryByText(`${name}…`)).not.toBeInTheDocument();
  });

  it("adds the ellipsis in the list only after 100 characters", () => {
    const name = "a".repeat(101);
    render(<SessionItem sessionId="chat-101" name={name} />);

    expect(screen.getByText(`${"a".repeat(100)}…`)).toBeInTheDocument();
  });
});

describe("SessionItem info card", () => {
  it("bounds the name rendered in the info card", async () => {
    const name = "b".repeat(501);
    render(<SessionItem sessionId="chat-long" name={name} />);

    fireEvent.focus(
      screen.getByText(`${"b".repeat(100)}…`).closest('[role="button"]')!,
    );

    expect(await screen.findByText(`${"b".repeat(500)}…`)).toBeInTheDocument();
  });

  it("shows a compact relative update time with the exact date as metadata", async () => {
    const updatedAt = new Date(Date.now() - 5 * 60 * 1000).toISOString();
    render(
      <SessionItem
        sessionId="chat-time"
        name="Time-aware chat"
        updatedAt={updatedAt}
      />,
    );

    fireEvent.focus(
      screen.getByText("Time-aware chat").closest('[role="button"]')!,
    );

    const relativeTime = new Intl.RelativeTimeFormat("en", {
      numeric: "auto",
      style: "short",
    }).format(-5, "minute");
    const time = await screen.findByText(relativeTime);
    expect(time).toHaveAttribute("datetime", updatedAt);
    expect(time).toHaveAttribute(
      "title",
      new Intl.DateTimeFormat("en", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(updatedAt)),
    );
  });

  it.each([
    {
      group: {
        id: "default",
        name: "Uncategorized",
        order: 0,
        kind: "default" as const,
        pinned: false,
      },
      source: "chat" as const,
    },
    {
      group: {
        id: "cron",
        name: "Scheduled task conversations",
        order: 1,
        kind: "cron" as const,
        pinned: false,
      },
      source: "cron" as const,
    },
    {
      group: {
        id: "team",
        name: "Team conversations",
        order: 2,
        kind: "custom" as const,
        pinned: false,
      },
      source: "chat" as const,
    },
  ])("shows the $group.name group", async ({ group, source }) => {
    render(
      <SessionItem
        sessionId={`chat-${group.id}`}
        name="Session group"
        groupId={group.id}
        groups={[group]}
        source={source}
      />,
    );

    fireEvent.focus(
      screen.getByText("Session group").closest('[role="button"]')!,
    );

    expect(await screen.findByText(group.name)).toBeInTheDocument();
    expect(screen.queryByText("chat.groups.chatShort")).not.toBeInTheDocument();
    expect(
      screen.queryByText("chat.sessionPanel.groupByTime"),
    ).not.toBeInTheDocument();
  });
});

describe("Session action surface", () => {
  it("moves through the group picker without selecting the conversation", async () => {
    const onMove = vi.fn();
    const onClick = vi.fn();
    render(
      <SessionItem
        sessionId="group-chat"
        name="Grouped"
        groupId="one"
        groups={
          [
            { id: "one", name: "Current" },
            { id: "two", name: "Target" },
          ] as never
        }
        onMove={onMove}
        onClick={onClick}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    fireEvent.click(
      await screen.findByRole("menuitem", {
        name: "chat.contextMenu.moveToGroup",
      }),
    );
    expect(
      await screen.findByRole("menuitem", { name: "Current" }),
    ).toBeDisabled();
    fireEvent.click(screen.getByRole("menuitem", { name: "Target" }));
    expect(onMove).toHaveBeenCalledExactlyOnceWith("group-chat", "two");
    expect(onClick).not.toHaveBeenCalled();
  });
});
