import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import CommunityPage, { PostBody } from ".";
import {
  openExternalLink,
  openExternalLinkChecked,
} from "@/utils/openExternalLink";
import { communityConnectionApi } from "@/api/modules/community";
import { communityPostsApi } from "./api";
vi.mock("@/utils/openExternalLink", () => ({
  openExternalLink: vi.fn(),
  openExternalLinkChecked: vi.fn(async () => {}),
}));
vi.mock("./api", () => ({
  communityPostsApi: {
    list: vi.fn(),
    detail: vi.fn(),
    comments: vi.fn(),
    comment: vi.fn(),
    interact: vi.fn(),
    likeComment: vi.fn(),
  },
}));
vi.mock("@/api/modules/community", () => ({
  communityConnectionApi: {
    status: vi.fn(async () => ({
      status: "connected",
      account: { id: "account", display_name: "Alice" },
    })),
  },
}));
vi.mock("../components/MarketplaceHeader", () => ({
  MarketplaceHeader: () => <div>Header</div>,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
const post = {
  id: "p1",
  title: "Community post",
  body_html: "<p>Article body</p>",
};
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(communityPostsApi.list).mockResolvedValue({
    items: [post],
    total: 1,
  });
  vi.mocked(communityPostsApi.detail).mockResolvedValue(post);
  vi.mocked(communityPostsApi.comments).mockResolvedValue({
    items: [{ id: "c1", author_name: "Bob", content: "Existing comment" }],
    total: 1,
  });
  vi.mocked(communityPostsApi.comment).mockResolvedValue({
    id: "new",
    author_name: "Alice",
    content: "Draft",
  });
});
describe("Embedded community", () => {
  it("opens a post inside extensions and shows its comments", async () => {
    renderWithProviders(<CommunityPage />, {
      initialEntries: ["/market?tab=community"],
    });
    fireEvent.click(
      await screen.findByRole("link", { name: /Community post/ }),
    );
    expect(await screen.findByText("Article body")).toBeInTheDocument();
    expect(await screen.findByText("Existing comment")).toBeInTheDocument();
    expect(communityPostsApi.comment).not.toHaveBeenCalled();
  });
  it("submits a reply with its parent and connected account", async () => {
    renderWithProviders(<CommunityPage />, {
      initialEntries: ["/market?tab=community&post=p1"],
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "communityPage.reply" }),
    );
    fireEvent.change(screen.getByLabelText("communityPage.writeComment"), {
      target: { value: "Draft" },
    });
    fireEvent.click(screen.getByRole("button", { name: "communityPage.send" }));
    await waitFor(() =>
      expect(communityPostsApi.comment).toHaveBeenCalledWith(
        "p1",
        "Draft",
        "account",
        "c1",
      ),
    );
    await waitFor(() =>
      expect(screen.getByLabelText("communityPage.writeComment")).toHaveValue(
        "",
      ),
    );
  });
  it("preserves the draft when sending fails", async () => {
    vi.mocked(communityPostsApi.comment).mockRejectedValue(
      new Error("offline"),
    );
    renderWithProviders(<CommunityPage />, {
      initialEntries: ["/market?tab=community&post=p1"],
    });
    fireEvent.change(
      await screen.findByLabelText("communityPage.writeComment"),
      { target: { value: "Keep this draft" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "communityPage.send" }));
    expect(
      await screen.findByText("communityPage.sendError"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("communityPage.writeComment")).toHaveValue(
      "Keep this draft",
    );
    expect(communityPostsApi.comment).toHaveBeenCalledTimes(1);
  });
  it("removes executable content from Platform HTML", () => {
    const { container } = renderWithProviders(
      <PostBody
        post={{
          ...post,
          body_html:
            '<p>Safe text</p><script>alert(1)</script><img src="x" onerror="alert(1)"><a href="javascript:alert(1)">unsafe</a><iframe src="https://evil.example"></iframe>',
        }}
      />,
    );
    expect(
      container.querySelector("script,iframe,[onerror],[href^='javascript:']"),
    ).toBeNull();
    expect(screen.getByText("Safe text")).toBeInTheDocument();
  });
});

it("renders custom emoji in nested comment replies", async () => {
  const { CUSTOM_EMOJI_URLS } = await import("./customEmoji");
  vi.mocked(communityPostsApi.comments).mockResolvedValue({
    items: [
      {
        id: "c1",
        author_name: "Alice",
        content: "😎",
        replies: [
          {
            id: "r1",
            author_name: "Bob",
            content: `A [emoji:${CUSTOM_EMOJI_URLS[0]}] [emoji:${CUSTOM_EMOJI_URLS[1]}] B`,
          },
        ],
      },
    ],
    total: 1,
  });
  renderWithProviders(<CommunityPage />, {
    initialEntries: ["/market?tab=community&post=p1"],
  });
  const emojis = await screen.findAllByRole("img", { name: "emoji" });
  expect(emojis).toHaveLength(2);
  expect(emojis[0]).toHaveAttribute("src", CUSTOM_EMOJI_URLS[0]);
  expect(emojis[0].className).toContain("customEmoji");
  expect(screen.getByText("😎")).toBeInTheDocument();
});

it("keeps filters when sorting, and resets pagination", async () => {
  renderWithProviders(<CommunityPage />, {
    initialEntries: [
      "/market?tab=community&type=work_share&keyword=demo&page=3",
    ],
  });
  await screen.findByText("Community post");
  expect(communityPostsApi.list).toHaveBeenLastCalledWith(
    3,
    "demo",
    "work_share",
    "recommended",
    expect.any(AbortSignal),
  );
  fireEvent.click(screen.getByText("communityPage.latest"));
  await waitFor(() =>
    expect(communityPostsApi.list).toHaveBeenLastCalledWith(
      1,
      "demo",
      "work_share",
      "latest",
      expect.any(AbortSignal),
    ),
  );
  fireEvent.mouseDown(
    screen.getByRole("combobox", { name: "communityPage.type" }),
  );
  fireEvent.click(await screen.findByText("communityPage.app_case"));
  await waitFor(() =>
    expect(communityPostsApi.list).toHaveBeenLastCalledWith(
      1,
      "demo",
      "app_case",
      "latest",
      expect.any(AbortSignal),
    ),
  );
  fireEvent.click(screen.getByRole("link", { name: /Community post/ }));
  const back = await screen.findByRole("link", { name: /communityPage.back/ });
  expect(back.getAttribute("href")).toContain("sort=latest");
  expect(back.getAttribute("href")).toContain("type=app_case");
});
it("keeps cached posts with actionable network feedback", async () => {
  renderWithProviders(<CommunityPage />);
  await screen.findByText("Community post");
  vi.mocked(communityPostsApi.list).mockRejectedValueOnce(
    new Error("network_unavailable - private details"),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "communityPage.refresh" }),
  );
  expect(
    await screen.findByText("communityErrors.network"),
  ).toBeInTheDocument();
  expect(screen.getByText("Community post")).toBeInTheDocument();
  expect(screen.queryByText(/private details/)).toBeNull();
  expect(screen.queryByText("communityPage.empty")).toBeNull();
});
it("opens the local article and question composers without publishing", async () => {
  renderWithProviders(<CommunityPage />);
  fireEvent.click(
    screen.getByRole("button", { name: "communityPage.writeOnPlatform" }),
  );
  expect(
    await screen.findByRole("radio", { name: "communityAssist.article" }),
  ).toBeChecked();
  expect(
    screen.getByRole("button", { name: "communityCompose.publish" }),
  ).toBeDisabled();
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "communityPage.back" }));
  fireEvent.click(
    screen.getByRole("button", { name: "communityPage.askOnPlatform" }),
  );
  expect(
    await screen.findByRole("radio", { name: "communityPage.question" }),
  ).toBeChecked();
  expect(openExternalLinkChecked).not.toHaveBeenCalled();
  expect(communityPostsApi.comment).not.toHaveBeenCalled();
});

