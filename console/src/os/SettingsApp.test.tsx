import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import SettingsApp from "./SettingsApp";
import { useAuthStore } from "@/stores/authStore";
vi.mock("../plugins/registry/hooks", () => ({
  useRoutes: () => [
    {
      id: "core.voice-transcription",
      path: "/voice-transcription",
      capability: "platform.settings.manage",
      Component: () => <div>voice administration</div>,
    },
  ],
}));
vi.mock("./WindowRouter", () => ({ default: ({ element }: any) => element }));
vi.mock("./useOsStyles", () => ({
  useOsStyles: () => ({ styles: {}, cx: () => "" }),
}));
afterEach(cleanup);
it("filters member settings and removes an open admin pane on role downgrade", () => {
  useAuthStore.setState({
    mode: "multi_user",
    phase: "authenticated",
    user: { id: "a", platform_role: "admin" } as never,
  });
  render(<SettingsApp />);
  expect(screen.getByText("voice administration")).toBeTruthy();
  act(() =>
    useAuthStore.setState({
      user: { id: "a", platform_role: "member" } as never,
    }),
  );
  expect(screen.queryByText("voice administration")).toBeNull();
  expect(screen.queryByText("Voice")).toBeNull();
});
