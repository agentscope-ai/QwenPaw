import { describe, expect, it } from "vitest";
import { redactReportText, validateReportLink } from "./reportPrivacy";

describe("report material privacy", () => {
  it("masks credentials and identifiers while retaining error evidence", () => {
    const result = redactReportText(
      'Authorization: Bearer abc-secret\n"api_key": "secret-value"\n' +
        "password=pass&access_token=token\n/Users/alice/work/log.txt\n" +
        "C:\\Users\\bob\\error.log\nalice@example.org\nHTTP 503 loading menu",
    );
    for (const value of [
      "abc-secret",
      "secret-value",
      "pass&",
      "=token",
      "alice",
      "bob",
    ]) {
      expect(result).not.toContain(value);
    }
    expect(result).toContain("HTTP 503 loading menu");
  });

  it("only accepts an associated question on the trusted platform", () => {
    expect(
      validateReportLink(
        "https://platform.agentscope.io/community/ask?relatedPluginId=demo",
        "app",
      ),
    ).toBe(true);
    expect(
      validateReportLink(
        "https://platform.agentscope.io/community/ask?relatedSkillId=id",
        "skill",
      ),
    ).toBe(true);
    for (const url of [
      "https://evil.example/community/ask?relatedPluginId=demo",
      "https://user:pass@platform.agentscope.io/community/ask?relatedPluginId=demo",
      "https://platform.agentscope.io/community/ask",
      "javascript:alert(1)",
    ])
      expect(validateReportLink(url, "plugin")).toBe(false);
  });
});
