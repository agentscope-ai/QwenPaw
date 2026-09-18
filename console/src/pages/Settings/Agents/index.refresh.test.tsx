import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { App, ConfigProvider } from "antd";
import AgentsPage from "./index";
import { renderWithProviders } from "@/test/common_setup";
import { useAuthStore } from "@/stores/authStore";
import { useAgentStore } from "@/stores/agentStore";
import i18n from "@/i18n";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("refreshes both owned and admin lists after creating an agent changes the skill scope", async () => {
  await i18n.changeLanguage("en");
  const existing = {
    id: "existing", name: "Existing agent", enabled: true,
    backend: "qwenpaw", access_role: "owner", can_edit: true,
    owner_user_id: "admin", visibility: "private", workspace_dir: "fixture",
  };
  const created = { ...existing, id: "created", name: "Created agent" };
  useAuthStore.setState({
    mode: "multi_user", phase: "authenticated",
    user: { id: "admin", platform_role: "admin" } as never,
  });
  useAgentStore.setState({ selectedAgent: existing.id, agents: [existing] } as never);
  let saved = false;
  let adminRefreshes = 0;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    let data: unknown = { models: [], active_llm: null, harnesses: [], items: [] };
    if (url === "/api/agents" && init.method === "POST") {
      saved = true;
      data = { id: created.id };
    } else if (url === "/api/agents" || url === "/api/admin/agents") {
      if (url === "/api/admin/agents" && saved) adminRefreshes++;
      data = { agents: saved ? [existing, created] : [existing] };
    }
    return new Response(JSON.stringify(data), { headers: { "Content-Type": "application/json" } });
  }));
  renderWithProviders(<ConfigProvider theme={{ token: { motion: false } }}><App><AgentsPage /></App></ConfigProvider>);
  const allTab = () => screen.getByRole("tab", { name: new RegExp(i18n.t("agent.accessGroup.adminAll")) });
  await waitFor(() => expect(allTab()).toHaveTextContent("(1)"));
  fireEvent.click(allTab());
  fireEvent.click(screen.getByRole("button", { name: new RegExp(i18n.t("agent.create")) }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText(i18n.t("agent.name")), { target: { value: created.name } });
  fireEvent.click(within(dialog).getByRole("button", { name: i18n.t("common.save") }));
  await waitFor(() => expect(useAgentStore.getState().agents).toHaveLength(2));
  await waitFor(() => expect(allTab()).toHaveTextContent("(2)"));
  expect(adminRefreshes).toBeGreaterThan(0);
  expect(within(screen.getByRole("tabpanel")).getByText(created.name)).toBeVisible();
  fireEvent.click(screen.getByRole("tab", { name: new RegExp(i18n.t("agent.accessGroup.owner")) }));
  expect(within(screen.getByRole("tabpanel")).getByText(created.name)).toBeVisible();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
