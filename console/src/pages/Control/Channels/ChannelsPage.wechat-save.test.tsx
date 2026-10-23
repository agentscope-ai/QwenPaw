import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { FormInstance } from "antd";
import { useAgentStore } from "../../../stores/agentStore";
import ChannelsPage from "./index";

const feedback = vi.hoisted(() => ({
  message: {
    destroy: vi.fn(),
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  },
  modal: { confirm: vi.fn() },
  form: undefined as FormInstance | undefined,
}));
vi.mock("@agentscope-ai/design", async () => {
  const actual = await vi.importActual<typeof import("antd")>("antd");
  const original = actual.Form.useForm;
  vi.spyOn(actual.Form, "useForm").mockImplementation((instance) => {
    const pair = original(instance);
    feedback.form = pair[0];
    return pair;
  });
  return actual;
});
vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => feedback,
}));
vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));
vi.mock("../../../contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: false }),
}));
vi.mock("@/components/interaction/Cascade", () => ({
  Cascade: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("@/components/PageHeader", () => ({ PageHeader: () => null }));
// Presentation boundaries only: the real Drawer, data hook and every save/QR
// implementation remain production imports, including actual antd Form.
vi.mock("./components", async () => ({
  ChannelDrawer: (await import("./components/ChannelDrawer")).ChannelDrawer,
  useChannels: (await import("./useChannels")).useChannels,
  getChannelLabel: (key: string) => key,
  ChannelCard: ({
    channelKey,
    onClick,
  }: {
    channelKey: string;
    onClick: () => void;
  }) => <button onClick={onClick}>open-{channelKey}</button>,
  ChannelAvailableItem: ({
    channelKey,
    onClick,
  }: {
    channelKey: string;
    onClick: () => void;
  }) => <button onClick={onClick}>open-{channelKey}</button>,
  AccessControlDrawer: () => null,
  PendingApprovalsDrawer: () => null,
}));

type Row = {
  agent: string | null;
  auth: string | null;
  body: Record<string, unknown>;
};
const writes: Row[] = [];
const conflicts: Row[] = [];
const cancellations: {
  agent: string | null;
  channel: string;
  token: string | null;
}[] = [];
let enabled = false;
let channel = "wechat";
let extraConfig: Record<string, unknown> = {};
let onPut: (row: Row, signal?: AbortSignal | null) => Promise<Response>;
let onConflict: (row: Row) => Promise<Response>;

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
async function settle() {
  await act(async () => {});
}
async function tick(ms = 1000) {
  await act(async () => vi.advanceTimersByTimeAsync(ms));
}

beforeEach(() => {
  vi.useFakeTimers();
  writes.length = conflicts.length = 0;
  cancellations.length = 0;
  enabled = false;
  channel = "wechat";
  extraConfig = {};
  feedback.form = undefined;
  Object.values(feedback.message).forEach((mock) => mock.mockClear());
  feedback.modal.confirm.mockClear();
  useAgentStore.setState({ selectedAgent: "A", agents: [] });
  onPut = async (row) => json(row.body);
  onConflict = async () => json({ conflict: false, agents: [] });
  vi.stubGlobal(
    "fetch",
    async (input: string | URL | Request, init: RequestInit = {}) => {
      const path = new URL(String(input), "https://console.test").pathname;
      const headers = new Headers(init.headers);
      const row = {
        agent: headers.get("X-Agent-Id"),
        auth: headers.get("X-Channel-Auth-Session"),
        body: init.body ? JSON.parse(String(init.body)) : {},
      };
      if (init.method === "PUT") {
        writes.push(row);
        return onPut(row, init.signal);
      }
      if (init.method === "DELETE") {
        cancellations.push({
          agent: row.agent,
          channel: path.split("/").slice(-2)[0],
          token: new URL(
            String(input),
            "https://console.test",
          ).searchParams.get("token"),
        });
        return new Response(null, { status: 204 });
      }
      if (path.endsWith("/conflict-check")) {
        conflicts.push(row);
        return onConflict(row);
      }
      if (path.endsWith("/qrcode/status"))
        return json({
          status: "confirmed",
          credentials: {
            bot_token: "confirmed-" + row.agent,
            base_url: "https://wx.test",
          },
        });
      if (path.endsWith("/qrcode"))
        return json({ qrcode_img: "cXI=", poll_token: "opaque-" + row.agent });
      if (path.endsWith("/channels"))
        return json({
          [channel]: {
            isBuiltin: true,
            enabled,
            bot_token: "initial-" + row.agent,
            bot_prefix: "",
            base_url: "https://wx.test",
            ...extraConfig,
          },
        });
      if (path.endsWith("/types")) return json([channel]);
      if (path.endsWith("/schemas"))
        return json({
          [channel]: {
            label: channel,
            description: "",
            plugin_id: channel,
            config_fields: [],
            availability: "validated",
          },
        }); // Existing API schema without the optional qrcode_available field.
      return json([]); // unrelated ACL badge display
    },
  );
});
afterEach(async () => {
  cleanup();
  await settle();
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  sessionStorage.clear();
  localStorage.clear();
});
async function openPage() {
  const view = render(<ChannelsPage />);
  await settle();
  fireEvent.click(screen.getByText("open-" + channel));
  await settle();
  return view;
}
async function qrSuccess(agent = "A") {
  fireEvent.click(screen.getByText("channels.wechatGetQrcode"));
  await settle();
  await tick(2000);
  expect(
    (
      screen.getByPlaceholderText(
        "channels.wechatBotTokenPlaceholder",
      ) as HTMLInputElement
    ).value,
  ).toBe("confirmed-" + agent);
}
function editToken(value: string) {
  fireEvent.change(
    screen.getByPlaceholderText("channels.wechatBotTokenPlaceholder"),
    { target: { value } },
  );
}
function editMedia(value: string) {
  fireEvent.change(screen.getByPlaceholderText("~/.qwenpaw/media"), {
    target: { value },
  });
}

it("sends a validated A job after its real conflict check completes while B is selected", async () => {
  enabled = true;
  const held = deferred<Response>();
  onConflict = () => held.promise;
  await openPage();
  editToken("validated-A");
  await tick();
  expect(conflicts).toHaveLength(1); // actual Form validation passed before POST
  expect(conflicts[0].agent).toBe("A");
  act(() => useAgentStore.setState({ selectedAgent: "B" }));
  await settle();
  await act(async () => held.resolve(json({ conflict: false, agents: [] })));
  expect(writes).toHaveLength(1);
  expect(writes[0].agent).toBe("A");
  expect(writes[0].body.bot_token).toBe("validated-A");
  expect(useAgentStore.getState().selectedAgent).toBe("B");
  fireEvent.click(screen.getByText("open-wechat"));
  await settle();
  expect(
    (
      screen.getByPlaceholderText(
        "channels.wechatBotTokenPlaceholder",
      ) as HTMLInputElement
    ).value,
  ).toBe("initial-B");
});

it("validates an A edit before debounce so a queued immutable job survives switching to B", async () => {
  await openPage();
  const validation = vi.spyOn(feedback.form!, "validateFields");
  editToken("queued-A");
  await settle();
  expect(writes).toHaveLength(0);
  // No fake result: inspect the actual antd validation invocation/completion.
  expect(validation).toHaveBeenCalledTimes(1);
  await validation.mock.results[0].value;
  act(() => useAgentStore.setState({ selectedAgent: "B" }));
  await settle();
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({
    agent: "A",
    body: { bot_token: "queued-A" },
  });
});

it("discards a validation still pending when A switches to B", async () => {
  await openPage();
  const validation = vi.spyOn(feedback.form!, "validateFields");
  editToken("pending-A");
  act(() => {
    // Synchronous timer advancement starts actual async Form validation, but
    // deliberately does not drain its promise before the store transition.
    vi.advanceTimersByTime(1000);
    expect(validation).toHaveBeenCalledTimes(1);
    useAgentStore.setState({ selectedAgent: "B" });
  });
  await settle();
  expect(writes).toHaveLength(0);
  expect(conflicts).toHaveLength(0);
  expect(useAgentStore.getState().selectedAgent).toBe("B");
});

it("discards pending validation across a batched ABA scope transition", async () => {
  await openPage();
  const validation = vi.spyOn(feedback.form!, "validateFields");
  editToken("obsolete-pre-ABA");
  act(() => {
    vi.advanceTimersByTime(1000);
    expect(validation).toHaveBeenCalledTimes(1);
    useAgentStore.setState({ selectedAgent: "B" });
    useAgentStore.setState({ selectedAgent: "A" });
  });
  await settle();
  expect(writes).toHaveLength(0);
  expect(useAgentStore.getState().selectedAgent).toBe("A");
});

it.each(["success", "http-failure", "network-unknown"])(
  "derives a queued noncredential job only after explicit PUT success: %s",
  async (outcome) => {
    const held = deferred<Response>();
    onPut = () =>
      writes.length === 1 ? held.promise : Promise.resolve(json({}));
    await openPage();
    await qrSuccess();
    await tick();
    expect(writes).toHaveLength(1);
    expect(writes[0].auth).toBe("opaque-A");
    editMedia("/A/new-media");
    await tick();
    expect(writes).toHaveLength(1); // serialized behind the first write
    if (outcome === "network-unknown") {
      // A received non-2xx is a definite HTTP failure. A rejected body read
      // simulates an unknown transport result after dispatch, without a retry.
      const response = json({});
      vi.spyOn(response, "json").mockRejectedValueOnce(
        new TypeError("connection lost"),
      );
      await act(async () => held.resolve(response));
    } else {
      await act(async () =>
        held.resolve(json({}, outcome === "success" ? 200 : 503)),
      );
    }
    await settle();
    expect(writes).toHaveLength(2);
    expect(writes[1]).toMatchObject({
      agent: "A",
      body: { bot_token: "confirmed-A", media_dir: "/A/new-media" },
    });
    expect(writes[1].auth).toBe(outcome === "success" ? null : "opaque-A");
    expect(writes[0].auth).toBe("opaque-A"); // original snapshot unchanged
  },
);

it.each(["token", "path"])(
  "manual %s edits clear QR provenance",
  async (field) => {
    await openPage();
    await qrSuccess();
    if (field === "token") editToken("manual-A");
    else
      fireEvent.change(
        screen.getByPlaceholderText("~/.qwenpaw/wechat_bot_token"),
        { target: { value: "/A/manual-token" } },
      );
    await tick();
    expect(writes).toHaveLength(1);
    expect(writes[0].auth).toBe(null);
    expect(writes[0].agent).toBe("A");
    expect(
      writes[0].body[field === "token" ? "bot_token" : "bot_token_file"],
    ).toBe(field === "token" ? "manual-A" : "/A/manual-token");
  },
);

it("unmount flushes the actual Page authorization closure and original body", async () => {
  const page = await openPage();
  await qrSuccess();
  page.unmount();
  await settle();
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({
    agent: "A",
    auth: "opaque-A",
    body: { bot_token: "confirmed-A", base_url: "https://wx.test" },
  });
  expect(cancellations).toEqual([]);
});

it("the real request timeout cannot strip provenance from the queued automatic edit", async () => {
  onPut = (_row, signal) =>
    writes.length === 1
      ? new Promise((_resolve, reject) =>
          signal!.addEventListener(
            "abort",
            () => reject(new DOMException("network abort", "AbortError")),
            { once: true },
          ),
        )
      : Promise.resolve(json({}));
  await openPage();
  await qrSuccess();
  await tick();
  expect(writes).toHaveLength(1);
  editMedia("/A/after-timeout");
  await tick();
  expect(writes).toHaveLength(1);
  await tick(29000); // production request's actual default 30s, virtual clock
  expect(writes).toHaveLength(2);
  expect(writes[1]).toMatchObject({
    agent: "A",
    auth: "opaque-A",
    body: { media_dir: "/A/after-timeout", bot_token: "confirmed-A" },
  });
});

it("retry retains the actual failed Page job's original authorization header and body", async () => {
  onPut = async () =>
    writes.length === 1 ? json({ detail: "offline" }, 503) : json({});
  await openPage();
  await qrSuccess();
  await tick();
  expect(writes).toHaveLength(1);
  expect(feedback.message.error).toHaveBeenCalledTimes(1);
  const original = structuredClone(writes[0]);
  // Display the production toast's actual retry action, without replacing its
  // captured save callback. Request defaults changing must not retarget it.
  sessionStorage.setItem(
    "qwenpaw-agent-storage",
    JSON.stringify({ state: { selectedAgent: "B" } }),
  );
  render(feedback.message.error.mock.calls[0][0].content);
  fireEvent.click(screen.getByText("common.retry"));
  await settle();
  expect(writes).toHaveLength(2);
  expect(writes[1]).toEqual(original);
});

it("a newer edit supersedes only validation still in flight, then saves the newer body", async () => {
  await openPage();
  editToken("obsolete-A");
  act(() => {
    vi.advanceTimersByTime(1000);
    editToken("newer-A");
  });
  await settle();
  expect(writes).toHaveLength(0);
  await tick();
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({
    agent: "A",
    auth: null,
    body: { bot_token: "newer-A" },
  });
});

it("an A commit cannot make B's queued failed authorization job ordinary", async () => {
  await openPage();
  await qrSuccess();
  await tick();
  expect(writes[0].auth).toBe("opaque-A");
  act(() => useAgentStore.setState({ selectedAgent: "B" }));
  await settle();
  fireEvent.click(screen.getByText("open-wechat"));
  await settle();
  await qrSuccess("B");
  const held = deferred<Response>();
  onPut = () =>
    writes.length === 2 ? held.promise : Promise.resolve(json({}));
  await tick();
  expect(writes[1]).toMatchObject({ agent: "B", auth: "opaque-B" });
  editMedia("/B/new-media");
  await tick();
  await act(async () => held.resolve(json({}, 503)));
  expect(writes).toHaveLength(3);
  expect(writes[2]).toMatchObject({
    agent: "B",
    auth: "opaque-B",
    body: { bot_token: "confirmed-B", media_dir: "/B/new-media" },
  });
});

it("Matrix password edits retain normalization through actual Drawer and Page PUT", async () => {
  channel = "matrix";
  extraConfig = {
    homeserver: "https://matrix.test",
    user_id: "@A:matrix.test",
    password: "initial-password",
    access_token: "stale-access",
  };
  await openPage();
  const validation = vi.spyOn(feedback.form!, "validateFields");
  fireEvent.change(screen.getByPlaceholderText("channels.fieldPassword"), {
    target: { value: "updated-password" },
  });
  await tick();
  const observedValidation = await Promise.allSettled(
    validation.mock.results.map(({ value }) => value),
  );
  console.info(
    "Matrix actual Form validation observation",
    JSON.stringify({
      observedValidation,
      values: feedback.form!.getFieldsValue(true),
    }),
  );
  expect(writes).toHaveLength(1);
  expect(writes[0].body).toMatchObject({
    password: "updated-password",
    access_token: "",
  });
  expect(writes[0].body).not.toHaveProperty("auth_method");
});

it("Console edits retain the enabled invariant through actual Drawer and Page PUT", async () => {
  channel = "console";
  await openPage();
  fireEvent.change(screen.getByPlaceholderText("@bot"), {
    target: { value: "prefix" },
  });
  await tick();
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({
    agent: "A",
    auth: null,
    body: { enabled: true, bot_prefix: "prefix" },
  });
});

it.each(["success", "http-failure", "network-unknown"])(
  "a validated queued A job uses only its own shared receipt after switching UI to B: %s",
  async (outcome) => {
    const held = deferred<Response>();
    onPut = () =>
      writes.length === 1 ? held.promise : Promise.resolve(json({}));
    await openPage();
    await qrSuccess();
    await tick();
    expect(writes).toHaveLength(1);
    const original = structuredClone(writes[0]);
    const validation = vi.spyOn(feedback.form!, "validateFields");
    editMedia("/A/validated-queued");
    await settle();
    expect(validation).toHaveBeenCalledTimes(1);
    await validation.mock.results[0].value;
    await tick(); // second immutable A job now waits behind the in-flight PUT
    expect(writes).toHaveLength(1);
    act(() => useAgentStore.setState({ selectedAgent: "B" }));
    await settle();
    const response = json({}, outcome === "http-failure" ? 503 : 200);
    if (outcome === "network-unknown") {
      vi.spyOn(response, "json").mockRejectedValueOnce(
        new TypeError("connection lost"),
      );
    }
    await act(async () => held.resolve(response));
    expect(writes).toHaveLength(2);
    expect(writes[1]).toMatchObject({
      agent: "A",
      auth: outcome === "success" ? null : "opaque-A",
      body: { bot_token: "confirmed-A", media_dir: "/A/validated-queued" },
    });
    expect(writes[0]).toEqual(original);
    expect(useAgentStore.getState().selectedAgent).toBe("B");
    fireEvent.click(screen.getByText("open-wechat"));
    await settle();
    expect(
      (
        screen.getByPlaceholderText(
          "channels.wechatBotTokenPlaceholder",
        ) as HTMLInputElement
      ).value,
    ).toBe("initial-B");
    expect(cancellations).toEqual([]);
  },
);

it("an unmounted failed A job keeps its actual retry action after the store selects B", async () => {
  const second = deferred<Response>();
  onPut = () =>
    writes.length === 1
      ? Promise.resolve(json({}, 503))
      : writes.length === 2
      ? second.promise
      : Promise.resolve(json({}));
  const page = await openPage();
  await qrSuccess();
  await tick();
  expect(writes).toHaveLength(1);
  const original = structuredClone(writes[0]);
  expect(feedback.message.error).toHaveBeenCalledTimes(1);
  page.unmount(); // actual autosave cleanup flushes the retained failed task
  act(() => useAgentStore.setState({ selectedAgent: "B" }));
  await settle();
  expect(writes).toHaveLength(2);
  expect(writes[1]).toEqual(original);
  await act(async () => second.resolve(json({}, 503)));
  expect(feedback.message.error).toHaveBeenCalledTimes(2);
  render(feedback.message.error.mock.calls[1][0].content);
  fireEvent.click(screen.getByText("common.retry"));
  await settle();
  expect(writes).toHaveLength(3);
  expect(writes[2]).toEqual(original);
  expect(useAgentStore.getState().selectedAgent).toBe("B");
  expect(cancellations).toEqual([]);
});

it("retired scope receipts cannot authorize a new batch even with the same A token and credentials", async () => {
  await openPage();
  await qrSuccess();
  await tick();
  for (const agent of ["B", "A"]) {
    act(() => useAgentStore.setState({ selectedAgent: agent }));
    await settle();
    fireEvent.click(screen.getByText("open-wechat"));
    await settle();
    await qrSuccess(agent);
    await tick();
  }
  expect(writes.map(({ agent, auth }) => [agent, auth])).toEqual([
    ["A", "opaque-A"],
    ["B", "opaque-B"],
    ["A", "opaque-A"],
  ]);
});

async function openValidMatrix() {
  channel = "matrix";
  extraConfig = {
    homeserver: "https://matrix.test",
    user_id: "@A:matrix.test",
    password: "initial-password",
    access_token: "stale-access",
  };
  return openPage();
}

it("native outOfDate cannot revalidate or save an old scope snapshot", async () => {
  await openValidMatrix();
  const validation = vi.spyOn(feedback.form!, "validateFields");
  fireEvent.change(screen.getByPlaceholderText("channels.fieldPassword"), {
    target: { value: "obsolete-A" },
  });
  act(() => useAgentStore.setState({ selectedAgent: "B" }));
  await settle();
  const observed = await Promise.allSettled(
    validation.mock.results.map(({ value }) => value),
  );
  expect(observed[0]).toMatchObject({
    status: "rejected",
    reason: { outOfDate: true, errorFields: [] },
  });
  expect(validation).toHaveBeenCalledTimes(1);
  await tick();
  expect(writes).toHaveLength(0);
});

it("native outOfDate preserves a newer real edit and never saves its obsolete revision", async () => {
  await openValidMatrix();
  const validation = vi.spyOn(feedback.form!, "validateFields");
  const input = screen.getByPlaceholderText("channels.fieldPassword");
  fireEvent.change(input, { target: { value: "obsolete-revision" } });
  fireEvent.change(input, { target: { value: "newer-revision" } });
  await settle();
  const observed = await Promise.allSettled(
    validation.mock.results.map(({ value }) => value),
  );
  expect(observed.slice(0, 2)).toMatchObject([
    { status: "rejected", reason: { outOfDate: true, errorFields: [] } },
    { status: "rejected", reason: { outOfDate: true, errorFields: [] } },
  ]);
  expect(validation).toHaveBeenCalledTimes(3); // only current revision gets one retry
  expect(observed[2].status).toBe("fulfilled");
  await tick();
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({
    agent: "A",
    body: { password: "newer-revision", access_token: "" },
  });
});

it("native outOfDate cannot rescue changed full Form values without a revision event", async () => {
  await openValidMatrix();
  const validation = vi.spyOn(feedback.form!, "validateFields");
  fireEvent.change(screen.getByPlaceholderText("channels.fieldPassword"), {
    target: { value: "obsolete-values" },
  });
  // Real Form programmatic updates do not emit onValuesChange. This isolates
  // the full-values fence from the separate revision/epoch fences.
  act(() => feedback.form!.setFieldsValue({ password: "programmatic-newer" }));
  await settle();
  const observed = await Promise.allSettled(
    validation.mock.results.map(({ value }) => value),
  );
  expect(observed[0]).toMatchObject({
    status: "rejected",
    reason: { outOfDate: true, errorFields: [] },
  });
  expect(validation).toHaveBeenCalledTimes(1);
  await tick();
  expect(writes).toHaveLength(0);
});

it("native invalid required fields are never rescued by the outOfDate retry", async () => {
  await openValidMatrix();
  const validation = vi.spyOn(feedback.form!, "validateFields");
  fireEvent.change(screen.getByPlaceholderText("channels.fieldPassword"), {
    target: { value: "" },
  });
  await settle();
  const observed = await Promise.allSettled(
    validation.mock.results.map(({ value }) => value),
  );
  expect(observed[0]).toMatchObject({
    status: "rejected",
    reason: {
      errorFields: [{ name: ["password"], errors: [expect.any(String)] }],
    },
  });
  expect(validation).toHaveBeenCalledTimes(1);
  await tick();
  expect(writes).toHaveLength(0);
});

it("UNIT controlled second outOfDate rejects after two actual validations without a third attempt", async () => {
  await openValidMatrix();
  const original = feedback.form!.validateFields.bind(feedback.form!);
  const secondFailure = { outOfDate: true, errorFields: [] };
  let invocation = 0;
  let secondNativeSucceeded = false;
  // One explicit unit fault layer: both validations execute the real Form;
  // only the second actual success is converted to a synthetic outOfDate.
  const validation = vi
    .spyOn(feedback.form!, "validateFields")
    .mockImplementation(async (...args) => {
      const sequence = ++invocation;
      const result = await original(...args);
      if (sequence === 2) {
        secondNativeSucceeded = true;
        throw secondFailure;
      }
      return result;
    });
  fireEvent.change(screen.getByPlaceholderText("channels.fieldPassword"), {
    target: { value: "valid-second-attempt" },
  });
  await settle();
  const observed = await Promise.allSettled(
    validation.mock.results.map(({ value }) => value),
  );
  expect(observed[0]).toMatchObject({
    status: "rejected",
    reason: { outOfDate: true, errorFields: [] },
  });
  expect(observed[1]).toMatchObject({
    status: "rejected",
    reason: secondFailure,
  });
  expect(secondNativeSucceeded).toBe(true);
  expect(validation).toHaveBeenCalledTimes(2);
  await tick();
  expect(validation).toHaveBeenCalledTimes(2);
  expect(writes).toHaveLength(0);
});

it.each(["switch", "unmount"])(
  "a confirmed QR session remains cancellable while actual validation custody is pending: %s",
  async (navigation) => {
    const page = await openPage();
    const original = feedback.form!.validateFields.bind(feedback.form!);
    const validationReturn = deferred<void>();
    let nativeValidationSucceeded = false;
    // A scheduling gate around the actual result, never a fabricated success:
    // the real Form runs first, but prepareSave has not received its return.
    const validation = vi
      .spyOn(feedback.form!, "validateFields")
      .mockImplementation(async (...args) => {
        const result = await original(...args);
        nativeValidationSucceeded = true;
        await validationReturn.promise;
        return result;
      });
    await qrSuccess(); // real QrcodeAuthBlock/hook/poll/onSuccess -> Drawer
    expect(nativeValidationSucceeded).toBe(true);
    expect(validation).toHaveBeenCalledTimes(1);
    expect(writes).toHaveLength(0);
    expect(cancellations).toHaveLength(0);
    if (navigation === "switch")
      act(() => useAgentStore.setState({ selectedAgent: "B" }));
    else page.unmount();
    await settle();
    await act(async () => validationReturn.resolve());
    await tick();
    expect(writes).toHaveLength(0);
    expect(cancellations).toEqual([
      { agent: "A", channel: "wechat", token: "opaque-A" },
    ]);
  },
);

it("validated custody is already queued when the next validation-result microtask switches to B", async () => {
  await openPage();
  const original = feedback.form!.validateFields.bind(feedback.form!);
  const gate = deferred<void>();
  const validation = vi
    .spyOn(feedback.form!, "validateFields")
    .mockImplementation(async (...args) => {
      const result = await original(...args);
      await gate.promise;
      return result;
    });
  await qrSuccess();
  expect(validation).toHaveBeenCalledTimes(1);
  // prepareSave already awaits this actual result. Our later registered
  // reaction runs after that continuation, before a later prepareSave.then
  // could enqueue a job. Taking custody must enqueue synchronously first.
  const switchAfterValidation = validation.mock.results[0].value.then(() => {
    useAgentStore.setState({ selectedAgent: "B" });
  });
  await act(async () => {
    gate.resolve();
    await switchAfterValidation;
  });
  await settle();
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({
    agent: "A",
    auth: "opaque-A",
    body: { bot_token: "confirmed-A", base_url: "https://wx.test" },
  });
  expect(cancellations).toEqual([]);
});

it("resetting a real confirmed flight prevents its still-valid pending Form result from queuing", async () => {
  const baseFetch = globalThis.fetch;
  let fetched = 0;
  vi.stubGlobal(
    "fetch",
    async (input: string | URL | Request, init: RequestInit = {}) => {
      const url = new URL(String(input), "https://console.test");
      if (
        url.pathname.endsWith("/qrcode") &&
        (init.method || "GET") === "GET"
      ) {
        return json({
          qrcode_img: "cXI=",
          poll_token: ++fetched === 1 ? "old-A" : "new-A",
        });
      }
      return baseFetch(input, init);
    },
  );
  await openPage();
  const original = feedback.form!.validateFields.bind(feedback.form!);
  const gate = deferred<void>();
  let nativeValidated = false;
  vi.spyOn(feedback.form!, "validateFields").mockImplementation(
    async (...args) => {
      const result = await original(...args);
      nativeValidated = true;
      await gate.promise;
      return result;
    },
  );
  await qrSuccess();
  expect(nativeValidated).toBe(true);
  fireEvent.click(screen.getByText("channels.wechatGetQrcode")); // real reset + new fetch
  await settle();
  expect(fetched).toBe(2);
  expect(cancellations).toEqual([
    { agent: "A", channel: "wechat", token: "old-A" },
  ]);
  await act(async () => gate.resolve());
  await tick(); // original scope/revision/values still match; old take must fail
  expect(writes).toHaveLength(0);
  expect(cancellations).toEqual([
    { agent: "A", channel: "wechat", token: "old-A" },
  ]);
});

it.each(["correct", "leave"])(
  "native invalid QR remains owned for correction or cancellation: %s",
  async (action) => {
    extraConfig = { message_merge_enabled: true, message_merge_delay_ms: -1 };
    await openPage();
    const validation = vi.spyOn(feedback.form!, "validateFields");
    await qrSuccess();
    const first = await Promise.allSettled(
      validation.mock.results.map(({ value }) => value),
    );
    expect(first[0]).toMatchObject({
      status: "rejected",
      reason: {
        errorFields: [
          { name: ["message_merge_delay_ms"], errors: [expect.any(String)] },
        ],
      },
    });
    expect(writes).toHaveLength(0);
    expect(cancellations).toEqual([]);
    if (action === "correct") {
      fireEvent.change(
        screen.getByLabelText("channels.wechatMessageMergeDelayMs"),
        { target: { value: "0" } },
      );
      await tick();
      expect(writes).toHaveLength(1);
      expect(writes[0]).toMatchObject({
        agent: "A",
        auth: "opaque-A",
        body: { bot_token: "confirmed-A", message_merge_delay_ms: 0 },
      });
      expect(cancellations).toEqual([]);
    } else {
      act(() => useAgentStore.setState({ selectedAgent: "B" }));
      await settle();
      expect(writes).toHaveLength(0);
      expect(cancellations).toEqual([
        { agent: "A", channel: "wechat", token: "opaque-A" },
      ]);
    }
  },
);
