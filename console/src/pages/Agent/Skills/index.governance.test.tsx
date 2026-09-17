import {
  act,
  cleanup,
  fireEvent,
  screen,
  waitFor,
  within,
  renderHook,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App, ConfigProvider, Modal } from "antd";
import SkillsPage from "./index";
import { useSkillsPage } from "./useSkillsPage";
import { renderWithProviders } from "@/test/common_setup";
import { useAuthStore } from "@/stores/authStore";
import { useAgentStore } from "@/stores/agentStore";
import { skillApi, invalidateSkillCache } from "@/api/modules/skill";
import i18n from "@/i18n";

// Use interactive vendor components instead of the global design pass-through stub.
vi.mock("@agentscope-ai/design", async () => {
  const antd = await vi.importActual<typeof import("antd")>("antd");
  return { ...antd, IconButton: antd.Button };
});
const hash = "a".repeat(64);
let calls: Array<{
  url: string;
  method: string;
  body?: unknown;
  agent: string | null;
}>;
let installed: Array<Record<string, unknown>>;
let catalog: () => Promise<unknown>;
let onRead: (url: string) => Promise<unknown>;
let onWrite: (url: string, body: unknown) => Promise<unknown>;
const text = (key: string) => i18n.t(key);
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
    accessToken: "session-1",
  });
  useAgentStore.setState({
    selectedAgent: "a",
    agents: [
      {
        id: "a",
        name: "Agent A",
        enabled: true,
        backend: "qwenpaw",
        access_role: "owner",
        can_edit: true,
      },
    ] as never,
  });
  invalidateSkillCache();
  calls = [];
  installed = [
    {
      name: "private-one",
      source: "custom",
      enabled: true,
      description: "local document",
    },
  ];
  catalog = async () => ({
    items: [
      {
        id: "skill-id",
        name: "authorized",
        version_id: "version-id",
        version: "1",
        content_hash: hash,
      },
    ],
  });
  onWrite = async () => ({});
  onRead = async () => ({
    items: [],
    enabled: false,
    records: [],
    blocked: [],
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      const method = init.method ?? "GET";
      const body =
        typeof init.body === "string" ? JSON.parse(init.body) : undefined;
      calls.push({
        url,
        method,
        body,
        agent: new Headers(init.headers).get("X-Agent-Id"),
      });
      let data: unknown;
      if (url === "/api/skills" || url === "/api/skills/refresh")
        data = installed;
      else if (url.startsWith("/api/skill-catalog")) data = await catalog();
      else if (method !== "GET") data = await onWrite(url, body);
      else data = await onRead(url);
      return data instanceof Response
        ? data
        : new Response(JSON.stringify(data), {
            headers: { "Content-Type": "application/json" },
          });
    }),
  );
});
afterEach(() => {
  Modal.destroyAll();
  ConfigProvider.config({ holderRender: undefined });
  cleanup();
  vi.unstubAllGlobals();
});
function renderPage() {
  return renderWithProviders(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App>
        <SkillsPage />
      </App>
    </ConfigProvider>,
  );
}
async function openCatalog() {
  fireEvent.mouseOver(
    await screen.findByRole("button", {
      name: new RegExp(text("skills.addSkill")),
    }),
  );
  fireEvent.click(
    await screen.findByRole("menuitem", {
      name: new RegExp(text("skills.downloadFromPool")),
    }),
  );
  return screen.findByRole("dialog");
}

it("Legacy downloads from the original pool without PG governance", async () => {
  useAuthStore.setState({ mode: "legacy", phase: "disabled", user: null } as never);
  onRead = async (url) => url === "/api/skills/pool" ? [{ name: "legacy-skill", source: "custom" }] : [];
  onWrite = async () => ({ downloaded: [{ workspace_id: "a", name: "legacy-skill" }] });
  renderPage();
  const dialog = await openCatalog();
  fireEvent.click(await within(dialog).findByText("legacy-skill"));
  fireEvent.click(within(dialog).getByRole("button", { name: new RegExp(text("common.confirm")) }));
  await waitFor(() => expect(calls.some(c => c.url === "/api/skills/pool/download" && (c.body as { preview_only?: boolean })?.preview_only !== true)).toBe(true));
  expect(calls.some(c => /skill-catalog|agent-skills|skill-governance/.test(c.url))).toBe(false);
});

