import {
  act,
  cleanup,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ConfigProvider } from "antd";
import GovernancePanel from "./GovernancePanel";
import { renderWithProviders } from "@/test/common_setup";
import { useAuthStore } from "@/stores/authStore";
import { useAgentStore } from "@/stores/agentStore";
import i18n from "@/i18n";

const hash = "a".repeat(64);
const label = (key: string) => i18n.t(`skillGovernance.${key}`);
const publication = {
  id: "req-1",
  skill_name: "snapshot-skill",
  submitted_by: "owner-42",
  status: "pending",
  content_hash: hash,
  review_version: 3,
  published_version_id: null,
  reviewed_by: null,
  review_note: null,
  created_at: null,
  reviewed_at: null,
};
let calls: Array<{ url: string; method: string; body?: unknown }>;
let respond: (url: string, init: RequestInit) => unknown;
beforeEach(async () => {
  await i18n.changeLanguage("en");
  useAuthStore.setState({
    mode: "multi_user",
    phase: "authenticated",
    user: { id: "admin", platform_role: "admin" } as never,
  });
  useAgentStore.setState({ selectedAgent: "mine", agents: [] });
  calls = [];
  respond = (url) => {
    if (url === "/api/admin/agents")
      return {
        agents: [
          { id: "not-in-store", name: "Other owner's Agent", enabled: true },
        ],
      };
    if (url.endsWith("/initialization/preview"))
      return {
        items: [
          { name: "draft-a", content_hash: hash },
          { name: "draft-b", content_hash: "b".repeat(64) },
        ],
      };
    if (url.endsWith("/items"))
      return {
        items: [
          {
            id: "skill-1",
            name: "published",
            status: "active",
            version_id: "v1",
            version: "1",
            content_hash: hash,
          },
        ],
      };
    if (url.endsWith("/agent-grants")) return { grants: [] };
    if (url.endsWith("/requests")) return { requests: [publication] };
    if (url.endsWith("/requests/req-1"))
      return { ...publication, files: ["scripts/example.txt"] };
    if (url.endsWith("/files/scripts/example.txt"))
      return { content: "fixed snapshot A" };
    return {};
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      calls.push({
        url,
        method: init.method ?? "GET",
        ...(init.body ? { body: JSON.parse(init.body as string) } : {}),
      });
      const value = await respond(url, init);
      return value instanceof Response
        ? value
        : new Response(JSON.stringify(value), {
            headers: { "Content-Type": "application/json" },
          });
    }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const renderPanel = (view: "published" | "requests" = "published") =>
  renderWithProviders(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <GovernancePanel view={view} />
    </ConfigProvider>,
  );

it("separates published skills from publication requests", async () => {
  const { unmount } = renderPanel("published");
  expect(await screen.findByText("published")).toBeInTheDocument();
  expect(screen.queryByText("snapshot-skill")).not.toBeInTheDocument();
  unmount();
  renderPanel("requests");
  expect(await screen.findByText("snapshot-skill")).toBeInTheDocument();
  expect(screen.queryByText("published")).not.toBeInTheDocument();
});

it("reviews the displayed immutable files with the displayed expected version", async () => {
  renderPanel("requests");
  fireEvent.click(
    await screen.findByRole("button", { name: label("reviewAction") }),
  );
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText(/owner-42/)).toBeInTheDocument();
  fireEvent.click(
    await within(dialog).findByRole("button", { name: "scripts/example.txt" }),
  );
  expect(
    await within(dialog).findByText("fixed snapshot A"),
  ).toBeInTheDocument();
  expect(within(dialog).getByText(hash)).toBeInTheDocument();
  expect(calls.some((c) => c.url.endsWith("/review"))).toBe(false);
  fireEvent.change(
    within(dialog).getByRole("textbox", { name: label("note") }),
    { target: { value: "Reviewed snapshot A" } },
  );
  fireEvent.click(
    within(dialog).getByRole("button", { name: label("approve") }),
  );
  await waitFor(() =>
    expect(calls.find((c) => c.url.endsWith("/review"))?.body).toEqual({
      decision: "approve",
      expected_version: 3,
      note: "Reviewed snapshot A",
    }),
  );
  expect(calls.some((c) => c.url.startsWith("/api/skills/pool"))).toBe(false);
});

it("offers administrator Agent targets beyond the current user's store without auto-granting", async () => {
  renderPanel("published");
  fireEvent.click(await screen.findByRole("button", { name: label("grants") }));
  const select = await screen.findByRole("combobox", {
    name: label("selectAgent"),
  });
  fireEvent.mouseDown(select);
  fireEvent.click(await screen.findByText("Other owner's Agent"));
  expect(calls.some((c) => c.method === "PUT")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: label("grant") }));
  await waitFor(() =>
    expect(calls.find((c) => c.method === "PUT")).toEqual({
      url: "/api/skill-governance/items/skill-1/agent-grants/not-in-store",
      method: "PUT",
      body: { enabled: true },
    }),
  );
});

it("does not fetch administrator data for an ordinary user", () => {
  useAuthStore.setState({
    user: { id: "member", platform_role: "member" } as never,
  });
  renderPanel("published");
  expect(calls).toEqual([]);
  expect(
    screen.queryByRole("button", { name: label("grants") }),
  ).not.toBeInTheDocument();
});

