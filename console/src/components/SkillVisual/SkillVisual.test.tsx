import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { SkillVisual, getFileIcon } from "./index";

describe("SkillVisual", () => {
  it("renders emoji when provided", () => {
    const { container } = render(<SkillVisual name="my-skill" emoji="🤖" />);
    expect(container.textContent).toBe("🤖");
  });

  it("applies emojiClassName to emoji wrapper", () => {
    const { container } = render(
      <SkillVisual name="skill" emoji="⚡" emojiClassName="emoji-cls" />,
    );
    expect(container.querySelector(".emoji-cls")).toBeInTheDocument();
  });

  it("renders file icon when no emoji provided", () => {
    const { container } = render(<SkillVisual name="report.pdf" />);
    // Component uses lucide-react SVG icons after shadcn migration
    expect(container.querySelector("svg")).toBeInTheDocument();
  });
});

describe("getFileIcon", () => {
  const cases = [
    "file_reader",
    "news",
    "docx",
    "xlsx",
    "pptx",
    "pdf",
    "cron",
    "report.txt",
    "archive.zip",
    "photo.jpg",
    "script.py",
    "unknown.xyz",
  ];

  it.each(cases)("getFileIcon('%s') renders an svg icon", (input) => {
    const { container } = render(<>{getFileIcon(input)}</>);
    // Component uses lucide-react SVG icons after shadcn migration
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("handles extra whitespace and mixed case in skill key", () => {
    const { container } = render(<>{getFileIcon("  CRON  ")}</>);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });
});
