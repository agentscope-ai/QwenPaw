import { describe, expect, it } from "vitest";
import { memoryBackendRegistry } from "./memoryBackends";

describe("memory backend frontend registry", () => {
  it("registers and disposes plugin-owned configuration UI", () => {
    const ConfigComponent = () => null;
    const registration = memoryBackendRegistry.register("test-memory", {
      id: "TEST-BACKEND",
      label: "Test Backend",
      ConfigComponent,
    });
    expect(
      memoryBackendRegistry
        .getSnapshot()
        .find((item) => item.id === "test-backend")?.ConfigComponent,
    ).toBe(ConfigComponent);
    registration.dispose();
    expect(
      memoryBackendRegistry
        .getSnapshot()
        .some((item) => item.id === "test-backend"),
    ).toBe(false);
  });

  it("marks a frontend registration unavailable when the backend is absent", () => {
    const registration = memoryBackendRegistry.register("missing-memory", {
      id: "MISSING-BACKEND",
      label: "Missing Backend",
    });

    memoryBackendRegistry.syncAvailable([]);

    expect(
      memoryBackendRegistry
        .getSnapshot()
        .find((item) => item.id === "missing-backend")?.available,
    ).toBe(false);
    registration.dispose();
  });

  it("restores availability after the backend registers on the server", () => {
    const registration = memoryBackendRegistry.register("late-memory", {
      id: "LATE-BACKEND",
      label: "Late Backend",
    });
    memoryBackendRegistry.syncAvailable([]);

    memoryBackendRegistry.syncAvailable([
      {
        id: "late-backend",
        label: "Late Backend",
        source: "plugin:late-memory",
        available: true,
      },
    ]);

    expect(
      memoryBackendRegistry
        .getSnapshot()
        .find((item) => item.id === "late-backend")?.available,
    ).toBe(true);
    registration.dispose();
  });
});