it("discards administrator data that resolves after an account switch", async () => {
  let finish!: (value: unknown) => void;
  const normal = respond;
  respond = (url, init) =>
    url.endsWith("/items")
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : normal(url, init);
  renderPanel("published");
  await waitFor(() => expect(finish).toBeTypeOf("function"));
  act(() =>
    useAuthStore.setState({
      user: { id: "member", platform_role: "member" } as never,
    }),
  );
  await act(async () => {
    finish({ items: [{ id: "secret", name: "stale-admin-item" }] });
  });
  expect(screen.queryByText("stale-admin-item")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: label("approve") }),
  ).not.toBeInTheDocument();
});

it("allows rejection only for a legacy request without a fixed snapshot", async () => {
  const normal = respond;
  respond = (url, init) =>
    url.endsWith("/requests")
      ? { requests: [{ ...publication, content_hash: null }] }
      : normal(url, init);
  renderPanel("requests");
  fireEvent.click(
    await screen.findByRole("button", { name: label("reviewAction") }),
  );
  const dialog = await screen.findByRole("dialog");
  expect(
    within(dialog).getByRole("button", { name: label("approve") }),
  ).toBeDisabled();
  expect(within(dialog).getByText(label("noSnapshot"))).toBeInTheDocument();
  fireEvent.click(
    within(dialog).getByRole("button", { name: label("reject") }),
  );
  await waitFor(() =>
    expect(calls.find((c) => c.url.endsWith("/review"))?.body).toEqual({
      decision: "reject",
      expected_version: 3,
      note: "",
    }),
  );
  expect(calls.some((c) => c.url.endsWith("/requests/req-1"))).toBe(false);
});

it("refreshes a conflicting review version without silently approving again", async () => {
  let version = 3;
  const normal = respond;
  respond = (url, init) => {
    if (url.endsWith("/review")) {
      version = 4;
      return new Response('{"detail":"version_conflict"}', {
        status: 409,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url.endsWith("/requests/req-1"))
      return {
        ...publication,
        review_version: version,
        files: ["scripts/example.txt"],
      };
    return normal(url, init);
  };
  renderPanel("requests");
  fireEvent.click(
    await screen.findByRole("button", { name: label("reviewAction") }),
  );
  const dialog = await screen.findByRole("dialog");
  await waitFor(() =>
    expect(
      within(dialog).getByRole("button", { name: label("approve") }),
    ).toBeEnabled(),
  );
  fireEvent.click(
    within(dialog).getByRole("button", { name: label("approve") }),
  );
  expect(
    await within(dialog).findByText(label("conflict")),
  ).toBeInTheDocument();
  expect(
    within(dialog).getByText(new RegExp(label("reviewVersion") + ": 4")),
  ).toBeInTheDocument();
  expect(calls.filter((c) => c.url.endsWith("/review"))).toHaveLength(1);
});

it("changes active status and revokes an explicit Agent grant without deleting a copy", async () => {
  const normal = respond;
  respond = (url, init) =>
    url.endsWith("/agent-grants")
      ? {
          grants: [
            {
              agent_id: "not-in-store",
              agent_database_id: "db-id",
              enabled: true,
            },
          ],
        }
      : normal(url, init);
  renderPanel("published");
  fireEvent.click(
    await screen.findByRole("switch", { name: new RegExp("published") }),
  );
  await waitFor(() =>
    expect(calls.some((c) => c.url.endsWith("/status"))).toBe(true),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: label("grants") })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: label("grants") }));
  fireEvent.click(await screen.findByRole("button", { name: label("revoke") }));
  await waitFor(() =>
    expect(
      calls.find((c) => c.url.endsWith("/agent-grants/not-in-store"))?.body,
    ).toEqual({ enabled: false }),
  );
  expect(
    calls.some(
      (c) => c.method === "DELETE" || c.url.startsWith("/api/agent-skills"),
    ),
  ).toBe(false);
});

it("shows a processed request as read-only details", async () => {
  const approved = {
    ...publication,
    status: "approved",
    reviewed_by: "admin-1",
    reviewed_at: "2026-09-14T10:00:00Z",
    review_note: "accepted",
  };
  const normal = respond;
  respond = (url, init) => {
    if (url.endsWith("/requests")) return { requests: [approved] };
    if (url.endsWith("/requests/req-1"))
      return { ...approved, files: ["SKILL.md"] };
    return normal(url, init);
  };
  renderPanel("requests");
  fireEvent.click(
    await screen.findByRole("button", { name: label("viewDetails") }),
  );
  const dialog = await screen.findByRole("dialog");
  expect(
    within(dialog).queryByRole("button", { name: label("approve") }),
  ).not.toBeInTheDocument();
  expect(
    within(dialog).queryByRole("button", { name: label("reject") }),
  ).not.toBeInTheDocument();
  expect(within(dialog).getByText(/admin-1/)).toBeInTheDocument();
  expect(
    within(dialog).getAllByRole("button", { name: i18n.t("common.close") }),
  ).toHaveLength(2);
});
