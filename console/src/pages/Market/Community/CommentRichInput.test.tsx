import { createRef } from "react";
import { act, fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import CommentRichInput, {
  type CommentRichInputHandle,
} from "./CommentRichInput";
import { CUSTOM_EMOJI_URLS } from "./customEmoji";

describe("CommentRichInput emoji token gating", () => {
  it("renders allowlisted emoji tokens as images", () => {
    const { container } = render(
      <CommentRichInput
        value={`x [emoji:${CUSTOM_EMOJI_URLS[0]}] y`}
        onChange={() => {}}
      />,
    );
    const img = container.querySelector("img[data-emoji-url]");
    expect(img).toHaveAttribute("src", CUSTOM_EMOJI_URLS[0]);
  });

  it("keeps non-allowlisted emoji tokens as literal text", () => {
    const { container } = render(
      <CommentRichInput
        value={
          "a [emoji:javascript:alert(1)] b " +
          "[emoji:https://evil.example.com/x.png]"
        }
        onChange={() => {}}
      />,
    );
    // No image node may ever carry an off-allowlist URL (the sink flagged
    // by CodeQL alert #656); bad tokens degrade to visible plain text.
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("[emoji:javascript:alert(1)]");
    expect(container.textContent).toContain(
      "[emoji:https://evil.example.com/x.png]",
    );
  });

  it("drops non-allowlisted urls passed to insertEmoji", () => {
    const ref = createRef<CommentRichInputHandle>();
    const { container } = render(
      <CommentRichInput ref={ref} value="" onChange={() => {}} />,
    );
    act(() => {
      ref.current?.insertEmoji("https://evil.example.com/x.png");
    });
    expect(container.querySelector("img")).toBeNull();
    act(() => {
      ref.current?.insertEmoji(CUSTOM_EMOJI_URLS[1]);
    });
    expect(container.querySelector("img[data-emoji-url]")).toHaveAttribute(
      "src",
      CUSTOM_EMOJI_URLS[1],
    );
  });

  it("renders newlines as br nodes and round-trips them", () => {
    const onChange = vi.fn();
    const { container } = render(
      <CommentRichInput value={"a\n\nb"} onChange={onChange} />,
    );
    const root = container.querySelector("[contenteditable]");
    // No "\n" text nodes: a trailing one loses the caret in Chromium.
    expect(root?.textContent).toBe("ab");
    expect(root?.querySelectorAll("br")).toHaveLength(2);
    fireEvent.input(root as Element);
    expect(onChange).toHaveBeenLastCalledWith("a\n\nb");
  });

  it("serializes native browser line-break soup back to newlines", () => {
    const onChange = vi.fn();
    const { container } = render(
      <CommentRichInput value="" onChange={onChange} />,
    );
    const root = container.querySelector("[contenteditable]") as Element;
    // Chromium/Firefox br breaks…
    root.innerHTML = "a<br>b";
    fireEvent.input(root);
    expect(onChange).toHaveBeenLastCalledWith("a\nb");
    // …Safari-style blocks with an empty placeholder-br line…
    root.innerHTML = "<div>a</div><div><br></div><div>b</div>";
    fireEvent.input(root);
    expect(onChange).toHaveBeenLastCalledWith("a\n\nb");
    // …and a trailing caret-placeholder br inside a block.
    root.innerHTML = "<div>a<br></div><div>b</div>";
    fireEvent.input(root);
    expect(onChange).toHaveBeenLastCalledWith("a\nb");
  });

  it("leaves Enter to the browser editing pipeline", () => {
    const onChange = vi.fn();
    const { container } = render(
      <CommentRichInput value="abc" onChange={onChange} />,
    );
    const root = container.querySelector("[contenteditable]") as Element;
    // Regression pin: the old handler intercepted Enter and inserted a
    // "\n" text node, which Chromium's caret gravity then typed before.
    fireEvent.keyDown(root, { key: "Enter" });
    expect(onChange).not.toHaveBeenCalled();
    expect(root.textContent).toBe("abc");
  });

  it("falls back to range insertion when execCommand is unavailable", () => {
    const onChange = vi.fn();
    const { container } = render(
      <CommentRichInput value="" onChange={onChange} />,
    );
    const root = container.querySelector("[contenteditable]") as Element;
    // jsdom has no execCommand; real browsers without it must still paste.
    fireEvent.paste(root, {
      clipboardData: {
        getData: (type: string) => (type === "text/plain" ? "x\ny" : ""),
      } as unknown as DataTransfer,
    });
    expect(onChange).toHaveBeenLastCalledWith("x\ny");
  });

  it("lets a successful execCommand paste own the edit", () => {
    const onChange = vi.fn();
    const exec = vi.fn(() => true);
    document.execCommand = exec;
    try {
      const { container } = render(
        <CommentRichInput value="" onChange={onChange} />,
      );
      const root = container.querySelector("[contenteditable]") as Element;
      fireEvent.paste(root, {
        clipboardData: {
          getData: (type: string) => (type === "text/plain" ? "rep" : ""),
        } as unknown as DataTransfer,
      });
      expect(exec).toHaveBeenCalledWith("insertText", false, "rep");
      // No manual fallback insertion on top of the browser transaction.
      expect(root.textContent).toBe("");
      expect(onChange).not.toHaveBeenCalled();
    } finally {
      delete (document as unknown as Record<string, unknown>).execCommand;
    }
  });
});
