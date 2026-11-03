import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

const mocks = vi.hoisted(() => ({
  sessionApi: {
    lastActiveChatId: "chat-1",
    getSessionIdentity: vi.fn((id: string) => ({ sessionId: id })),
  },
  hostFetch: vi.fn(),
}));

vi.mock("../../pages/Chat/sessionApi", () => ({ default: mocks.sessionApi }));
vi.mock("../hostSdk/fetch", () => ({ hostFetch: mocks.hostFetch }));

const deployments = [
  { name: "root", basename: "/", prefix: "" },
  { name: "default console", basename: undefined, prefix: "/console" },
  { name: "custom prefix", basename: "/qwenpaw", prefix: "/qwenpaw" },
  {
    name: "nested prefix",
    basename: "/apps/qwenpaw",
    prefix: "/apps/qwenpaw",
  },
  { name: "apps prefix", basename: "/apps", prefix: "/apps" },
  { name: "chat prefix", basename: "/chat", prefix: "/chat" },
];

describe.each(deployments)(
  "PawApp sessions under $name",
  ({ basename, prefix }) => {
    let hooks: typeof import("../hostSdk/hooks");
    let context: typeof import("./context");
    let host: typeof import("./host");

    beforeAll(async () => {
      vi.stubEnv("VITE_CONSOLE_BASENAME", basename);
      vi.resetModules();
      hooks = await import("../hostSdk/hooks");
      context = await import("./context");
      host = await import("./host");
    });

    afterAll(() => {
      vi.unstubAllEnvs();
      vi.resetModules();
    });

    beforeEach(() => {
      window.history.replaceState({}, "", `${prefix}/apps/office`);
      context.setActivePawAppId("office");
      mocks.sessionApi.lastActiveChatId = "chat-1";
      mocks.sessionApi.getSessionIdentity
        .mockReset()
        .mockImplementation((id) => ({
          sessionId: id === "chat-1" ? "pawapp:office:dialogue:1" : "",
        }));
      mocks.hostFetch.mockReset().mockImplementation(
        async () =>
          new Response(JSON.stringify({ text: "reply" }), {
            headers: { "content-type": "application/json" },
          }),
      );
      vi.stubGlobal("QwenPaw", {
        host: {
          getSelectedAgentId: () => "default",
          getCurrentSessionId: hooks.getCurrentSessionId,
        },
      });
    });

    afterEach(() => {
      context.setActivePawAppId(null);
      vi.unstubAllGlobals();
      window.history.replaceState({}, "", "/");
    });

    describe.each(["legacy", "scoped"])("%s host.chat()", (sdk) => {
      function currentHost() {
        return sdk === "legacy"
          ? host.hostNamespace
          : host.createHostNamespace(() => "office");
      }

      it("preserves the current dialogue in the request body", async () => {
        await currentHost().chat("continue the dialogue");

        expect(mocks.hostFetch).toHaveBeenCalledExactlyOnceWith(
          "/office/chat?agent_id=default",
          expect.objectContaining({
            method: "POST",
            body: JSON.stringify({
              message: "continue the dialogue",
              session_id: "pawapp:office:dialogue:1",
            }),
          }),
        );
      });

      it("respects an explicit session instead of the active dialogue", async () => {
        await currentHost().chat("continue another dialogue", {
          sessionId: "pawapp:office:dialogue:2",
        });

        expect(mocks.hostFetch).toHaveBeenCalledExactlyOnceWith(
          "/office/chat?agent_id=default",
          expect.objectContaining({
            method: "POST",
            body: JSON.stringify({
              message: "continue another dialogue",
              session_id: "pawapp:office:dialogue:2",
            }),
          }),
        );
      });
    });

    it.each([
      "pawapp:other:dialogue:1",
      "pawapp:office-other:dialogue:1",
      "ordinary-host-session",
    ])("does not inherit an unrelated session %s", (sessionId) => {
      mocks.sessionApi.getSessionIdentity.mockReturnValue({ sessionId });

      expect(hooks.getCurrentSessionId()).toBeNull();
    });

    it("resolves a normal chat route to its backend session", () => {
      window.history.replaceState({}, "", `${prefix}/chat/chat-2`);
      mocks.sessionApi.getSessionIdentity.mockImplementation((id) => ({
        sessionId: id === "chat-2" ? "backend-session-2" : "",
      }));

      expect(hooks.getCurrentSessionId()).toBe("backend-session-2");
    });

    it("infers the active PawApp from the browser path", () => {
      context.setActivePawAppId(null);

      expect(context.getActivePawAppId()).toBe("office");
    });
  },
);
