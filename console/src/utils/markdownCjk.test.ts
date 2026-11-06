import { describe, expect, it } from "vitest";

import { normalizeCjkEmphasis } from "./markdownCjk";

describe("normalizeCjkEmphasis", () => {
  it("repairs all supported emphasis delimiters", () => {
    expect(normalizeCjkEmphasis("**粗体。**后文")).toBe("**粗体**。后文");
    expect(normalizeCjkEmphasis("__粗体！__后文")).toBe("__粗体__！后文");
    expect(normalizeCjkEmphasis("*斜体；*後文")).toBe("*斜体*；後文");
    expect(normalizeCjkEmphasis("_斜体：_かな")).toBe("_斜体_：かな");
  });

  it("repairs combined three-character delimiters", () => {
    expect(normalizeCjkEmphasis("***内容。***后文")).toBe("***内容***。后文");
    expect(normalizeCjkEmphasis("___内容。___后文")).toBe("___内容___。后文");
  });

  it("moves every approved punctuation mark", () => {
    for (const mark of ["。", "！", "？", "；", "：", "，", "、", "…"]) {
      expect(normalizeCjkEmphasis(`**内容${mark}**后`)).toBe(
        `**内容**${mark}后`,
      );
    }
  });

  it("moves trailing full-width closers", () => {
    for (const closer of [
      "”",
      "’",
      "」",
      "』",
      "】",
      "》",
      "〉",
      "）",
      "〕",
      "］",
    ]) {
      expect(normalizeCjkEmphasis(`**内容。${closer}**後`)).toBe(
        `**内容**。${closer}後`,
      );
    }
    expect(normalizeCjkEmphasis("**内容！？…”）**后")).toBe(
      "**内容**！？…”）后",
    );
  });

  it("recognizes Han, Kana, Hangul and supplementary Han followers", () => {
    for (const follower of ["后", "あ", "ア", "한", "𠀀"]) {
      expect(normalizeCjkEmphasis(`**内容。**${follower}`)).toBe(
        `**内容**。${follower}`,
      );
    }
  });

  it("handles multiple, adjacent and nested emphasis", () => {
    expect(normalizeCjkEmphasis("**甲。**乙 __丙！__丁 *戊？*己")).toBe(
      "**甲**。乙 __丙__！丁 *戊*？己",
    );
    expect(normalizeCjkEmphasis("**外层 *内层。*后续**")).toBe(
      "**外层 *内层*。后续**",
    );
  });

  it("does not widen the punctuation or follower scope", () => {
    const unchanged = [
      "**内容.**后",
      "**内容。**latin",
      "**内容。** 后",
      "**内容」**后",
      "plain 中文。**后",
      "**已经规范**。后",
    ];
    for (const source of unchanged) {
      expect(normalizeCjkEmphasis(source)).toBe(source);
    }
  });

  it("preserves fenced, inline and indented code", () => {
    const source = [
      "outside **正文。**后",
      "```markdown",
      "**代码。**后",
      "```",
      "~~~",
      "__代码！__後",
      "~~~",
      "inline `**代码。**后` end",
      "    *缩进代码；*後",
      "\t_缩进代码：_かな",
    ].join("\n");
    const expected = source.replace("**正文。**后", "**正文**。后");
    expect(normalizeCjkEmphasis(source)).toBe(expected);
  });

  it("preserves unclosed fenced and inline code", () => {
    const unclosedFence = "before\n```md\n**代码。**后\n";
    const unclosedInline = "before `code **示例。**后\nand more __示例！__後";
    expect(normalizeCjkEmphasis(unclosedFence)).toBe(unclosedFence);
    expect(normalizeCjkEmphasis(unclosedInline)).toBe(unclosedInline);
  });

  it("honors odd and even backslash escaping", () => {
    expect(normalizeCjkEmphasis("\\**内容。**后")).toBe("\\**内容。**后");
    expect(normalizeCjkEmphasis("\\\\**内容。**后")).toBe("\\\\**内容**。后");
    expect(normalizeCjkEmphasis("**内容。\\**后")).toBe("**内容。\\**后");
    expect(normalizeCjkEmphasis("**内容\\\\。**后")).toBe("**内容\\\\**。后");
  });

  it("preserves matched repairs around unrelated unclosed delimiters", () => {
    expect(normalizeCjkEmphasis("**内容。**后 *未闭合")).toBe(
      "**内容**。后 *未闭合",
    );
    expect(normalizeCjkEmphasis("**甲。**乙 **未闭合")).toBe(
      "**甲**。乙 **未闭合",
    );
    expect(normalizeCjkEmphasis("*未闭合 **甲。**乙")).toBe(
      "*未闭合 **甲**。乙",
    );
  });

  it("preserves crossing invalid delimiters", () => {
    const source = "**外层 *内层。**后续";
    expect(normalizeCjkEmphasis(source)).toBe(source);
  });

  it("preserves CRLF and unfinished emphasis", () => {
    expect(normalizeCjkEmphasis("**甲。**乙\r\n__丙！__丁\r\n")).toBe(
      "**甲**。乙\r\n__丙__！丁\r\n",
    );
    for (const source of ["**未闭合。后", "_未闭合！後", "结尾 **"]) {
      expect(normalizeCjkEmphasis(source)).toBe(source);
    }
  });

  it("is deterministic and idempotent", () => {
    const source = "**甲。**乙 and *丙！*丁";
    const once = normalizeCjkEmphasis(source);
    expect(normalizeCjkEmphasis(source)).toBe(once);
    expect(normalizeCjkEmphasis(once)).toBe(once);
  });

  it("leaves empty and plain text unchanged", () => {
    expect(normalizeCjkEmphasis("")).toBe("");
    const plain = "普通中文，没有任何强调标记。";
    expect(normalizeCjkEmphasis(plain)).toBe(plain);
  });
});
