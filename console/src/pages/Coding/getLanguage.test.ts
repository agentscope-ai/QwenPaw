/**
 * Tests for the Coding editor's extension → Monaco language mapping.
 */

import { describe, expect, it } from "vitest";

import { getLanguage } from "./getLanguage";

describe("getLanguage", () => {
  it("maps RobotFramework extensions", () => {
    expect(getLanguage("tests/login.robot")).toBe("robotframework");
    expect(getLanguage("resources/common.resource")).toBe("robotframework");
    expect(getLanguage("SUITE.ROBOT")).toBe("robotframework");
  });

  it("keeps existing mappings intact", () => {
    expect(getLanguage("main.py")).toBe("python");
    expect(getLanguage("app.tsx")).toBe("typescript");
    expect(getLanguage("unknown.xyz")).toBe("plaintext");
  });

  it("maps C# and game shader extensions", () => {
    expect(getLanguage("Assets/Scripts/PlayerController.cs")).toBe("csharp");
    expect(getLanguage("Assets/Shaders/HologramShield.shader")).toBe("cpp");
    expect(getLanguage("Assets/Shaders/Lighting.cginc")).toBe("cpp");
    expect(getLanguage("Assets/Shaders/Dissolve.hlsl")).toBe("cpp");
    expect(getLanguage("res://shaders/water.gdshader")).toBe("cpp");
    expect(getLanguage("shaders/skybox.glsl")).toBe("cpp");
    expect(getLanguage("shaders/fullscreen.vert")).toBe("cpp");
    expect(getLanguage("shaders/fullscreen.frag")).toBe("cpp");
    expect(getLanguage("shaders/compute.wgsl")).toBe("wgsl");
  });

  it("maps common game scripting and C/C++ header extensions", () => {
    expect(getLanguage("scripts/player.gd")).toBe("python");
    expect(getLanguage("engine/renderer.hpp")).toBe("cpp");
    expect(getLanguage("engine/math.hxx")).toBe("cpp");
    expect(getLanguage("engine/platform.hh")).toBe("cpp");
  });
});