it("Legacy uploads workspace skills with the original upload action", async () => {
  useAuthStore.setState({ mode: "legacy", phase: "disabled", user: null } as never);
  onWrite = async () => ({ success: true, name: "private-one" });
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: new RegExp(text("skills.uploadToPool")) }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(await within(dialog).findByText("private-one"));
  fireEvent.click(within(dialog).getByRole("button", { name: new RegExp(text("common.confirm")) }));
  await waitFor(() => expect(calls.some(c => c.url === "/api/skills/pool/upload" && (c.body as { preview_only?: boolean })?.preview_only !== true)).toBe(true));
  expect(calls.some(c => /skill-catalog|agent-skills|skill-governance/.test(c.url))).toBe(false);
});

it("rename confirmation sends the target directory hash once and leaves edits open on stale confirmation", async () => {
  const detail = { name: "private-one", source: "custom", content: "---\nname: private-one\ndescription: fixture\n---\nA" };
  onRead = async () => detail;
  onWrite = async (_url, body) => new Response(JSON.stringify({ detail:
    (body as { overwrite?: boolean }).overwrite ? "content_conflict" : { reason: "conflict", expected_content_hash: hash, suggested_name: "target-2" }
  }), { status: 409, headers: { "Content-Type": "application/json" } });
  const { result } = renderHook(() => useSkillsPage(), { wrapper: ({ children }) => <ConfigProvider theme={{ token: { motion: false } }}><App>{children}</App></ConfigProvider> });
  await waitFor(() => expect(result.current.loading).toBe(false));
  await act(async () => result.current.handleEdit(detail));
  let pending!: Promise<void>;
  act(() => { pending = result.current.handleSubmit({ ...detail, name: "target" }); });
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText(hash)).toBeInTheDocument();
  expect(calls.filter(c => c.url === "/api/skills/save")).toHaveLength(1);
  fireEvent.click(within(dialog).getByRole("button", { name: new RegExp(text("common.confirm")) }));
  await act(async () => pending);
  const writes = calls.filter(c => c.url === "/api/skills/save");
  expect(writes).toHaveLength(2);
  expect(writes[1].body).toMatchObject({ source_name: "private-one", name: "target", overwrite: true, expected_content_hash: hash });
  expect(result.current.drawerOpen).toBe(true);
});

it("loads a catalog item without a description using the immutable API and explicit Agent", async () => {
  renderPage();
  const dialog = await openCatalog();
  fireEvent.click(await within(dialog).findByText("authorized"));
  expect(calls.some((c) => c.method === "POST")).toBe(false);
  fireEvent.click(
    within(dialog).getByRole("button", {
      name: new RegExp(text("common.confirm")),
    }),
  );
  await waitFor(() =>
    expect(calls.find((c) => c.url === "/api/agent-skills/load")).toMatchObject(
      {
        method: "POST",
        body: { agent_id: "a", skill_id: "skill-id" },
        agent: "a",
      },
    ),
  );
  expect(calls.some((c) => c.url.startsWith("/api/skills/pool"))).toBe(false);
});

it("shows an explicit empty authorized catalog", async () => {
  catalog = async () => ({ items: [] });
  renderPage();
  const dialog = await openCatalog();
  expect(
    await within(dialog).findByText(text("skillGovernance.emptyCatalog")),
  ).toBeInTheDocument();
});

it("lets an administrator register, grant, and load a pool draft for the selected Agent", async () => {
  useAuthStore.setState({
    user: { id: "admin", platform_role: "admin" } as never,
  });
  const draftHash = "b".repeat(64);
  let registered = false;
  onRead = async (url) => {
    if (url.endsWith("/items")) {
      return {
        items: registered
          ? [
              {
                id: "draft-id",
                name: "pool-draft",
                version_id: "draft-version",
                version: "1",
                content_hash: draftHash,
                status: "active",
              },
            ]
          : [],
      };
    }
    return { items: [] };
  };
  onWrite = async (url) => {
    if (url.endsWith("/initialization/preview")) {
      return { items: [{ name: "pool-draft", content_hash: draftHash }] };
    }
    if (url.endsWith("/initialization/import")) registered = true;
    return {};
  };

  renderPage();
  const dialog = await openCatalog();
  fireEvent.click(await within(dialog).findByText("pool-draft"));
  fireEvent.click(
    within(dialog).getByRole("button", {
      name: new RegExp(text("common.confirm")),
    }),
  );

  await waitFor(() =>
    expect(calls.some((call) => call.url === "/api/agent-skills/load")).toBe(
      true,
    ),
  );
  expect(calls.map((call) => call.url)).toEqual(
    expect.arrayContaining([
      "/api/skill-governance/initialization/import",
      "/api/skill-governance/items/draft-id/agent-grants/a",
      "/api/agent-skills/load",
    ]),
  );
});

