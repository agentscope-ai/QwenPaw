import { App, ConfigProvider } from "antd";
import {
  act,
  cleanup,
  fireEvent,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SkillSourceActions } from "./SkillSourceActions";
import { renderWithProviders as renderBase } from "@/test/common_setup";
import { useAuthStore } from "@/stores/authStore";
import { useAgentStore } from "@/stores/agentStore";
import { clearAccessSession } from "@/api/authSession";
import i18n from "@/i18n";
import type { SkillSpec } from "@/api/types";

const renderWithProviders = (element: React.ReactElement) =>
  renderBase(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App>{element}</App>
    </ConfigProvider>,
  );
const hash = "a".repeat(64);
const skill: SkillSpec = {
  name: "damaged",
  source: "custom",
  enabled: false,
  source_pool_version_id: "version-1",
  source_pool_version: "1",
  detached: true,
  update_available: true,
  content_hash: hash,
};
const label = (key: string) => i18n.t(`skillGovernance.${key}`);
let writes: Array<{ url: string; body: unknown; agent: string | null }>;
beforeEach(async () => {
  await i18n.changeLanguage("en");
  useAuthStore.setState({
    mode: "multi_user",
    phase: "authenticated",
    user: { id: "alice", platform_role: "member" } as never,
  });
  useAgentStore.setState({
    selectedAgent: "a",
    agents: [
      { id: "a", enabled: true, access_role: "owner", can_edit: true },
    ] as never,
  });
  writes = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      writes.push({
        url,
        body: JSON.parse(init.body as string),
        agent: new Headers(init.headers).get("X-Agent-Id"),
      });
      return new Response(JSON.stringify({ ...skill, detached: false }), {
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("shows a damaged bound copy as recoverable without requiring its main document", async () => {
  renderWithProviders(
    <SkillSourceActions skill={skill} onChanged={async () => {}} />,
  );
  expect(screen.getByText(label("recoverable"))).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: label("restore") }));
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
  expect(writes).toEqual([]);
  fireEvent.click(
    screen.getByRole("button", { name: i18n.t("common.confirm") }),
  );
  await waitFor(() =>
    expect(writes).toEqual([
      {
        url: "/api/agent-skills/damaged/restore",
        body: { agent_id: "a", expected_content_hash: hash },
        agent: "a",
      },
    ]),
  );
});

it("updates only after explicit confirmation with the installed content hash", async () => {
  renderWithProviders(
    <SkillSourceActions skill={skill} onChanged={async () => {}} />,
  );
  fireEvent.click(screen.getByRole("button", { name: label("update") }));
  await screen.findByRole("dialog");
  expect(writes).toEqual([]);
  fireEvent.click(
    screen.getByRole("button", { name: i18n.t("common.confirm") }),
  );
  await waitFor(() =>
    expect(writes[0]?.body).toEqual({
      agent_id: "a",
      expected_content_hash: hash,
    }),
  );
  expect(writes[0].url).toBe("/api/agent-skills/damaged/update");
});

it("discards a pending confirmation when the Agent changes", async () => {
  renderWithProviders(
    <SkillSourceActions skill={skill} onChanged={async () => {}} />,
  );
  fireEvent.click(screen.getByRole("button", { name: label("restore") }));
  await screen.findByRole("dialog");
  act(() => useAgentStore.setState({ selectedAgent: "b" }));
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
  expect(writes).toEqual([]);
});

it.each(["user", "unknown"])(
  "does not expose source writes for %s permission",
  (role) => {
    useAgentStore.setState({
      agents:
        role === "unknown"
          ? []
          : ([
              { id: "a", enabled: true, access_role: "user", can_edit: false },
            ] as never),
    });
    renderWithProviders(
      <SkillSourceActions skill={skill} onChanged={async () => {}} />,
    );
    expect(
      screen.queryByRole("button", { name: label("restore") }),
    ).not.toBeInTheDocument();
    expect(writes).toEqual([]);
  },
);

it("shows private copies without fabricated versions or restore controls", () => {
  renderWithProviders(
    <SkillSourceActions
      skill={{ name: "private", source: "custom" }}
      onChanged={async () => {}}
    />,
  );
  expect(screen.getByText(label("private"))).toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("reports a content conflict, refreshes state and does not report success", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response('{"detail":"content_conflict"}', {
          status: 409,
          headers: { "Content-Type": "application/json" },
        }),
      ),
  );
  let refreshed = 0;
  renderWithProviders(
    <SkillSourceActions
      skill={skill}
      onChanged={async () => {
        refreshed++;
      }}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: label("restore") }));
  await screen.findByRole("dialog");
  fireEvent.click(
    screen.getByRole("button", { name: i18n.t("common.confirm") }),
  );
  expect(await screen.findByText(label("conflict"))).toBeInTheDocument();
  await waitFor(() => expect(refreshed).toBe(1));
  expect(screen.queryByText(label("completed"))).not.toBeInTheDocument();
});

it("cancels restoration without writing", async () => {
  renderWithProviders(
    <SkillSourceActions skill={skill} onChanged={async () => {}} />,
  );
  fireEvent.click(screen.getByRole("button", { name: label("restore") }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(dialog.querySelector(".ant-btn-default")!);
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
  expect(writes).toEqual([]);
});

it("invalidates a pending confirmation across same-account reauthentication", async () => {
  renderWithProviders(
    <SkillSourceActions skill={skill} onChanged={async () => {}} />,
  );
  fireEvent.click(screen.getByRole("button", { name: label("restore") }));
  await screen.findByRole("dialog");
  act(() => clearAccessSession());
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
  expect(writes).toEqual([]);
});

it("keeps the installed copy after a revoked grant rejects restoration", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue(
      new Response('{"detail":"forbidden"}', {
        status: 403,
        headers: { "Content-Type": "application/json" },
      }),
    );
  vi.stubGlobal("fetch", fetch);
  renderWithProviders(
    <SkillSourceActions skill={skill} onChanged={async () => {}} />,
  );
  fireEvent.click(screen.getByRole("button", { name: label("restore") }));
  await screen.findByRole("dialog");
  fireEvent.click(
    screen.getByRole("button", { name: i18n.t("common.confirm") }),
  );
  expect(await screen.findByText(label("forbidden"))).toBeInTheDocument();
  expect(screen.getByText(label("recoverable"))).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0][0]).toBe("/api/agent-skills/damaged/restore");
  expect(screen.queryByText(label("completed"))).not.toBeInTheDocument();
});
