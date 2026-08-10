import { describe, expect, it } from "vitest";
import {
  baseFromRoutePath,
  isModeWindowTransition,
  pathToRouteId,
} from "./osRouteMap";

const routes = [
  { id: "core.chat", path: "/chat/*", source: "core" },
  { id: "core.app-center", path: "/apps", source: "core" },
  {
    id: "core.app-center.embed",
    path: "/apps/:appId",
    source: "core",
  },
  { id: "plugin.office", path: "/apps/office", source: "office" },
  {
    id: "plugin.office.settings",
    path: "/apps/office/settings",
    source: "office",
  },
  { id: "plugin.review", path: "/apps/review", source: "review" },
];

describe("osRouteMap", () => {
  it("removes splats and parameters from window bases", () => {
    expect(baseFromRoutePath("/chat/*")).toBe("/chat");
    expect(baseFromRoutePath("/apps/:appId")).toBe("/apps");
  });

  it("routes dynamic children to their owning app", () => {
    expect(pathToRouteId("/chat/session-1", routes)).toBe("core.chat");
  });

  it("treats Chat and Coding navigation as a window replacement", () => {
    expect(isModeWindowTransition("core.chat", "core.coding")).toBe(true);
    expect(isModeWindowTransition("core.coding", "core.chat")).toBe(true);
    expect(isModeWindowTransition("core.chat", "core.inbox")).toBe(false);
  });

  it("prefers a concrete PawApp over the aggregate apps route", () => {
    expect(pathToRouteId("/apps/office", routes)).toBe("plugin.office");
    expect(pathToRouteId("/apps/review", routes)).toBe("plugin.review");
  });

  it("maps secondary PawApp routes to the bundle window", () => {
    expect(pathToRouteId("/apps/office/settings", routes)).toBe(
      "plugin.office",
    );
  });

  it("falls back to App Center for unknown PawApp deep links", () => {
    expect(pathToRouteId("/apps/unknown", routes)).toBe(
      "core.app-center.embed",
    );
  });

  it("does not map unrelated paths to the root route", () => {
    expect(
      pathToRouteId("/not-registered", [
        ...routes,
        { id: "core.root", path: "/", source: "core" },
      ]),
    ).toBeUndefined();
  });

  it("keeps root navigation inside the current OS window", () => {
    expect(
      pathToRouteId("/", [
        ...routes,
        { id: "core.root", path: "/", source: "core" },
      ]),
    ).toBeUndefined();
  });
});
