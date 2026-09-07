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
});