it("does not hide public content when account status cannot load", async () => {
  vi.mocked(communityConnectionApi.status).mockRejectedValueOnce(
    new Error("offline"),
  );
  renderWithProviders(<CommunityPage />, {
    initialEntries: ["/market?tab=community&post=p1"],
  });
  expect(await screen.findByText("Article body")).toBeInTheDocument();
  expect(screen.getByText("Existing comment")).toBeInTheDocument();
  expect(screen.queryByLabelText("communityPage.writeComment")).toBeNull();
});
it("opens sanitized HTML and comment links through the desktop-compatible opener", async () => {
  vi.mocked(communityPostsApi.detail).mockResolvedValueOnce({
    ...post,
    body_html: '<p><a href="/skills/demo"><strong>Resource</strong></a></p>',
  });
  vi.mocked(communityPostsApi.comments).mockResolvedValueOnce({
    total: 1,
    items: [
      {
        id: "c1",
        author_name: "Alice",
        content: "[Example](https://example.com)",
      },
    ],
  });
  renderWithProviders(<CommunityPage />, {
    initialEntries: ["/market?tab=community&post=p1"],
  });
  fireEvent.click(await screen.findByText("Resource"));
  expect(openExternalLink).toHaveBeenCalledWith(
    "https://platform.agentscope.io/skills/demo",
  );
  fireEvent.click(screen.getByRole("link", { name: "Example" }));
  expect(openExternalLink).toHaveBeenCalledWith("https://example.com/");
});

