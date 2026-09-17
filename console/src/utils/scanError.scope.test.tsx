import { act, cleanup, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ConfigProvider, Modal } from "antd";
import { checkScanWarnings, handleScanError } from "./scanError";
import { captureSkillScope } from "@/api/skillScope";
import { useAuthStore } from "@/stores/authStore";
import i18n from "@/i18n";

vi.mock("@agentscope-ai/design", async () => vi.importActual("antd"));
beforeEach(async () => {
  ConfigProvider.config({
    holderRender: (children) => (
      <ConfigProvider theme={{ token: { motion: false } }}>
        {children}
      </ConfigProvider>
    ),
  });
  await i18n.changeLanguage("en");
  useAuthStore.setState({
    mode: "multi_user",
    phase: "authenticated",
    user: { id: "alice", platform_role: "member" } as never,
  });
});
afterEach(() => {
  Modal.destroyAll();
  ConfigProvider.config({ holderRender: undefined });
  cleanup();
});
const findings = [
  {
    title: "Private scan finding",
    file_path: "SKILL.md",
    description: "synthetic",
  },
];
it("drops scan findings that resolve after the initiating identity changes", async () => {
  const scope = captureSkillScope();
  let finish!: (value: never) => void;
  const pending = checkScanWarnings(
    "demo",
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
    async () => ({ whitelist: [] }) as never,
    i18n.t,
    scope,
  );
  act(() =>
    useAuthStore.setState({
      user: { id: "bob", platform_role: "member" } as never,
    }),
  );
  await act(async () => {
    finish([{ skill_name: "demo", action: "warned", findings }] as never);
    await pending;
  });
  expect(screen.queryByText("Private scan finding")).not.toBeInTheDocument();
});
it("closes an already-visible scan error when its identity changes", async () => {
  const scope = captureSkillScope();
  act(() => {
    handleScanError(
      new Error(JSON.stringify({ type: "security_scan_failed", findings })),
      i18n.t,
      scope,
    );
  });
  await screen.findByText("Private scan finding");
  act(() =>
    useAuthStore.setState({
      user: { id: "bob", platform_role: "member" } as never,
    }),
  );
  await waitFor(() =>
    expect(screen.queryByText("Private scan finding")).not.toBeInTheDocument(),
  );
});
