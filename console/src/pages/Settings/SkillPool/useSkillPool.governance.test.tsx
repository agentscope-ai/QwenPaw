import {
  act,
  cleanup,
  fireEvent,
  renderHook,
  screen,
  within,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App, ConfigProvider } from "antd";
import { useSkillPool } from "./useSkillPool";
import { useAuthStore } from "@/stores/authStore";
import { useAgentStore } from "@/stores/agentStore";
import { invalidateSkillCache } from "@/api/modules/skill";
import i18n from "@/i18n";
vi.mock("@agentscope-ai/design", async () => vi.importActual("antd"));
const resultRows = [
  { agent_id: "other", status: "failed", reason: "batch_rolled_back" },
  { agent_id: "detached", status: "skipped", reason: "detached" },
];
beforeEach(async () => {
  await i18n.changeLanguage("en");
  useAuthStore.setState({
    mode: "multi_user",
    phase: "authenticated",
    user: { id: "admin", platform_role: "admin" } as never,
  });
  useAgentStore.setState({ selectedAgent: "a", agents: [] });
  invalidateSkillCache();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const data = url.endsWith("/initialization/preview")
        ? { items: [] }
        : url.endsWith("/items")
        ? { items: [] }
        : url.endsWith("/auto-update")
        ? {
            updated: true,
            sync: { results: [{ name: "draft", results: resultRows }] },
          }
        : url.endsWith("/builtin-notice")
        ? { has_updates: false }
        : [];
      return new Response(JSON.stringify(data), {
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("retains per-target failures when enabling pool automatic updates", async () => {
  const { result } = renderHook(() => useSkillPool(), {
    wrapper: ({ children }) => (
      <ConfigProvider theme={{ token: { motion: false } }}>
        <App>{children}</App>
      </ConfigProvider>
    ),
  });
  await waitFor(() => expect(result.current.loading).toBe(false));
  await act(async () =>
    result.current.handleToggleAutoUpdate(
      { name: "draft", source: "custom" },
      true,
    ),
  );
  expect(result.current.broadcastResults).toEqual(resultRows);
});

it("broadcast carries only explicitly confirmed per-target hash and source version", async () => {
  const writes: Array<Record<string, unknown>> = [];
  const hash = "a".repeat(64);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      let data: unknown = [];
      if (url.endsWith("/items"))
        data = { items: [{ id: "s", name: "sample" }] };
      if (url.endsWith("/broadcast")) {
        const body = JSON.parse(init.body as string) as Record<string, unknown>;
        writes.push(body);
        data = {
          results: [
            {
              agent_id: "a",
              name: "sample",
              status: body?.preview_only ? "ready" : "updated",
              reason: "",
              expected_content_hash: hash,
              expected_version_id: "v2",
            },
          ],
        };
      }
      return new Response(JSON.stringify(data), {
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  const { result } = renderHook(() => useSkillPool(), {
    wrapper: ({ children }) => (
      <ConfigProvider theme={{ token: { motion: false } }}>
        <App>{children}</App>
      </ConfigProvider>
    ),
  });
  await waitFor(() => expect(result.current.loading).toBe(false));
  let pending!: Promise<void>;
  act(() => {
    pending = result.current.handleBroadcast(["sample"], ["a"]);
  });
  const dialog = await screen.findByRole("dialog");
  expect(writes).toHaveLength(1);
  expect(within(dialog).queryByText(new RegExp(hash))).not.toBeInTheDocument();
  expect(within(dialog).getByText(/Ready to install or update/)).toBeInTheDocument();
  fireEvent.click(
    within(dialog).getByRole("button", {
      name: new RegExp(i18n.t("common.confirm")),
    }),
  );
  await act(async () => pending);
  expect(writes[1]).toEqual({
    agent_ids: ["a"],
    preview_only: false,
    overwrite: true,
    confirmations: {
      a: { expected_content_hash: hash, expected_version_id: "v2" },
    },
  });
});

it("registers selected drafts and grants selected Agents before broadcasting", async () => {
  const writes: Array<{ url: string; body?: Record<string, unknown> }> = [];
  const hash = "b".repeat(64);
  let registered = false;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const body = init.body
        ? (JSON.parse(init.body as string) as Record<string, unknown>)
        : undefined;
      if (init.method && init.method !== "GET") writes.push({ url, body });
      let data: unknown = [];
      if (url.endsWith("/initialization/preview")) {
        data = { items: [{ name: "draft", content_hash: hash }] };
      } else if (url.endsWith("/initialization/import")) {
        registered = true;
        data = { imported: 1 };
      } else if (url.endsWith("/items")) {
        data = {
          items: registered
            ? [{ id: "s", name: "draft", content_hash: hash }]
            : [],
        };
      } else if (url.includes("/agent-grants/")) {
        data = { enabled: true };
      } else if (url.endsWith("/broadcast")) {
        data = {
          results: [
            {
              agent_id: "a",
              name: "draft",
              status: body?.preview_only ? "ready" : "updated",
              reason: "",
              expected_content_hash: null,
              expected_version_id: "v1",
            },
          ],
        };
      }
      return new Response(JSON.stringify(data), {
        headers: { "Content-Type": "application/json" },
      });
    }),
  );

  const { result } = renderHook(() => useSkillPool(), {
    wrapper: ({ children }) => (
      <ConfigProvider theme={{ token: { motion: false } }}>
        <App>{children}</App>
      </ConfigProvider>
    ),
  });
  await waitFor(() => expect(result.current.loading).toBe(false));

  let pending!: Promise<void>;
  act(() => {
    pending = result.current.handleBroadcast(["draft"], ["a"]);
  });
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(
    within(dialog).getByRole("button", {
      name: new RegExp(i18n.t("common.confirm")),
    }),
  );
  await act(async () => pending);

  expect(writes.some(({ url }) => url.endsWith("/initialization/import"))).toBe(
    true,
  );
  expect(writes.some(({ url }) => url.endsWith("/agent-grants/a"))).toBe(true);
  expect(writes.filter(({ url }) => url.endsWith("/broadcast"))).toHaveLength(
    2,
  );
});

it("publishes the selected pool skill as an immutable version after confirmation", async () => {
  const hash = "c".repeat(64);
  const writes: Array<{ url: string; body?: unknown }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const body = init.body ? JSON.parse(init.body as string) : undefined;
      if (init.method && init.method !== "GET") writes.push({ url, body });
      let data: unknown = [];
      if (url.endsWith("/initialization/preview"))
        data = { items: [{ name: "draft", content_hash: hash }] };
      else if (url.endsWith("/items")) data = { items: [] };
      else if (url.endsWith("/builtin-notice")) data = { has_updates: false };
      else if (url.endsWith("/initialization/import")) data = { imported: 1 };
      return new Response(JSON.stringify(data), {
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  const { result } = renderHook(() => useSkillPool(), {
    wrapper: ({ children }) => (
      <ConfigProvider theme={{ token: { motion: false } }}>
        <App>{children}</App>
      </ConfigProvider>
    ),
  });
  await waitFor(() => expect(result.current.loading).toBe(false));
  let pending!: Promise<void>;
  act(() => {
    pending = result.current.handlePublish({ name: "draft", source: "custom" });
  });
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText(hash)).toBeInTheDocument();
  fireEvent.click(
    within(dialog).getByRole("button", {
      name: new RegExp(i18n.t("common.confirm")),
    }),
  );
  await act(async () => pending);
  expect(
    writes.find(({ url }) => url.endsWith("/initialization/import"))?.body,
  ).toEqual({ items: [{ name: "draft", content_hash: hash }] });
});
