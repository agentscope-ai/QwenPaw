import { useCallback, useState } from "react";
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ConfigProvider, Form } from "antd";
import { AgentModal } from "./AgentModal";
import { renderWithProviders } from "@/test/common_setup";
import { useAuthStore } from "@/stores/authStore";
import { useAgentStore } from "@/stores/agentStore";
import type { AgentSummary } from "@/api/types/agents";
import i18n from "@/i18n";

let urls: string[];
let catalog: (url: string) => Promise<unknown>;
let legacyPool: unknown[];
const agent = {
  id: "target",
  name: "Target",
  enabled: true,
  backend: "qwenpaw",
  can_edit: true,
  access_role: "owner",
} as AgentSummary;
beforeEach(async () => {
  await i18n.changeLanguage("en");
  urls = [];
  legacyPool = [];
  catalog = async () => ({
    items: [
      {
        id: "s",
        name: "granted-only",
        version_id: "v",
        version: "1",
        content_hash: "a".repeat(64),
      },
    ],
  });
  useAuthStore.setState({
    mode: "multi_user",
    phase: "authenticated",
    user: { id: "alice", platform_role: "member" } as never,
  });
  useAgentStore.setState({ selectedAgent: "other", agents: [agent] });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      urls.push(url);
      const data = url.startsWith("/api/skill-catalog")
        ? await catalog(url)
        : url === "/api/skills/pool" ? legacyPool
        : url === "/api/skills"
        ? []
        : { models: [], active_llm: null, harnesses: [] };
      return new Response(JSON.stringify(data), {
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
});

it.each([null, agent])("Legacy new/edit skill picker uses only the original pool (%s)", async (editingAgent) => {
  useAuthStore.setState({ mode: "legacy", phase: "disabled", user: null } as never);
  legacyPool = [{ name: "legacy-choice", source: "custom" }];
  renderWithProviders(<Harness editingAgent={editingAgent} />);
  const choice = await screen.findByText("legacy-choice");
  fireEvent.click(choice);
  expect(choice.parentElement?.className).toContain("pickerCardSelected");
  expect(urls).toContain("/api/skills/pool");
  expect(urls.some(url => /skill-catalog|agent-skills|skill-governance/.test(url))).toBe(false);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function Harness({ editingAgent }: { editingAgent: AgentSummary | null }) {
  const [form] = Form.useForm();
  const [selected, setSelected] = useState<string[]>([]);
  const installed = useCallback(() => {}, []);
  return (
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AgentModal
        open
        editingAgent={editingAgent}
        form={form}
        selectedSkills={selected}
        onSelectedSkillsChange={setSelected}
        onInstalledSkillsLoaded={installed}
        onSave={async () => {}}
        onCancel={() => {}}
      />
    </ConfigProvider>
  );
}

it("creates an Agent without querying the administrator pool or preselecting ungranted skills", async () => {
  renderWithProviders(<Harness editingAgent={null} />);
  expect(
    await screen.findByText(i18n.t("skillGovernance.createFirst")),
  ).toBeInTheDocument();
  expect(
    urls.some(
      (url) =>
        url.startsWith("/api/skills/pool") ||
        url.startsWith("/api/skill-catalog"),
    ),
  ).toBe(false);
});
it("loads the edited Agent's authorized catalog instead of the globally selected Agent or full pool", async () => {
  renderWithProviders(<Harness editingAgent={agent} />);
  expect(await screen.findByText("granted-only")).toBeInTheDocument();
  expect(urls).toContain("/api/skill-catalog?agent_id=target");
  expect(urls).not.toContain("/api/skills/pool");
});
it("does not display a late authorized catalog after the account changes", async () => {
  let finish!: (value: unknown) => void;
  catalog = () =>
    new Promise((resolve) => {
      finish = resolve;
    });
  renderWithProviders(<Harness editingAgent={agent} />);
  await waitFor(() => expect(finish).toBeTypeOf("function"));
  act(() => useAuthStore.setState({ phase: "anonymous", user: null }));
  await act(async () =>
    finish({
      items: [
        {
          id: "old",
          name: "stale-grant",
          version_id: "v",
          version: "1",
          content_hash: "a".repeat(64),
        },
      ],
    }),
  );
  expect(screen.queryByText("stale-grant")).not.toBeInTheDocument();
});
