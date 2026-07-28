/**
 * Tests for the RobotFramework Monaco language module:
 *   • registerRobotFramework wiring + double-registration guard
 *   • Monarch grammar smoke tests via a minimal rule-matching harness
 */

import { describe, expect, it, vi } from "vitest";
import {
  ROBOT_LANGUAGE_ID,
  conf,
  language,
  registerRobotFramework,
} from "./robotframework";

// ---------------------------------------------------------------------------
// Mock Monaco instance
// ---------------------------------------------------------------------------

function createMonacoMock(existingIds: string[] = []) {
  return {
    languages: {
      getLanguages: vi.fn(() => existingIds.map((id) => ({ id }))),
      register: vi.fn(),
      setLanguageConfiguration: vi.fn(),
      setMonarchTokensProvider: vi.fn(),
    },
  };
}

describe("registerRobotFramework", () => {
  it("registers language with .robot and .resource extensions", () => {
    const monaco = createMonacoMock();
    registerRobotFramework(monaco as never);

    expect(monaco.languages.register).toHaveBeenCalledWith(
      expect.objectContaining({
        id: ROBOT_LANGUAGE_ID,
        extensions: [".robot", ".resource"],
      }),
    );
    expect(monaco.languages.setLanguageConfiguration).toHaveBeenCalledWith(
      ROBOT_LANGUAGE_ID,
      conf,
    );
    expect(monaco.languages.setMonarchTokensProvider).toHaveBeenCalledWith(
      ROBOT_LANGUAGE_ID,
      language,
    );
  });

  it("skips registration when language already exists", () => {
    const monaco = createMonacoMock([ROBOT_LANGUAGE_ID]);
    registerRobotFramework(monaco as never);

    expect(monaco.languages.register).not.toHaveBeenCalled();
    expect(monaco.languages.setMonarchTokensProvider).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Grammar smoke tests
//
// Minimal emulation of Monarch's first-match-wins scanning over the `root`
// state (state transitions are not followed — enough for rule-level checks).
// ---------------------------------------------------------------------------

type MonarchAction = string | { token: string };
type MonarchRule = [RegExp, MonarchAction];

const rootRules = (language.tokenizer as Record<string, MonarchRule[]>).root;

function tokenOf(action: MonarchAction): string {
  return typeof action === "string" ? action : action.token;
}

function tokenize(line: string): { token: string; text: string }[] {
  const out: { token: string; text: string }[] = [];
  let pos = 0;
  while (pos < line.length) {
    let matched = false;
    for (const [pattern, action] of rootRules) {
      const re = new RegExp(pattern.source, "iy");
      re.lastIndex = pos;
      const m = re.exec(line);
      if (m && m[0].length > 0) {
        out.push({ token: tokenOf(action), text: m[0] });
        pos += m[0].length;
        matched = true;
        break;
      }
    }
    if (!matched) {
      out.push({ token: "", text: line[pos] });
      pos += 1;
    }
  }
  return out;
}

function tokensIn(line: string): string[] {
  return tokenize(line).map((t) => t.token);
}

describe("robotframework Monarch grammar", () => {
  it("highlights section headers case-insensitively", () => {
    expect(tokensIn("*** Test Cases ***")[0]).toBe("keyword.section");
    expect(tokensIn("*** settings ***")[0]).toBe("keyword.section");
    expect(tokensIn("*** Keywords ***")[0]).toBe("keyword.section");
    expect(tokensIn("*** Variables ***")[0]).toBe("keyword.section");
  });

  it("highlights comments", () => {
    expect(tokensIn("# top-level comment")[0]).toBe("comment");
    expect(tokensIn("    Log    hi    # trailing")).toContain("comment");
  });

  it("does not treat escaped hash as comment", () => {
    const tokens = tokenize("    Log    \\# not a comment");
    const escape = tokens.find((t) => t.text === "\\#");
    expect(escape?.token).toBe("string.escape");
  });

  it("highlights scalar / list / dict / env variables", () => {
    expect(tokensIn("${VAR}    value")).toContain("variable");
    expect(tokensIn("@{LIST}    a    b")).toContain("variable");
    expect(tokensIn("&{DICT}    k=v")).toContain("variable");
    expect(tokensIn("    Log    %{HOME}")).toContain("variable");
  });

  it("highlights bracket settings like [Tags] and [Arguments]", () => {
    const tags = tokenize("    [Tags]    smoke");
    expect(tags.find((t) => t.text === "[Tags]")?.token).toBe("tag");
    const args = tokenize("    [Arguments]    ${a}");
    expect(args.find((t) => t.text === "[Arguments]")?.token).toBe("tag");
  });

  it("highlights control-flow structures and FOR separators", () => {
    const forLine = tokenize("    FOR    ${i}    IN RANGE    10");
    const controls = forLine.filter((t) => t.token === "keyword.control");
    expect(controls.map((t) => t.text.trim())).toEqual(["FOR", "IN RANGE"]);
    expect(forLine.find((t) => t.text === "10")?.token).toBe("number");
    expect(tokensIn("    END")).toContain("keyword.control");
  });

  it("highlights settings-section directives at column 0", () => {
    expect(tokensIn("Library    Collections")[0]).toBe("keyword");
    expect(tokensIn("Suite Setup    Open Browser")[0]).toBe("keyword");
    expect(tokensIn("Resource    common.resource")[0]).toBe("keyword");
  });

  it("highlights test case / keyword names at column 0", () => {
    expect(tokensIn("My First Test")[0]).toBe("type");
    // A name merely starting with a directive word is still a name
    expect(tokensIn("Library helpers should load")[0]).toBe("type");
  });

  it("leaves indented keyword calls as plain text", () => {
    const tokens = tokenize("    Open Browser    https://example.org");
    expect(tokens.find((t) => t.text.includes("Open"))?.token).toBe("");
  });
});
