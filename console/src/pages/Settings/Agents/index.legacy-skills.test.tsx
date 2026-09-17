import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App, ConfigProvider } from "antd";
import AgentsPage from "./index";
import { renderWithProviders } from "@/test/common_setup";
import { useAuthStore } from "@/stores/authStore";
import { useAgentStore } from "@/stores/agentStore";
import { invalidateSkillCache } from "@/api/modules/skill";
import i18n from "@/i18n";

const agent = { id: "target", name: "Legacy Agent", enabled: true, backend: "qwenpaw", access_role: "owner", can_edit: true, workspace_dir: "fixture" };
let calls: Array<{ url: string; method: string; body?: Record<string, unknown> }>;
beforeEach(async () => {
  await i18n.changeLanguage("en");
  calls = [];
  useAuthStore.setState({ mode: "legacy", phase: "disabled", user: null } as never);
  useAgentStore.setState({ selectedAgent: "target", agents: [agent] } as never);
  invalidateSkillCache();
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    const method = init.method || "GET";
    calls.push({ url, method, body: typeof init.body === "string" ? JSON.parse(init.body) : undefined });
    const data = url === "/api/agents" ? (method === "GET" ? { agents: [agent] } : { id: "created" })
      : url === "/api/agents/target" ? agent
      : url === "/api/skills/pool" ? [{ name: "legacy-choice", source: "custom" }]
      : url === "/api/skills" ? []
      : url === "/api/skills/pool/download" ? { downloaded: [{ workspace_id: "target", name: "legacy-choice" }] }
      : { models: [], active_llm: null, harnesses: [] };
    return new Response(JSON.stringify(data), { headers: { "Content-Type": "application/json" } });
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it.each([false, true])("Legacy Agent save carries the selected skills through the original create/edit network flow (%s)", async (editing) => {
  renderWithProviders(<ConfigProvider theme={{ token: { motion: false } }}><App><AgentsPage /></App></ConfigProvider>);
  await screen.findByText("Legacy Agent");
  if (editing) fireEvent.click(screen.getByRole("img", { name: "edit" }).closest("button")!);
  else fireEvent.click(screen.getByRole("button", { name: new RegExp(i18n.t("agent.create")) }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(await within(dialog).findByText("legacy-choice"));
  if (!editing) fireEvent.change(within(dialog).getByLabelText(i18n.t("agent.name")), { target: { value: "Created Legacy" } });
  fireEvent.click(within(dialog).getByRole("button", { name: i18n.t("common.save") }));
  await waitFor(() => expect(calls.some(c => c.url === (editing ? "/api/agents/target" : "/api/agents") && c.method === (editing ? "PUT" : "POST"))).toBe(true));
  if (editing) expect(calls.find(c => c.url === "/api/skills/pool/download")?.body).toEqual({ skill_name: "legacy-choice", targets: [{ workspace_id: "target" }] });
  else expect(calls.find(c => c.url === "/api/agents" && c.method === "POST")?.body?.skill_names).toEqual(["legacy-choice"]);
  expect(calls.some(c => /skill-catalog|agent-skills|skill-governance/.test(c.url))).toBe(false);
});
