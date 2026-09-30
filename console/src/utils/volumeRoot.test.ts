import { describe, expect, it } from "vitest";

import { isVolumeRoot } from "./volumeRoot";

describe("isVolumeRoot", () => {
  it("detects a Windows drive root", () => {
    expect(isVolumeRoot("C:\\")).toBe(true);
    expect(isVolumeRoot("C:/")).toBe(true);
    expect(isVolumeRoot("C:")).toBe(true);
    expect(isVolumeRoot("e:\\")).toBe(true);
  });

  it("detects the POSIX root", () => {
    expect(isVolumeRoot("/")).toBe(true);
  });

  it("detects a UNC share root", () => {
    expect(isVolumeRoot("//server/share")).toBe(true);
    expect(isVolumeRoot("\\\\server\\share")).toBe(true);
  });

  it("treats ordinary directories as safe", () => {
    expect(isVolumeRoot("C:\\Users\\me\\project")).toBe(false);
    expect(isVolumeRoot("C:/Users/me/project")).toBe(false);
    expect(isVolumeRoot("/home/me/project")).toBe(false);
    expect(isVolumeRoot("//server/share/folder")).toBe(false);
    expect(isVolumeRoot("relative/folder")).toBe(false);
  });

  it("ignores empty input", () => {
    expect(isVolumeRoot("")).toBe(false);
    expect(isVolumeRoot("   ")).toBe(false);
  });
});