it("renders uploaded video links with controls and removes image transforms", () => {
  const { container } = renderWithProviders(
    <PostBody
      post={{
        ...post,
        body_html:
          '<a href="https://example.com/demo.mp4?x-oss-process=image/resize,w_1920">Demo</a><video src="https://example.com/native.webm" autoplay onerror="alert(1)"></video>',
      }}
    />,
  );
  const videos = container.querySelectorAll("video");
  expect(videos).toHaveLength(2);
  expect(videos[0]).toHaveAttribute("src", "https://example.com/demo.mp4");
  for (const video of videos) {
    expect(video).toHaveAttribute("controls");
    expect(video).not.toHaveAttribute("autoplay");
    expect(video).not.toHaveAttribute("onerror");
  }
});

it("keeps question answers and comments separate and submits an answer", async () => {
  vi.mocked(communityPostsApi.detail).mockResolvedValue({
    ...post,
    article_type: "question",
  });
  vi.mocked(communityPostsApi.comments).mockImplementation(
    async (_id, _page, _signal, kind) => ({
      total: 1,
      items: [
        {
          id: kind || "c",
          author_name: "Bob",
          content: kind === "answer" ? "A solution" : "A clarification",
          kind,
        },
      ],
    }),
  );
  renderWithProviders(<CommunityPage />, {
    initialEntries: ["/market?tab=community&post=p1"],
  });
  expect(await screen.findByText("A solution")).toBeVisible();
  expect(screen.getByText("A clarification")).not.toBeVisible();
  fireEvent.change(screen.getByLabelText("communityPage.writeAnswer"), {
    target: { value: "Try restarting" },
  });
  fireEvent.click(
    screen.getByRole("radio", { name: "communityPage.commentQuestion" }),
  );
  expect(screen.getByText("A clarification")).toBeVisible();
  expect(screen.getByText("A solution")).not.toBeVisible();
  fireEvent.click(screen.getByRole("radio", { name: "communityPage.answers" }));
  expect(screen.getByLabelText("communityPage.writeAnswer")).toHaveValue(
    "Try restarting",
  );
  fireEvent.click(
    screen.getByRole("button", { name: "communityPage.sendAnswer" }),
  );
  await waitFor(() =>
    expect(communityPostsApi.comment).toHaveBeenCalledWith(
      "p1",
      "Try restarting",
      "account",
      undefined,
      "answer",
    ),
  );
});

it("reflects Platform likes and saved state and opens reports on Platform", async () => {
  vi.mocked(communityPostsApi.interact)
    .mockResolvedValueOnce({ liked: true, like_count: 6 })
    .mockResolvedValueOnce({ favorited: true, favorite_count: 1 });
  renderWithProviders(<CommunityPage />, {
    initialEntries: ["/market?tab=community&post=p1"],
  });
  fireEvent.click(
    (
      await screen.findAllByRole("button", {
        name: "communityPage.like",
        pressed: false,
      })
    )[0],
  );
  expect(
    await screen.findByRole("button", {
      name: "communityPage.like 6",
      pressed: true,
    }),
  ).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", {
      name: "communityPage.favorite",
      pressed: false,
    }),
  );
  expect(
    await screen.findByRole("button", {
      name: "communityPage.favorited 1",
      pressed: true,
    }),
  ).toBeInTheDocument();
  expect(communityPostsApi.interact).toHaveBeenLastCalledWith(
    "p1",
    "favorite",
    "account",
  );
  fireEvent.click(screen.getByRole("button", { name: "communityPage.report" }));
  expect(openExternalLink).toHaveBeenCalledWith(
    "https://platform.agentscope.io/community/articles/p1",
  );
});
