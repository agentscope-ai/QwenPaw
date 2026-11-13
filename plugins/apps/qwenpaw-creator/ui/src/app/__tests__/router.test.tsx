import { describe, expect, it } from "vitest";
import { matchRoutes } from "react-router-dom";
import { CREATOR_ROUTE_OBJECTS, FORMAL_CREATOR_ROUTES } from "@/app/router";
import { normalizeCreatorRoute } from "@/routing/navigation";

function terminalRouteId(path: string): string | undefined {
  const matches = matchRoutes(CREATOR_ROUTE_OBJECTS, path);
  return matches?.at(-1)?.route.id;
}

describe("Creator hash router", () => {
  it("registers the Blueprint, parameterized Plan/Workbench, legacy and Assets page paths", () => {
    expect(FORMAL_CREATOR_ROUTES).toEqual([
      "/",
      "/project/:id",
      "/project/:id/t/:timelineId/plan",
      "/project/:id/t/:timelineId/plan/element/:elementId",
      "/project/:id/plan",
      "/project/:id/plan/element/:elementId",
      "/project/:id/assets",
    ]);
    expect(terminalRouteId("/")).toBe("home");
    expect(terminalRouteId("/project/p1/t/timeline%3Amain/plan")).toBe(
      "project-timeline-plan",
    );
    expect(
      terminalRouteId("/project/p1/t/timeline%3Amain/plan/element/r2v-window"),
    ).toBe("project-timeline-element-workbench");
    // Legacy paths stay routable: /plan redirects to the primary timeline's
    // parameterized route, the element workbench renders directly.
    expect(terminalRouteId("/project/p1/plan")).toBe("project-plan");
    expect(terminalRouteId("/project/p1/plan/element/r2v-window")).toBe(
      "project-element-workbench",
    );
    expect(terminalRouteId("/project/p1/assets")).toBe("project-assets");
    expect(terminalRouteId("/project/p1/unknown")).toBe("project-not-found");
  });

  it("keeps /project/:id as the blueprint default entry", () => {
    expect(terminalRouteId("/project/p1")).toBe("project-blueprint");
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
