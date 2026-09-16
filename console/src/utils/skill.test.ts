import { expect, it } from "vitest";
import { deriveInstalledFromLabel } from "./skill";

it.each([
  "E:/private/skills/demo",
  "/home/user/private",
  "C:\\secret\\skill",
  "https://host.invalid/?token=synthetic",
  "unknown",
])("does not expose unrecognized source metadata: %s", (value) => {
  expect(deriveInstalledFromLabel(value)).toBe("");
});
it("retains known provider labels and absent legacy origins", () => {
  expect(deriveInstalledFromLabel("github")).toBe("GitHub");
  expect(deriveInstalledFromLabel("zip")).toBe("ZIP");
  expect(deriveInstalledFromLabel(undefined)).toBe("");
});
