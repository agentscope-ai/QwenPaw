// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { ViewCronSessionButton } from "./ViewCronSessionButton";
import type { PushMessage } from "../types";

const mocks = vi.hoisted(() => ({
  trace: vi.fn(),
  chats: vi.fn(),
  selectAgent: vi.fn(),
  close: vi.fn(),
  info: vi.fn(),
  error: vi.fn(),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../../../api/modules/console", () => ({
  consoleApi: { getInboxTrace: mocks.trace },
}));
vi.mock("../../../api/modules/chat", () => ({
  chatApi: { listChats: mocks.chats },
}));
vi.mock("../../../stores/agentStore", () => ({
  useAgentStore: (
    selector: (state: {
      setSelectedAgent: typeof mocks.selectAgent;
    }) => unknown,
  ) => selector({ setSelectedAgent: mocks.selectAgent }),
}));
vi.mock("antd", async () => ({
  ...(await vi.importActual<object>("antd")),
  message: { info: mocks.info, error: mocks.error },
}));

const item: PushMessage = {
  id: "notification",
  channelType: "skill",
  channelName: "Cron",
  title: "Scheduled task",
  content: "Completed",
  sender: { userId: "user", username: "User" },
  createdAt: new Date(),
  read: true,
  metadata: {
    sourceType: "cron",
    agentId: "other-agent",
    payload: { run_id: "run-1" },
  },
};

function Location() {
  return <div data-testid="location">{useLocation().pathname}</div>;
}

function mount(value = item) {
  render(
    <MemoryRouter initialEntries={["/inbox"]}>
      <ViewCronSessionButton item={value} onNavigate={mocks.close} />
      <Location />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  mocks.trace.mockResolvedValue({
    meta: {
      run_session_id: "cron-session",
      target_session_id: "original-session",
      dispatch_channel: "console",
      target_user_id: "user",
    },
  });
  mocks.chats.mockResolvedValue([
    { id: "original-chat", session_id: "original-session" },
    {
      id: "wrong-user",
      session_id: "cron-session",
      channel: "console",
      user_id: "another-user",
    },
    {
      id: "chat/123",
      session_id: "cron-session",
      channel: "console",
      user_id: "user",
    },
  ]);
});

describe("ViewCronSessionButton", () => {
  it("opens the execution chat using its Console ID and owning agent", async () => {
    mount();
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => {
      expect(screen.getByTestId("location").textContent).toBe(
        "/chat/chat%2F123",
      );
    });
    expect(mocks.trace).toHaveBeenCalledWith("run-1");
    expect(mocks.chats).toHaveBeenCalledWith({ agentId: "other-agent" });
    expect(mocks.selectAgent).toHaveBeenCalledWith("other-agent");
    expect(mocks.close).toHaveBeenCalledOnce();
  });

  it("stays in the inbox when the session has been deleted", async () => {
    mocks.chats.mockResolvedValue([]);
    mount();
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() =>
      expect(mocks.info).toHaveBeenCalledWith("inbox.sessionNotFound"),
    );
    expect(mocks.selectAgent).not.toHaveBeenCalled();
    expect(mocks.close).not.toHaveBeenCalled();
    expect(screen.getByTestId("location").textContent).toBe("/inbox");
  });

  it("reports lookup failures without switching agents", async () => {
    mocks.trace.mockRejectedValue(new Error("offline"));
    mount();
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() =>
      expect(mocks.error).toHaveBeenCalledWith("inbox.openSessionFailed"),
    );
    expect(mocks.selectAgent).not.toHaveBeenCalled();
  });

  it("disables the action when no execution trace exists", () => {
    mount({ ...item, metadata: { sourceType: "cron" } });
    expect((screen.getByRole("button") as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  it("does not show the action for other inbox sources", () => {
    mount({ ...item, metadata: { sourceType: "heartbeat" } });
    expect(screen.queryByRole("button")).toBeNull();
  });
});
