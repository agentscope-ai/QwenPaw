import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { TranscriptText } from "./TranscriptText";

it("renders replayed file tokens as compact references, not their internal ids", () => {
  const {container} = render(<TranscriptText text="分析 @[需求.md](chat-file:personal_library:private-id) /writing" />);
  expect(screen.getByText("需求.md")).toBeTruthy();
  expect(container.textContent).not.toContain("private-id");
  expect(container.textContent).toContain("/writing");
});
