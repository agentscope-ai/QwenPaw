import { describe, expect, it } from "vitest";
import { matchRoutes } from "react-router-dom";
import { CREATOR_ROUTE_OBJECTS, FORMAL_CREATOR_ROUTES } from "@/app/router";
import { normalizeCreatorRoute } from "@/routing/navigation";

function terminalRouteId(path: string): string | undefined {
  const matches = matchRoutes(CREATOR_ROUTE_OBJECTS, path);
  return matches?.at(-1)?.route.id;
}

describe("Creator hash router", () => {
  it("registers only the Project, Timeline/Element Plan, R2V Workbench, and Assets page paths", () => {
    expect(FORMAL_CREATOR_ROUTES).toEqual([
      "/",
      "/project/:id/plan",
      "/project/:id/plan/element/:elementId",
      "/project/:id/assets",
    ]);
    expect(terminalRouteId("/")).toBe("home");
    expect(terminalRouteId("/project/p1/plan")).toBe("project-plan");
    expect(terminalRouteId("/project/p1/plan/element/r2v-window")).toBe(
      "project-element-workbench",
    );
    expect(terminalRouteId("/project/p1/assets")).toBe("project-assets");
    expect(terminalRouteId("/project/p1/unknown")).toBe("project-not-found");
  });

  it("keeps /project/:id as the sole project default entry", () => {
    expect(terminalRouteId("/project/p1")).toBe("project-default");
  });

  it("normalizes only safe same-app routes for host URL synchronization", () => {
    expect(normalizeCreatorRoute("/project/p1/plan?reviewOp=op-1")).toBe(
      "/project/p1/plan?reviewOp=op-1",
    );
    expect(normalizeCreatorRoute("/")).toBe("/");
    expect(normalizeCreatorRoute("project/p1/plan")).toBeNull();
    expect(normalizeCreatorRoute("//example.com/project/p1/plan")).toBeNull();
    expect(normalizeCreatorRoute("/project/p1/plan#other")).toBeNull();
  });
});
