import { describe, it, expect } from "vitest";
import { parseShellResult } from "./ShellExecutionCard";

describe("parseShellResult", () => {
  it("returns empty for null/undefined", () => {
    expect(parseShellResult(null)).toEqual({
      exitCode: null,
      stdout: "",
      stderr: "",
      raw: "",
    });
    expect(parseShellResult(undefined)).toEqual({
      exitCode: null,
      stdout: "",
      stderr: "",
      raw: "",
    });
  });

  it("parses success with stdout only", () => {
    const result = parseShellResult("file1\nfile2\nfile3");
    expect(result.exitCode).toBe(0);
    expect(result.stdout).toBe("file1\nfile2\nfile3");
    expect(result.stderr).toBe("");
  });

  it("parses success with stdout and stderr", () => {
    const raw = "output line 1\noutput line 2\n[stderr]\nwarning: something";
    const result = parseShellResult(raw);
    expect(result.exitCode).toBe(0);
    expect(result.stdout).toBe("output line 1\noutput line 2");
    expect(result.stderr).toBe("warning: something");
  });

  it("parses success with no output", () => {
    const result = parseShellResult(
      "Command executed successfully (no output).",
    );
    expect(result.exitCode).toBe(0);
    expect(result.stdout).toBe("");
    expect(result.stderr).toBe("");
  });

  it("parses failure with exit code and stderr", () => {
    const raw =
      "Command failed with exit code 1.\n[stdout]\npartial output\n[stderr]\nerror: not found";
    const result = parseShellResult(raw);
    expect(result.exitCode).toBe(1);
    expect(result.stdout).toBe("partial output");
    expect(result.stderr).toBe("error: not found");
  });

  it("parses failure with negative exit code (timeout)", () => {
    const raw =
      "Command failed with exit code -1.\n[stderr]\n⚠️ TimeoutError: The command execution exceeded the timeout of 60 seconds.";
    const result = parseShellResult(raw);
    expect(result.exitCode).toBe(-1);
    expect(result.stdout).toBe("");
    expect(result.stderr).toContain("TimeoutError");
  });

  it("parses failure with only stderr", () => {
    const raw =
      "Command failed with exit code 127.\n[stderr]\nbash: foo: command not found";
    const result = parseShellResult(raw);
    expect(result.exitCode).toBe(127);
    expect(result.stdout).toBe("");
    expect(result.stderr).toBe("bash: foo: command not found");
  });

  it("handles non-string result (object)", () => {
    const result = parseShellResult({ some: "data" });
    expect(result.exitCode).toBe(0);
    expect(result.stdout).toContain('"some"');
  });
});
