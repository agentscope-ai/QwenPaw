import { beforeEach, describe, expect, it } from "vitest";
import { routeRegistry } from "../store";

beforeEach(() => {
  routeRegistry.__resetForTests();
});

describe("routeRegistry case sensitivity", () => {
  it("keeps case-sensitive matching on the resolved route", () => {
    routeRegistry.add("core", {
      id: "r1",
      path: "/r1",
      caseSensitive: true,
      component: () => null,
    });

    expect(routeRegistry.snapshot()[0].caseSensitive).toBe(true);
  });
});
