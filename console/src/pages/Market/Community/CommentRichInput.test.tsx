import { createRef } from "react";
import { act, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
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
});
