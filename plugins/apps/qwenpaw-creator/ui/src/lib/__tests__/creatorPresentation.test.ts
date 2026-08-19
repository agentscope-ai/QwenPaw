import { describe, expect, it } from "vitest";
import i18n from "@/i18n";
import {
  creatorToolLabel,
  getToolRunningLabel,
} from "@/lib/creatorPresentation";

describe("creatorToolLabel", () => {
  it("labels newly registered specialist tools instead of falling back", () => {
    expect(creatorToolLabel("tts_generation")).toBe("合成语音");
    expect(creatorToolLabel("s2v_generation")).toBe("生成口型视频");
    expect(creatorToolLabel("create_character_voice")).toBe("创建角色音色");
    expect(creatorToolLabel("read_document")).toBe("读取文档");
    expect(creatorToolLabel("query_source_memory")).toBe("查询素材记忆");
    expect(creatorToolLabel("design_motion_overlays")).toBe("设计动态字幕");
  });

  it("never falls back to the processing status label", () => {
    // The action title appends 处理中/完成 after the label, so the
    // fallback must stay neutral to avoid "处理中处理中" / "处理中完成".
    const fallback = creatorToolLabel("some_future_tool");
    expect(fallback).not.toBe(i18n.t("presentation.processing"));
    expect(fallback).not.toContain("处理中");
  });

  it("provides running labels for the newly registered tools", () => {
    expect(getToolRunningLabel("tts_generation")).toBe("语音合成中…");
    expect(getToolRunningLabel("design_motion_overlays")).toBe(
      "动态字幕设计中…",
    );
  });
});
