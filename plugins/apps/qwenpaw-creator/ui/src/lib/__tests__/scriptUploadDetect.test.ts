import { describe, expect, it } from "vitest";
import {
  countScriptContentMarkers,
  detectScriptUpload,
  looksLikeScriptName,
  scriptSuffixKind,
} from "@/lib/scriptUploadDetect";

// 一份典型剧本的首屏：标题、角色行、动作提示都齐了。
const SCRIPT_MARKDOWN = [
  "## 场 1 · 内景 · 旧宅大厅 · 夜",
  "**林晚**：我回来了。",
  "> 她看见母亲遗留的钥匙压在鞋下。",
  "林晚：钥匙还在。",
].join("\n");

// 普通笔记：没有任何剧本结构特征，绝不能因此打断用户。
const PROSE = [
  "今天开会讨论了下一季度的排期，大家同意先做导入链路。",
  "会后我整理了纪要，明天同步给制作组。",
].join("\n");

function textFile(name: string, content: string): File {
  return new File([content], name, { type: "text/plain" });
}

describe("scriptSuffixKind", () => {
  it("splits uploads into text, document and everything else", () => {
    const textNames = [
      "剧本.md",
      "a.markdown",
      "b.txt",
      "c.text",
      "d.rst",
      "e.srt",
      "f.vtt",
    ];
    for (const name of textNames) {
      expect(scriptSuffixKind(name), name).toBe("text");
    }
    for (const name of ["剧本.pdf", "剧本.doc", "剧本.docx"]) {
      expect(scriptSuffixKind(name), name).toBe("document");
    }
    for (const name of ["分镜.png", "片段.mp4", "设定.json", "无后缀", ""]) {
      expect(scriptSuffixKind(name), name).toBe("none");
    }
  });

  it("ignores the suffix casing", () => {
    expect(scriptSuffixKind("我的剧本.MD")).toBe("text");
    expect(scriptSuffixKind("我的剧本.Docx")).toBe("document");
  });
});

describe("looksLikeScriptName", () => {
  it("recognises script-ish file names", () => {
    for (const name of [
      "我的剧本.md",
      "拍摄脚本 v2.txt",
      "第三集 台词.docx",
      "第 12 场 修订.md",
      "screenplay_final.pdf",
      "EP07 分场.docx",
    ]) {
      expect(looksLikeScriptName(name), name).toBe(true);
    }
  });

  it("leaves ordinary uploads alone", () => {
    for (const name of [
      "会议记录.md",
      "notes.txt",
      "shot list.pdf",
      "角色设定表.docx",
    ]) {
      expect(looksLikeScriptName(name), name).toBe(false);
    }
  });
});

describe("countScriptContentMarkers", () => {
  it("counts the structural markers of a script", () => {
    expect(countScriptContentMarkers(SCRIPT_MARKDOWN)).toBe(4);
  });

  it("needs more than one marker before it looks like a script", () => {
    // 单条特征（一个场次标题）不足以打断用户。
    expect(countScriptContentMarkers("第一场 日 内 教室")).toBe(1);
    expect(countScriptContentMarkers(PROSE)).toBe(0);
    expect(countScriptContentMarkers("")).toBe(0);
  });
});

describe("detectScriptUpload", () => {
  it("never asks about files that cannot carry a script", async () => {
    await expect(
      detectScriptUpload(new File([SCRIPT_MARKDOWN], "分镜.png")),
    ).resolves.toBe("none");
  });

  it("asks for a text file whose name already says script", async () => {
    // 文件名就够了，正文是不是剧本都照问（默认项仍是素材理解）。
    const detected = await detectScriptUpload(textFile("我的剧本.md", PROSE));
    expect(detected).toBe("text");
  });

  it("asks for an unnamed text file whose first screen is a script", async () => {
    await expect(
      detectScriptUpload(textFile("未命名.txt", SCRIPT_MARKDOWN)),
    ).resolves.toBe("text");
  });

  it("stays silent for ordinary text uploads", async () => {
    const detected = await detectScriptUpload(textFile("会议记录.md", PROSE));
    expect(detected).toBe("none");
  });

  it("only reads the first screen of a text file", async () => {
    // 剧本特征出现在 64KB 之后：不该为了判定把整份文件读进内存。
    const late = `${"x".repeat(70 * 1024)}\n${SCRIPT_MARKDOWN}`;
    await expect(detectScriptUpload(textFile("notes.txt", late))).resolves.toBe(
      "none",
    );
  });

  it("judges Word/PDF by name alone", async () => {
    // 文档正文在浏览器里读不出来，只有文件名像剧本时才问。
    await expect(
      detectScriptUpload(new File(["PK\u0003\u0004"], "我的剧本.docx")),
    ).resolves.toBe("document");
    await expect(
      detectScriptUpload(new File(["%PDF-1.7"], "扫描件.pdf")),
    ).resolves.toBe("none");
  });
});
