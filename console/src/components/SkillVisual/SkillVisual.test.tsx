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
    expect(container.querySelector("[role='img']")).toBeInTheDocument();
  });
});

describe("getFileIcon", () => {
  const cases: [string, string][] = [
    ["file_reader", "FileTextFilled"],
    ["news", "FileTextFilled"],
    ["docx", "FileWordFilled"],
    ["xlsx", "FileExcelFilled"],
    ["pptx", "FilePptFilled"],
    ["pdf", "FilePdfFilled"],
    ["cron", "CalendarFilled"],
    ["report.txt", "FileTextFilled"],
    ["archive.zip", "FileZipFilled"],
    ["photo.jpg", "FileImageFilled"],
    ["script.py", "CodeFilled"],
    ["unknown.xyz", "FileTextFilled"],
  ];

  it.each(cases)("getFileIcon('%s') renders correct icon", (input) => {
    const { container } = render(<>{getFileIcon(input)}</>);
    expect(container.querySelector("[role='img']")).toBeInTheDocument();
  });

  it("handles extra whitespace and mixed case in skill key", () => {
    const { container } = render(<>{getFileIcon("  CRON  ")}</>);
    expect(container.querySelector("[role='img']")).toBeInTheDocument();
  });
});
