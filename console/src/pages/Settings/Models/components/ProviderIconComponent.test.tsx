import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ProviderIcon } from "./ProviderIconComponent";

describe("ProviderIcon", () => {
  it.each([13, 16, 24, 32, 36])(
    "preserves the requested %ipx size for images and letter fallbacks",
    (size) => {
      render(<ProviderIcon providerId="openrouter" size={size} />);

      const image = screen.getByRole("img", { name: "openrouter" });
      const imageStyle = getComputedStyle(image);
      expect(imageStyle.width).toBe(`${size}px`);
      expect(imageStyle.height).toBe(`${size}px`);

      fireEvent.error(image);

      const fallbackStyle = getComputedStyle(screen.getByTitle("openrouter"));
      expect(fallbackStyle.width).toBe(`${size}px`);
      expect(fallbackStyle.height).toBe(`${size}px`);
    },
  );
});
