import { describe, expect, it } from "vitest";
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