it.each(["owner", "collaborator", "user"])(
  "exposes publication only to owner while preserving %s private skills",
  async (role) => {
    useAgentStore.setState({
      agents: [
        {
          id: "a",
          name: "Agent A",
          backend: "qwenpaw",
          enabled: true,
          access_role: role,
          can_edit: role !== "user",
        },
      ] as never,
    });
    renderPage();
    expect(await screen.findByText("private-one")).toBeInTheDocument();
    expect(
      !!screen.queryByRole("button", {
        name: new RegExp(text("skillGovernance.submit")),
      }),
    ).toBe(role === "owner");
    if (role === "owner") {
      fireEvent.click(
        screen.getByRole("button", {
          name: new RegExp(text("skillGovernance.submit")),
        }),
      );
      const dialog = await screen.findByRole("dialog");
      fireEvent.click(within(dialog).getByText("private-one"));
      fireEvent.click(
        within(dialog).getByRole("button", {
          name: new RegExp(text("common.confirm")),
        }),
      );
      await waitFor(() =>
        expect(
          calls.find((c) => c.url === "/api/skill-governance/requests")?.body,
        ).toEqual({ agent_id: "a", skill_name: "private-one" }),
      );
    }
    expect(calls.some((c) => c.url.startsWith("/api/skills/pool"))).toBe(false);
  },
);

it("discards a late catalog and old selection after switching accounts", async () => {
  let finish!: (value: unknown) => void;
  catalog = () =>
    new Promise((resolve) => {
      finish = resolve;
    });
  renderPage();
  await openCatalog();
  await waitFor(() => expect(finish).toBeTypeOf("function"));
  act(() =>
    useAuthStore.setState({
      user: { id: "bob", platform_role: "member" } as never,
    }),
  );
  await act(async () =>
    finish({
      items: [
        {
          id: "old",
          name: "old-authorized",
          version_id: "v",
          version: "1",
          content_hash: hash,
        },
      ],
    }),
  );
  expect(screen.queryByText("old-authorized")).not.toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(calls.some((c) => c.method === "POST")).toBe(false);
});

it("does not continue a batch publication under a new account", async () => {
  installed.push({ name: "private-two", source: "custom", enabled: true });
  let finish!: (value: unknown) => void;
  onWrite = () =>
    new Promise((resolve) => {
      finish = resolve;
    });
  renderPage();
  fireEvent.click(
    await screen.findByRole("button", {
      name: new RegExp(text("skillGovernance.submit")),
    }),
  );
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(await within(dialog).findByText("private-one"));
  fireEvent.click(within(dialog).getByText("private-two"));
  fireEvent.click(
    within(dialog).getByRole("button", {
      name: new RegExp(text("common.confirm")),
    }),
  );
  await waitFor(() => expect(finish).toBeTypeOf("function"));
  act(() =>
    useAuthStore.setState({
      user: { id: "bob", platform_role: "member" } as never,
    }),
  );
  await act(async () =>
    finish({
      id: "request",
      status: "pending",
      review_version: 0,
      content_hash: hash,
    }),
  );
  expect(calls.filter((c) => c.method === "POST")).toHaveLength(1);
  expect(calls.find((c) => c.method === "POST")?.body).toEqual({
    agent_id: "a",
    skill_name: "private-one",
  });
});

