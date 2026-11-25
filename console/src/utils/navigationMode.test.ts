import { afterEach, describe, expect, it, vi } from "vitest";
import {
  addRouterBasename,
  getAppRelativeLocation,
  getConsoleRootHref,
  getLoginHref,
  getLoginPath,
  getOsPawAppIdFromHistoryState,
  getOsRootHref,
  getPostLoginHref,
  getRouterBasename,
  isLoginPath,
  isOsPath,
  stripRouterBasename,
  withOsPawAppHistoryState,
} from "./navigationMode";

describe("navigationMode", () => {
  it("recognizes OS routes with and without the console basename", () => {
    expect(isOsPath("/")).toBe(false);
    expect(isOsPath("/os/apps/office")).toBe(true);
    expect(isOsPath("/console")).toBe(false);
    expect(isOsPath("/console/os/apps/office?tab=one")).toBe(true);
    expect(isOsPath("/chat")).toBe(false);
    expect(isOsPath("/console/chat")).toBe(false);
  });

  it("normalizes console-prefixed locations", () => {
    expect(getRouterBasename("/console/os")).toBe("/console");
    expect(stripRouterBasename("/console/os")).toBe("/os");
    expect(stripRouterBasename("/console")).toBe("/");
    expect(
      getAppRelativeLocation({
        pathname: "/console/os",
        search: "?space=one",
        hash: "#top",
      }),
    ).toBe("/os?space=one#top");
  });

  it("builds basename-safe login redirects", () => {
    const location = {
      pathname: "/console/os",
      search: "?space=one",
    };
    expect(getLoginPath(location)).toBe("/login?redirect=%2Fos%3Fspace%3Done");
    expect(getLoginHref(location)).toBe(
      "/console/login?redirect=%2Fos%3Fspace%3Done",
    );
    expect(isLoginPath("/console/login")).toBe(true);
  });

  it("canonicalizes OS destinations after login", () => {
    expect(getPostLoginHref("/console/login", "/os/apps/office")).toBe(
      "/console/os",
    );
    expect(getPostLoginHref("/login", "/os/chat")).toBe("/os");
    expect(getPostLoginHref("/login", "/chat")).toBeNull();
  });

  it("builds the single OS browser entry path", () => {
    expect(getOsRootHref("/console/os/apps/office")).toBe("/console/os");
    expect(getOsRootHref("/os/chat")).toBe("/os");
    expect(addRouterBasename("/console/login", "/os")).toBe("/console/os");
  });

  it("stores OS PawApp history without discarding other shell state", () => {
    const appState = withOsPawAppHistoryState({ osApp: "core.apps" }, "office");
    expect(appState).toEqual({ osApp: "core.apps", osPawAppId: "office" });
    expect(getOsPawAppIdFromHistoryState(appState)).toBe("office");

    const rootState = withOsPawAppHistoryState(appState, null);
    expect(rootState).toEqual({ osApp: "core.apps" });
    expect(getOsPawAppIdFromHistoryState(rootState)).toBeUndefined();
  });

  it("builds basename-safe classic console paths", () => {
    expect(getConsoleRootHref("/console/os/apps/office")).toBe("/console/chat");
    expect(getConsoleRootHref("/os")).toBe("/chat");
  });
});

