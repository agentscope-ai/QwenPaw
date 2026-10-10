import { act, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { createSdkSessionAdapter } from "../sdkSessionAdapter";
import {
  ChatSessionTransition,
  ReadyChatWelcome,
} from "./ChatSessionTransition";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

it("keeps the SDK surface inert and suppresses welcome until ready", async () => {
  const session = { id: "target", name: "target", messages: [] };
  const adapter = createSdkSessionAdapter({
    getSession: async () => session,
    getSessionList: async () => [],
    updateSession: async () => [],
    removeSession: async () => [],
    createSession: async () => ({ session, sessions: [session] }),
  });
  render(
    <ChatSessionTransition adapter={adapter} sessionId="target">
      <div>Previous conversation</div>
      <ReadyChatWelcome adapter={adapter} sessionId="target">
        <div>Welcome</div>
      </ReadyChatWelcome>
    </ChatSessionTransition>,
  );
  const surface = screen.getByText("Previous conversation").parentElement!;
  expect(surface.inert).toBe(true);
  expect(surface).toBeVisible();
  expect(screen.queryByText("Welcome")).toBeNull();
  expect(screen.getByRole("status")).toHaveTextContent("common.loading");
  await act(async () => {
    await adapter.api.getSession("target");
  });
  expect(surface.inert).toBe(false);
  expect(screen.getByText("Welcome")).toBeVisible();
  expect(screen.queryByRole("status")).toBeNull();
});
