import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import { request } from "@/api/request";
import { CommunityRelatedResources } from "./CommunityRelatedResources";
vi.mock("@/api/request", () => ({ request: vi.fn() }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
const detail = {
  discussionUrl: "https://platform.agentscope.io/community/articles/post",
  resourceName: "Post title",
  resourceType: "article",
  resourceId: "post",
  receivedAt: new Date(),
  eventLabelKey: "reply",
};
describe("Related resources", () => {
  it("shows every linked Skill and Plugin instead of the article", async () => {
    vi.mocked(request).mockResolvedValue({
      resources: [
        {
          id: "s1",
          type: "skill",
          name: "Skill One",
          url: "https://platform.agentscope.io/skills/s1",
        },
        {
          id: "s2",
          type: "skill",
          name: "Skill Two",
          url: "https://platform.agentscope.io/skills/s2",
        },
        {
          id: "p1",
          type: "plugin",
          name: "Plugin One",
          url: "https://platform.agentscope.io/plugins/p1",
        },
      ],
    });
    renderWithProviders(<CommunityRelatedResources detail={detail} />);
    expect(
      await screen.findByRole("link", { name: "Skill One (Skill)" }),
    ).toHaveAttribute("href", "https://platform.agentscope.io/skills/s1");
    expect(screen.getAllByRole("link")).toHaveLength(3);
    expect(screen.queryByText("Post title")).toBeNull();
  });
  it("shows an explicit empty state for a post without resources", async () => {
    vi.mocked(request).mockResolvedValue({ resources: [] });
    renderWithProviders(<CommunityRelatedResources detail={detail} />);
    expect(
      await screen.findByText("communityInbox.noResources"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });
});