it("confirms an existing-name collision with its current installed hash", async () => {
  installed.push({
    name: "authorized",
    source: "custom",
    enabled: true,
    content_hash: hash,
  });
  renderPage();
  const dialog = await openCatalog();
  fireEvent.click(await within(dialog).findByText("authorized"));
  fireEvent.click(
    within(dialog).getByRole("button", {
      name: new RegExp(text("common.confirm")),
    }),
  );
  await waitFor(() => expect(screen.getAllByRole("dialog")).toHaveLength(2));
  expect(calls.some((c) => c.url === "/api/agent-skills/load")).toBe(false);
  const confirm = screen.getAllByRole("dialog")[1];
  fireEvent.click(
    within(confirm).getByRole("button", {
      name: new RegExp(text("common.confirm")),
    }),
  );
  await waitFor(() =>
    expect(calls.find((c) => c.url === "/api/agent-skills/load")?.body).toEqual(
      {
        agent_id: "a",
        skill_id: "skill-id",
        overwrite: true,
        expected_content_hash: hash,
      },
    ),
  );
});

it.each(["update", "restore"])(
  "refreshes the actual page and populated cache after source %s succeeds",
  async (action) => {
    const nextHash = "b".repeat(64);
    installed = [
      {
        name: "bound-copy",
        source: "custom",
        enabled: true,
        source_pool_version_id: "v1",
        source_pool_version: "1",
        detached: true,
        update_available: true,
        content_hash: hash,
      },
    ];
    onWrite = async () => {
      installed = [
        {
          ...installed[0],
          source_pool_version_id: "v2",
          source_pool_version: "2",
          detached: false,
          update_available: false,
          content_hash: nextHash,
        },
      ];
      return installed[0];
    };
    renderPage();
    await screen.findByText(
      text("skillGovernance.sourceVersion").replace("{{version}}", "1"),
    );
    expect((await skillApi.listSkills("a"))[0].content_hash).toBe(hash);
    expect(calls.filter((c) => c.url === "/api/skills")).toHaveLength(1);
    fireEvent.click(
      screen.getByRole("button", { name: text("skillGovernance." + action) }),
    );
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: new RegExp(text("common.confirm")),
      }),
    );
    await waitFor(() =>
      expect(
        screen.getByText(
          i18n.t("skillGovernance.sourceVersion", { version: "2" }),
        ),
      ).toBeInTheDocument(),
    );
    expect(
      screen.queryByText(text("skillGovernance.recoverable")),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(text("skillGovernance.updateAvailable")),
    ).not.toBeInTheDocument();
    expect((await skillApi.listSkills("a"))[0].content_hash).toBe(nextHash);
    expect(calls.filter((c) => c.url === "/api/skills")).toHaveLength(2);
  },
);

it.each(["update", "restore"])(
  "uses fresh H2 for the next source %s confirmation after a 409 on H1",
  async (action) => {
    const nextHash = "b".repeat(64);
    installed = [
      {
        name: "bound-copy",
        source: "custom",
        enabled: true,
        source_pool_version_id: "v1",
        source_pool_version: "1",
        detached: true,
        update_available: true,
        content_hash: hash,
      },
    ];
    onWrite = async () => {
      installed = [{ ...installed[0], content_hash: nextHash }];
      return new Response('{"detail":"content_conflict"}', {
        status: 409,
        headers: { "Content-Type": "application/json" },
      });
    };
    renderPage();
    fireEvent.click(
      await screen.findByRole("button", {
        name: text("skillGovernance." + action),
      }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(hash)).toBeInTheDocument();
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: new RegExp(text("common.confirm")),
      }),
    );
    await screen.findByText(text("skillGovernance.conflict"));
    await waitFor(() =>
      expect(calls.filter((c) => c.url === "/api/skills")).toHaveLength(2),
    );
    expect((await skillApi.listSkills("a"))[0].content_hash).toBe(nextHash);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: text("skillGovernance." + action) }),
      ).toBeEnabled(),
    );
    expect(
      screen.getByText(text("skillGovernance.conflict")),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: text("skillGovernance." + action) }),
    );
    expect(
      await within(await screen.findByRole("dialog")).findByText(nextHash),
    ).toBeInTheDocument();
    expect(calls.filter((c) => c.url.endsWith("/" + action))).toHaveLength(1);
  },
);