describe("configured console basename", () => {
  let baseElement: HTMLBaseElement | undefined;

  function setDocumentBase(path: string) {
    baseElement = document.createElement("base");
    baseElement.href = `${path}/`;
    document.head.append(baseElement);
  }

  afterEach(() => {
    baseElement?.remove();
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  async function loadNavigation(basename: string | undefined) {
    vi.stubEnv("VITE_CONSOLE_BASENAME", basename);
    vi.resetModules();
    return import("./navigationMode");
  }

  it.each([undefined, "", " "])(
    "preserves the default basename for %j",
    async (basename) => {
      const navigation = await loadNavigation(basename);
      expect(navigation.getRouterBasename("/console/chat")).toBe("/console");
      expect(navigation.getRouterBasename("/chat")).toBeUndefined();
      expect(navigation.getRouterBasename("/console-other")).toBeUndefined();
    },
  );

  it.each(["/qwenpaw", "/qwenpaw/", "qwenpaw", " /qwenpaw// "])(
    "normalizes the configured basename %j",
    async (basename) => {
      const navigation = await loadNavigation(basename);
      expect(navigation.getRouterBasename("/qwenpaw/chat")).toBe("/qwenpaw");
      expect(navigation.stripRouterBasename("/qwenpaw")).toBe("/");
      expect(navigation.stripRouterBasename("/qwenpaw/")).toBe("/");
      expect(navigation.getRouterBasename("/qwenpaw-other")).toBeUndefined();
      expect(navigation.getRouterBasename("/console/chat")).toBeUndefined();
    },
  );

  it("matches a nested basename literally at a path boundary", async () => {
    const navigation = await loadNavigation("/apps/qwenpaw.v2+preview");
    expect(navigation.getRouterBasename("/apps/qwenpaw.v2+preview/chat")).toBe(
      "/apps/qwenpaw.v2+preview",
    );
    expect(
      navigation.getRouterBasename("/apps/qwenpawXv22preview/chat"),
    ).toBeUndefined();
    expect(
      navigation.getRouterBasename("/apps/qwenpaw.v2+preview-other"),
    ).toBeUndefined();
  });

  it("preserves a custom basename in login and shell navigation", async () => {
    const navigation = await loadNavigation("/apps/qwenpaw/");
    const location = {
      pathname: "/apps/qwenpaw/os/apps/office",
      search: "?space=one",
      hash: "#top",
    };
    expect(navigation.isOsPath(location.pathname)).toBe(true);
    expect(navigation.getLoginHref(location)).toBe(
      "/apps/qwenpaw/login?redirect=%2Fos%2Fapps%2Foffice%3Fspace%3Done%23top",
    );
    expect(navigation.isLoginPath("/apps/qwenpaw/login")).toBe(true);
    expect(
      navigation.getPostLoginHref("/apps/qwenpaw/login", "/os/apps/office"),
    ).toBe("/apps/qwenpaw/os");
    expect(navigation.getConsoleRootHref(location.pathname)).toBe(
      "/apps/qwenpaw/chat",
    );
  });

  it("supports an explicit root basename without duplicate slashes", async () => {
    const navigation = await loadNavigation("/");
    expect(navigation.getRouterBasename("/console/chat")).toBeUndefined();
    expect(navigation.stripRouterBasename("/os")).toBe("/os");
    expect(navigation.getLoginHref({ pathname: "/chat" })).toBe(
      "/login?redirect=%2Fchat",
    );
    expect(navigation.getOsRootHref("/login")).toBe("/os");
  });

  it.each(["/控制台", "/my console"])(
    "keeps browser navigation inside %s",
    async (base) => {
      setDocumentBase(base);
      const navigation = await loadNavigation(undefined);
      const pathname = new URL(`${base}/login`, "https://example.org").pathname;
      expect(navigation.stripRouterBasename(pathname)).toBe("/login");
      expect(navigation.addRouterBasename(pathname, "/chat")).toBe(
        pathname.replace(/login$/, "chat"),
      );
    },
  );

  it.each([
    ["/O'Reilly", "/O%27Reilly"],
    ["/中文", "/%e4%b8%ad%e6%96%87"],
    ["/apps/data+preview", "/%61pps/data%2Bpreview"],
  ])("matches an equivalent encoding of %s", async (base, spelling) => {
    setDocumentBase(base);
    const navigation = await loadNavigation(undefined);
    const pathname = `${spelling}/chat/%2Fother`;
    expect(navigation.getRouterBasename(pathname)).toBe(spelling);
    expect(navigation.stripRouterBasename(spelling)).toBe("/");
    expect(navigation.stripRouterBasename(pathname)).toBe("/chat/%2Fother");
    expect(navigation.getLoginHref({ pathname })).toBe(
      `${spelling}/login?redirect=%2Fchat%2F%252Fother`,
    );
    expect(
      navigation.getRouterBasename(`${spelling}-other/chat`),
    ).toBeUndefined();
    expect(navigation.getRouterBasename(`${spelling}%2Fchat`)).toBeUndefined();
    expect(navigation.getRouterBasename(`${spelling}%/chat`)).toBeUndefined();
  });

  it("prefers the server-injected runtime base path", async () => {
    setDocumentBase("/app/qwenpaw/web");
    const navigation = await loadNavigation(undefined);
    const location = {
      pathname: "/app/qwenpaw/web/chat",
      search: "?draft=one",
    };
    expect(navigation.getRouterBasename(location.pathname)).toBe(
      "/app/qwenpaw/web",
    );
    expect(navigation.stripRouterBasename(location.pathname)).toBe("/chat");
    expect(navigation.getLoginHref(location)).toBe(
      "/app/qwenpaw/web/login?redirect=%2Fchat%3Fdraft%3Done",
    );
  });
});
