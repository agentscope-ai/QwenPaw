import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CommunityFeedback } from ".";
import type { InstallationOrigin } from "@/api/types/community";
vi.mock("@/pages/CommunityFeedback/PostComposer", () => ({
  PostComposer: ({ origin }: { origin: InstallationOrigin }) => (
    <div data-testid="composer">{origin.resource_id}</div>
  ),
}));
vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: { error: vi.fn() } }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
const origin: InstallationOrigin = {
  provider: "agentscope-platform",
  resource_type: "plugin",
  resource_id: "@owner/demo",
  installed_version: "1.2.3",
};
describe("CommunityFeedback", () => {
  it("opens the linked-resource composer without opening the card", () => {
    const parent = vi.fn();
    render(
      <div onClick={parent}>
        <CommunityFeedback origin={origin} resourceName="Demo" />
      </div>,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "communityFeedback.forResource" }),
    );
    expect(screen.getByTestId("composer")).toHaveTextContent("@owner/demo");
    expect(parent).not.toHaveBeenCalled();
  });
  it.each([
    undefined,
    null,
    { ...origin, provider: "github" },
    { ...origin, resource_id: " " },
  ])("hides feedback for invalid provenance", (value) => {
    render(
      <CommunityFeedback
        origin={value as InstallationOrigin}
        resourceName="Demo"
      />,
    );
    expect(screen.queryByRole("button")).toBeNull();
  });
});