it("refreshes the cached installed hash after a load conflict before asking again", async () => {
  const nextHash = "b".repeat(64);
  installed.push({
    name: "authorized",
    source: "custom",
    enabled: true,
    content_hash: hash,
  });
  onWrite = async () => {
    installed = installed.map((skill) =>
      skill.name === "authorized"
        ? { ...skill, content_hash: nextHash }
        : skill,
    );
    return new Response('{"detail":"content_conflict"}', {
      status: 409,
      headers: { "Content-Type": "application/json" },
    });
  };
  renderPage();
  const dialog = await openCatalog();
  fireEvent.click(await within(dialog).findByText("authorized"));
  fireEvent.click(
    within(dialog).getByRole("button", {
      name: new RegExp(text("common.confirm")),
    }),
  );
  await waitFor(() => expect(screen.getAllByRole("dialog")).toHaveLength(2));
  const confirm = screen.getAllByRole("dialog")[1];
  expect(within(confirm).getByText(hash)).toBeInTheDocument();
  fireEvent.click(
    within(confirm).getByRole("button", {
      name: new RegExp(text("common.confirm")),
    }),
  );
  await within(dialog).findByText(text("skillGovernance.conflict"));
  await waitFor(() =>
    expect(calls.filter((c) => c.url === "/api/skills")).toHaveLength(2),
  );
  expect(
    (await skillApi.listSkills("a")).find((s) => s.name === "authorized")
      ?.content_hash,
  ).toBe(nextHash);
  fireEvent.click(
    within(dialog).getByRole("button", { name: text("common.cancel") }),
  );
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
  const reopened = await openCatalog();
  fireEvent.click(await within(reopened).findByText("authorized"));
  fireEvent.click(
    within(reopened).getByRole("button", {
      name: new RegExp(text("common.confirm")),
    }),
  );
  await waitFor(() => expect(screen.getAllByRole("dialog")).toHaveLength(2));
  expect(
    within(screen.getAllByRole("dialog")[1]).getByText(nextHash),
  ).toBeInTheDocument();
  expect(calls.filter((c) => c.url === "/api/agent-skills/load")).toHaveLength(
    1,
  );
});

async function selectBatch() {
  await screen.findByText("private-one");
  fireEvent.click(
    screen.getByRole("button", { name: text("skills.batchOperation") }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: text("skills.selectAll") }),
  );
}
const scanFindings = [
  {
    title: "Old actor scan finding",
    file_path: "SKILL.md",
    description: "synthetic",
  },
];

it("drops late scan findings from the actual batch-enable page wiring", async () => {
  let finish!: (value: unknown) => void;
  onWrite = async () => ({ results: { "private-one": { success: true } } });
  onRead = async (url) =>
    url.endsWith("/blocked-history")
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : { whitelist: [] };
  renderPage();
  await selectBatch();
  fireEvent.click(
    screen.getByRole("button", {
      name: new RegExp(text("skills.batchEnable")),
    }),
  );
  await waitFor(() => expect(finish).toBeTypeOf("function"));
  act(() =>
    useAuthStore.setState({
      user: { id: "bob", platform_role: "member" } as never,
    }),
  );
  await act(async () => {
    finish([
      { skill_name: "private-one", action: "warned", findings: scanFindings },
    ]);
    // Let the real static-modal scheduler render any incorrectly accepted late result.
    await new Promise((resolve) => setTimeout(resolve, 50));
  });
  expect(screen.queryByText("Old actor scan finding")).not.toBeInTheDocument();
  expect(
    calls.filter((c) => c.url === "/api/skills/batch-enable"),
  ).toHaveLength(1);
});

it("closes a scan-blocked batch-enable dialog when the actual page changes identity", async () => {
  onWrite = async () => ({
    results: {
      "private-one": {
        success: false,
        reason: "security_scan_failed",
        detail: { type: "security_scan_failed", findings: scanFindings },
      },
    },
  });
  renderPage();
  await selectBatch();
  fireEvent.click(
    screen.getByRole("button", {
      name: new RegExp(text("skills.batchEnable")),
    }),
  );
  await screen.findByText("Old actor scan finding");
  act(() =>
    useAuthStore.setState({
      user: { id: "bob", platform_role: "member" } as never,
    }),
  );
  await waitFor(() =>
    expect(
      screen.queryByText("Old actor scan finding"),
    ).not.toBeInTheDocument(),
  );
});

