import { describe, expect, it } from "vitest";
import { can, Capability } from "./capabilities";

describe("platform capabilities", () => {
  it("gives admins normal use plus governance capabilities", () => {
    expect(can("multi_user", "admin", Capability.PlatformUse)).toBe(true);
    expect(can("multi_user", "admin", Capability.UsersManage)).toBe(true);
    expect(can("multi_user", "admin", Capability.PlatformSettingsManage)).toBe(
      true,
    );
  });

  it("keeps normal use for members without platform governance", () => {
    expect(can("multi_user", "member", Capability.PlatformUse)).toBe(true);
    expect(can("multi_user", "member", Capability.UsersManage)).toBe(false);
    expect(
      can("multi_user", "member", Capability.PlatformSettingsManage),
    ).toBe(false);
  });

  it("preserves every legacy route", () => {
    expect(can("legacy", null, Capability.UsersManage)).toBe(true);
    expect(can("legacy", null, Capability.PlatformSettingsManage)).toBe(true);
  });
});
