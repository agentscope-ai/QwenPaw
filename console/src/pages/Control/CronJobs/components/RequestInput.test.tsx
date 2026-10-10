// @vitest-environment jsdom
import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RequestInput } from "./RequestInput";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const wrap = (text: string) => [
  { content: [{ text, type: "text" }], role: "user" },
];

function Editor({ initial = "" }: { initial?: string }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <RequestInput value={value} onChange={setValue} />
      <output data-testid="saved">{value}</output>
    </>
  );
}
const input = () => screen.getByRole("textbox") as HTMLTextAreaElement;
const saved = () => screen.getByTestId("saved").textContent || "";

describe("RequestInput", () => {
  it("round-trips a legacy task without nesting its message JSON inside text", () => {
    const original = wrap("杭州今天天气如何？");
    // Mirrors handleEdit's serialization and handleSubmit's JSON.parse.
    render(<Editor initial={JSON.stringify(original, null, 2)} />);
    expect(input().value).toBe("杭州今天天气如何？");
    expect(JSON.parse(saved())).toEqual(original);
    fireEvent.click(screen.getByText("cronJobs.jsonMode"));
    fireEvent.click(screen.getByText("cronJobs.textMode"));
    expect(JSON.parse(saved())).toEqual(original);
    fireEvent.change(input(), { target: { value: "明天的天气呢？" } });
    expect(JSON.parse(saved())).toEqual(wrap("明天的天气呢？"));
  });

  it("preserves all fields of a legacy multi-message request when saved unchanged", () => {
    const original = [
      { role: "system", content: [{ type: "text", text: "保持简洁" }] },
      {
        role: "user",
        content: [{ type: "text", text: "查询天气" }],
        name: "user",
      },
    ];
    render(<Editor initial={JSON.stringify(original, null, 2)} />);
    expect(screen.getByText("cronJobs.textMode")).toBeTruthy();
    expect(JSON.parse(saved())).toEqual(original);
  });

  it("defaults to text and wraps literal text for submission", () => {
    render(<Editor />);
    expect(input().value).toBe("");
    expect(screen.getByText("cronJobs.jsonMode")).toBeTruthy();
    const text = '杭州天气？\n包含 "引号" 和 {JSON}';
    fireEvent.change(input(), { target: { value: text } });
    expect(JSON.parse(saved())).toEqual(wrap(text));
    fireEvent.change(input(), { target: { value: "   " } });
    expect(saved()).toBe("");
  });

  it("fills the JSON example and can return to text", () => {
    render(<Editor />);
    fireEvent.click(screen.getByText("cronJobs.jsonMode"));
    expect(JSON.parse(input().value)).toEqual(
      wrap("cronJobs.requestTextExample"),
    );
    fireEvent.click(screen.getByText("cronJobs.textMode"));
    expect(input().value).toBe("cronJobs.requestTextExample");
  });

  it("preserves edits through text to JSON to text and back", () => {
    render(<Editor initial={JSON.stringify(wrap("原始任务"))} />);
    expect(input().value).toBe("原始任务");
    fireEvent.change(input(), { target: { value: "修改任务" } });
    fireEvent.click(screen.getByText("cronJobs.jsonMode"));
    expect(JSON.parse(input().value)).toEqual(wrap("修改任务"));
    fireEvent.change(input(), {
      target: { value: JSON.stringify(wrap("JSON 修改")) },
    });
    fireEvent.click(screen.getByText("cronJobs.textMode"));
    expect(input().value).toBe("JSON 修改");
    fireEvent.click(screen.getByText("cronJobs.jsonMode"));
    expect(JSON.parse(input().value)).toEqual(wrap("JSON 修改"));
  });

  it("keeps advanced JSON intact and retains its draft across mode switches", () => {
    const advanced = JSON.stringify([
      {
        role: "user",
        content: [
          { type: "text", text: "分析图片" },
          { type: "image", image_url: "example" },
        ],
      },
    ]);
    render(<Editor initial={advanced} />);
    expect(input().value).toBe(advanced);
    expect(saved()).toBe(advanced);
    fireEvent.click(screen.getByText("cronJobs.textMode"));
    fireEvent.click(screen.getByText("cronJobs.jsonMode"));
    expect(input().value).toBe(advanced);
  });

  it("lets users leave unfinished JSON and recover the draft", () => {
    render(<Editor initial={JSON.stringify(wrap("任务"))} />);
    fireEvent.click(screen.getByText("cronJobs.jsonMode"));
    fireEvent.change(input(), { target: { value: "{unfinished" } });
    fireEvent.click(screen.getByText("cronJobs.textMode"));
    expect(input().value).toBe("任务");
    expect(JSON.parse(saved())).toEqual(wrap("任务"));
    fireEvent.click(screen.getByText("cronJobs.jsonMode"));
    expect(input().value).toBe("{unfinished");
  });
});