it.each([
  [403, "forbidden", "skillGovernance.forbidden"],
  [422, "skill_security_scan_failed", "skillGovernance.failed"],
  [503, "skill_authority_unavailable", "skillGovernance.failed"],
])(
  "shows top-bar publication failure %s and retains unsubmitted selection",
  async (status, detail, errorKey) => {
    onWrite = async () =>
      new Response(JSON.stringify({ detail }), {
        status: status as number,
        headers: { "Content-Type": "application/json" },
      });
    renderPage();
    await selectBatch();
    fireEvent.click(
      screen.getByRole("button", {
        name: new RegExp(text("skillGovernance.submit")),
      }),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(
      await screen.findByText(text(errorKey as string)),
    ).toBeInTheDocument();
    expect(
      screen.getByText(i18n.t("skills.selectedCount", { count: 1 })),
    ).toBeInTheDocument();
    expect(
      calls.filter((c) => c.url === "/api/skill-governance/requests"),
    ).toHaveLength(1);
  },
);

it("shows submitted and remaining names after a partial top-bar publication", async () => {
  installed.push(
    { name: "private-two", source: "custom", enabled: true },
    { name: "private-three", source: "custom", enabled: true },
  );
  onWrite = async (_url, body) =>
    (body as { skill_name: string }).skill_name === "private-one"
      ? { id: "submitted-one" }
      : new Response('{"detail":"forbidden"}', {
          status: 403,
          headers: { "Content-Type": "application/json" },
        });
  renderPage();
  await selectBatch();
  fireEvent.click(
    screen.getByRole("button", {
      name: new RegExp(text("skillGovernance.submit")),
    }),
  );
  expect(
    await screen.findByText(text("skillGovernance.forbidden")),
  ).toBeInTheDocument();
  expect(
    screen.getByText(
      i18n.t("skillGovernance.submittedSkills", { names: "private-one" }),
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByText(
      i18n.t("skillGovernance.unsubmittedSkills", {
        names: "private-two, private-three",
      }),
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByText(i18n.t("skills.selectedCount", { count: 2 })),
  ).toBeInTheDocument();
  expect(
    calls
      .filter((c) => c.url === "/api/skill-governance/requests")
      .map((c) => (c.body as { skill_name: string }).skill_name),
  ).toEqual(["private-one", "private-two"]);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  onWrite = async () => ({ id: "retry-success" });
  fireEvent.click(
    screen.getByRole("button", {
      name: new RegExp(text("skillGovernance.submit")),
    }),
  );
  await waitFor(() =>
    expect(
      screen.getByText(i18n.t("skills.selectedCount", { count: 0 })),
    ).toBeInTheDocument(),
  );
  expect(
    calls
      .filter((c) => c.url === "/api/skill-governance/requests")
      .map((c) => (c.body as { skill_name: string }).skill_name),
  ).toEqual(["private-one", "private-two", "private-two", "private-three"]);
});

it("retains top-bar selections while pending and clears them only after publication succeeds", async () => {
  let finish!: (value: unknown) => void;
  onWrite = () =>
    new Promise((resolve) => {
      finish = resolve;
    });
  renderPage();
  await selectBatch();
  fireEvent.click(
    screen.getByRole("button", {
      name: new RegExp(text("skillGovernance.submit")),
    }),
  );
  await waitFor(() => expect(finish).toBeTypeOf("function"));
  expect(
    screen.getByText(i18n.t("skills.selectedCount", { count: 1 })),
  ).toBeInTheDocument();
  await act(async () => finish({ id: "published-request" }));
  expect(
    screen.getByText(i18n.t("skills.selectedCount", { count: 0 })),
  ).toBeInTheDocument();
});

it("does not show a late top-bar publication failure in the next identity", async () => {
  let finish!: (value: unknown) => void;
  onWrite = () =>
    new Promise((resolve) => {
      finish = resolve;
    });
  renderPage();
  await selectBatch();
  fireEvent.click(
    screen.getByRole("button", {
      name: new RegExp(text("skillGovernance.submit")),
    }),
  );
  await waitFor(() => expect(finish).toBeTypeOf("function"));
  act(() =>
    useAuthStore.setState({
      user: { id: "bob", platform_role: "member" } as never,
    }),
  );
  await act(async () =>
    finish(
      new Response('{"detail":"forbidden"}', {
        status: 403,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  expect(
    screen.queryByText(text("skillGovernance.forbidden")),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByText(
      i18n.t("skillGovernance.unsubmittedSkills", { names: "private-one" }),
    ),
  ).not.toBeInTheDocument();
  expect(
    calls.filter((c) => c.url === "/api/skill-governance/requests"),
  ).toHaveLength(1);
});
