import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import BidiSenderInput from "./BidiSenderInput";

vi.mock("antd", async () => {
  const React = await import("react");
  return {
    Input: {
      TextArea: React.forwardRef(function MockTextArea(
        props: Record<string, unknown>,
        ref: React.Ref<HTMLTextAreaElement>,
      ) {
        return React.createElement("textarea", { ...props, ref });
      }),
    },
  };
});

describe("BidiSenderInput", () => {
  it("sets dir=auto so mixed RTL/LTR input follows the Unicode BiDi algorithm", () => {
    render(<BidiSenderInput value="مرحبا Hello 123" onChange={vi.fn()} />);
    expect(screen.getByRole("textbox")).toHaveAttribute("dir", "auto");
  });
});
