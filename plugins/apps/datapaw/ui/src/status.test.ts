import { describe, expect, it } from "vitest";

import type { AppStatus } from "./api";
import type { PawDependencySnapshot, PawDependencyStatus } from "./sdk";
import { buildAppStatusModel, groupDependencies } from "./status";

function dependency(
  id: string,
  health: PawDependencyStatus["health"],
  required = false,
): PawDependencyStatus {
  return {
    id,
    display_name: id,
    ownership: "external",
    required,
    lifecycle: "unmanaged",
    health,
    error_code: null,
    message: "",
    remediation: null,
    capabilities: [],
    actions: ["check"],
    last_checked_at: "2026-08-11T00:00:00Z",
    latency_ms: 4,
  };
}

function snapshot(dependencies: PawDependencyStatus[]): PawDependencySnapshot {
  return {
    schema_version: "1",
    app_id: "datapaw",
    summary: "healthy",
    dependencies,
    capabilities: [],
  };
}

const status: AppStatus = {
  app: "datapaw",
  service: { name: "context", ready: true, mode: "managed" },
  health: {},
  skills_available: true,
  skills: { available: true, count: 31, providers: 7 },
  dependencies: snapshot([]),
};

describe("DataPaw status model", () => {
  it("keeps an optional graph outage separate from overall readiness", () => {
    const dependencies = snapshot([
      dependency("context", "healthy", true),
      dependency("source:warehouse", "healthy"),
      dependency("graph-store", "unavailable"),
    ]);

    const model = buildAppStatusModel(status, dependencies, "warehouse");

    expect(model.label).toBe("Ready");
    expect(model.categories.find((item) => item.id === "graph")).toEqual(
      expect.objectContaining({
        detail: "Optional unavailable",
        tone: "error",
        optional: true,
      }),
    );
  });

  it("degrades when the selected business source is unavailable", () => {
    const dependencies = snapshot([
      dependency("context", "healthy", true),
      dependency("source:warehouse", "unavailable"),
    ]);

    const model = buildAppStatusModel(status, dependencies, "warehouse");

    expect(model.label).toBe("Degraded");
    expect(model.categories.find((item) => item.id === "data")?.detail).toBe(
      "Selected source unavailable",
    );
  });

  it("categorizes required, business-data, and optional dependencies", () => {
    const groups = groupDependencies([
      dependency("context", "healthy", true),
      dependency("source:warehouse", "healthy"),
      dependency("graph-store", "healthy"),
    ]);

    expect(groups.map((group) => [group.id, group.dependencies[0].id])).toEqual(
      [
        ["core", "context"],
        ["data", "source:warehouse"],
        ["optional", "graph-store"],
      ],
    );
  });
});
