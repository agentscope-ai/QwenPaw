import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ProviderApiKeyLink } from "./ProviderApiKeyLink";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("provider API key links", () => {
  it("supports plugin metadata without provider-specific UI branches", () => {
    render(<ProviderApiKeyLink url="https://plugin.example/keys" />);
    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      "https://plugin.example/keys",
    );
    expect(screen.getByRole("link")).toHaveAttribute(
      "rel",
      "noopener noreferrer",
    );
  });

  it.each([undefined, "", "javascript:alert(1)", "file:///tmp/key"])(
    "omits invalid metadata: %s",
    (url) => {
      render(<ProviderApiKeyLink url={url} />);
      expect(screen.queryByRole("link")).not.toBeInTheDocument();
    },
  );
});
