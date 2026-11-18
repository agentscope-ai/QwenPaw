import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ApiError } from "../../../api/request";
import { createSdkSessionAdapter } from "../sdkSessionAdapter";
import {
  ChatSessionTransition,
  ReadyChatWelcome,
} from "./ChatSessionTransition";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

it("hides the SDK surface and welcome until hydration completes", async () => {
  const session = { id: "target", name: "target", messages: [] };
  const adapter = createSdkSessionAdapter({
    getSession: async () => session,
    getSessionList: async () => [],
    updateSession: async () => [],
    removeSession: async () => [],
    createSession: async () => ({ session, sessions: [session] }),
  });
  render(
    <ChatSessionTransition
      adapter={adapter}
      sessionId="target"
      onRetry={vi.fn()}
    >
      <div>Previous conversation</div>
      <ReadyChatWelcome adapter={adapter} sessionId="target">
        <div>Welcome</div>
      </ReadyChatWelcome>
    </ChatSessionTransition>,
  );
  const surface = screen.getByText("Previous conversation").parentElement!;
  expect(surface.inert).toBe(true);
  expect(surface).not.toBeVisible();
  expect(screen.queryByText("Welcome")).toBeNull();
  expect(screen.getByRole("status")).toHaveTextContent("common.loading");
  await act(async () => {
    await adapter.api.getSession("target");
  });
  expect(surface.inert).toBe(false);
  await waitFor(() => expect(surface).toBeVisible());
  expect(screen.getByText("Welcome")).toBeVisible();
  expect(screen.queryByRole("status")).toBeNull();
});

function draftAdapter() {
  return createSdkSessionAdapter({
    getSession: async () => undefined,
    getSessionList: async () => [],
    updateSession: async () => [],
    removeSession: async () => [],
    createSession: async () => [],
  });
}

it("keeps the SDK mounted and inert while route ownership is pending", () => {
  const adapter = draftAdapter();
  const view = render(
    <ChatSessionTransition adapter={adapter} pending>
      <div>SDK surface</div>
    </ChatSessionTransition>,
  );
  const surface = screen.getByText("SDK surface").parentElement!;
  expect(surface).not.toBeVisible();
  expect(surface.inert).toBe(true);
  expect(screen.getByRole("status")).toHaveTextContent("common.loading");

  view.rerender(
    <ChatSessionTransition adapter={adapter}>
      <div>SDK surface</div>
    </ChatSessionTransition>,
  );
  expect(screen.getByText("SDK surface").parentElement).toBe(surface);
  expect(surface.inert).toBe(false);
});

it.each([
  [new ApiError(404, "Chat not found"), "chat.routeNotFound"],
  [new ApiError(409, "Ambiguous Chat"), "chat.routeAmbiguous"],
  [new Error("Network error"), "chat.historyLoadFailed"],
])("shows a route error and an interactive retry action (%s)", (error, key) => {
  const retry = vi.fn();
  render(
    <ChatSessionTransition
      adapter={draftAdapter()}
      error={error}
      onRetry={retry}
    >
      <div>SDK surface</div>
    </ChatSessionTransition>,
  );

  expect(screen.getByText("SDK surface")).not.toBeVisible();
  expect(screen.getByRole("alert")).toHaveTextContent(key as string);
  fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
  expect(retry).toHaveBeenCalledOnce();
});

it("offers retry when the SDK history load rejects", async () => {
  const adapter = draftAdapter();
  const retry = vi.fn();
  render(
    <ChatSessionTransition
      adapter={adapter}
      sessionId="missing"
      onRetry={retry}
    >
      <div>SDK surface</div>
    </ChatSessionTransition>,
  );
  await act(async () => {
    await adapter.api.getSession("missing");
  });

  expect(screen.getByRole("alert")).toHaveTextContent("chat.historyLoadFailed");
  fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
  expect(retry).toHaveBeenCalledOnce();
});

it("delegates failed hydration retry without bypassing the SDK loader", async () => {
  const session = { id: "target", name: "target", messages: [] };
  const getSession = vi.fn().mockRejectedValueOnce(new Error("offline"));
  const onRetry = vi.fn();
  const adapter = createSdkSessionAdapter({
    getSession,
    getSessionList: async () => [],
    updateSession: async () => [],
    removeSession: async () => [],
    createSession: async () => ({ session, sessions: [session] }),
  });
  render(
    <ChatSessionTransition
      adapter={adapter}
      sessionId="target"
      onRetry={onRetry}
    >
      <div>Recovered conversation</div>
    </ChatSessionTransition>,
  );

  await act(async () => {
    await expect(adapter.api.getSession("target")).rejects.toThrow("offline");
  });

  const surface = screen.getByText("Recovered conversation").parentElement!;
  expect(surface.inert).toBe(true);
  expect(surface).not.toBeVisible();
  expect(screen.getByRole("alert")).toHaveTextContent("chat.historyLoadFailed");

  fireEvent.click(screen.getByRole("button", { name: "common.retry" }));

  expect(onRetry).toHaveBeenCalledOnce();
  expect(getSession).toHaveBeenCalledOnce();
  expect(surface.inert).toBe(true);
  expect(surface).not.toBeVisible();
  expect(screen.getByRole("alert")).toHaveTextContent("chat.historyLoadFailed");
});
