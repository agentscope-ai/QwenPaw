import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, it, expect, vi } from "vitest";
import {
  BrowserRouter,
  MemoryRouter,
  Routes,
  Route,
  Link,
} from "react-router-dom";
import { PostComposer } from "./PostComposer";
import { communityConnectionApi } from "@/api/modules/community";
import { request } from "@/api/request";
import { clearWritingSessions, type AssistantSession } from "./writingSession";
const assistantReply = vi.hoisted(() => ({ text: "" }));
vi.mock("./PostAssistance", () => ({
  PostAssistance: ({
    onApply,
    sessionState,
    onSessionChange,
  }: {
    onApply: (text: string) => void;
    sessionState?: AssistantSession;
    onSessionChange: (state: AssistantSession) => void;
  }) => (
    <>
      <button onClick={() => onApply(assistantReply.text)}>
        Apply assistant draft
      </button>
      <span>{sessionState?.history[0]?.content}</span>
      <button
        onClick={() =>
          onSessionChange({
            language: "zh",
            writingStyle: "detailed",
            history: [{ role: "assistant", content: "Remember this reply" }],
            result: "Remember this reply",
            session: "chat-1",
            minutes: 60,
            evidence: [],
            warnings: [],
            publicImages: {},
            insertedImages: {},
          })
        }
      >
        Simulate reply
      </button>
    </>
  ),
}));
vi.mock("@/api/modules/community", () => ({
  communityConnectionApi: { status: vi.fn(), start: vi.fn() },
}));
vi.mock("@/api/request", () => ({ request: vi.fn() }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
beforeEach(() => {
  vi.clearAllMocks();
  clearWritingSessions();
  vi.mocked(communityConnectionApi.status).mockResolvedValue({
    status: "connected",
    account: { id: "a", display_name: "Alice" },
    sync_enabled: true,
    messages_enabled: true,
  });
});
it("blocks publishing while logged out", async () => {
  vi.mocked(communityConnectionApi.status).mockResolvedValue({
    status: "disconnected",
    sync_enabled: false,
    messages_enabled: true,
  });
  render(<PostComposer onClose={() => {}} initialBody={"# Report\nBody"} />);
  expect(
    await screen.findByText("communityCompose.loginRequired"),
  ).toBeInTheDocument();
  expect(screen.queryByLabelText("communityCompose.body")).toBeNull();
  expect(request).not.toHaveBeenCalled();
});
it("prefills report title and body, and requires explicit publication", async () => {
  vi.mocked(request).mockResolvedValue({ id: "new-post" });
  render(
    <PostComposer
      onClose={() => {}}
      initialBody={"# Report title\nReport body"}
    />,
  );
  expect(
    await screen.findByLabelText("communityCompose.postTitle"),
  ).toHaveValue("Report title");
  expect(screen.getByLabelText("communityCompose.body")).toHaveValue(
    "# Report title\nReport body",
  );
  expect(
    screen.getByRole("button", { name: "communityCompose.publish" }),
  ).toBeDisabled();
  expect(request).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(
    screen.getByRole("button", { name: "communityCompose.publish" }),
  );
  await waitFor(() => expect(request).toHaveBeenCalledTimes(1));
  const options = vi.mocked(request).mock.calls[0][1];
  expect(JSON.parse(String(options?.body))).toMatchObject({
    title: "Report title",
    content: "# Report title\nReport body",
    account_id: "a",
  });
  expect(
    await screen.findByText("communityCompose.published"),
  ).toBeInTheDocument();
});

it("uses the desktop browser for authorization from the report composer", async () => {
  const { invoke, isTauri } = await import("@/test/tauri-mock");
  isTauri.mockReturnValue(true);
  invoke.mockResolvedValue(undefined);
  const url =
    "https://platform.agentscope.io/cli/login?source=qwenpaw-community";
  vi.mocked(communityConnectionApi.status).mockResolvedValue({
    status: "disconnected",
    sync_enabled: false,
    messages_enabled: true,
  });
  vi.mocked(communityConnectionApi.start).mockResolvedValue({
    flow_id: "f1",
    authorize_url: url,
    expires_at: 9999999999,
  });
  const open = vi.spyOn(window, "open");
  try {
    render(<PostComposer onClose={() => {}} initialBody="# Report\nBody" />);
    fireEvent.click(
      await screen.findByRole("button", { name: "communityCompose.login" }),
    );
    await waitFor(() =>
      expect(invoke).toHaveBeenCalledWith("open_external_link", { url }),
    );
    expect(open).not.toHaveBeenCalled();
    expect(request).not.toHaveBeenCalled();
  } finally {
    isTauri.mockReturnValue(false);
    open.mockRestore();
  }
});

it("restores a Platform draft and publishes that same draft ID", async () => {
  vi.mocked(request).mockImplementation(async (path) => {
    if (String(path).startsWith("/community/drafts/native-draft?"))
      return {
        id: "native-draft",
        title: "Platform title",
        content: "Platform body",
        type: "discussion",
        resources: [],
        editable: true,
      } as never;
    return { id: "native-draft" } as never;
  });
  render(
    <PostComposer
      onClose={() => {}}
      draftId="native-draft"
      initialType="discussion"
    />,
  );
  await waitFor(() =>
    expect(screen.getByLabelText("communityCompose.body")).toHaveValue(
      "Platform body",
    ),
  );
  fireEvent.change(screen.getByLabelText("communityCompose.body"), {
    target: { value: "Revised body" },
  });
  fireEvent.click(screen.getByRole("button", { name: "communityDrafts.save" }));
  await screen.findByText("communityDrafts.saved");
  const save = vi
    .mocked(request)
    .mock.calls.find(([path]) => path === "/community/drafts")!;
  expect(JSON.parse(String(save[1]?.body))).toMatchObject({
    draft_id: "native-draft",
    content: "Revised body",
    article_type: "discussion",
  });
  await waitFor(() => expect(screen.getByRole("checkbox")).toBeEnabled());
  fireEvent.click(screen.getByRole("checkbox"));
  const publishButton = await screen.findByRole("button", {
    name: "communityCompose.publish",
  });
  await waitFor(() => expect(publishButton).toBeEnabled());
  fireEvent.click(publishButton);
  await screen.findByText("communityCompose.published");
  const publish = vi
    .mocked(request)
    .mock.calls.find(([path]) => path === "/community/posts")!;
  expect(JSON.parse(String(publish[1]?.body)).draft_id).toBe("native-draft");
  expect(
    vi
      .mocked(request)
      .mock.calls.some(([, options]) => options?.method === "DELETE"),
  ).toBe(false);
});

it.each([
  [
    "\n# New title\r\n\r\nIntroduction\n\n## Section\nDetails",
    "New title",
    "Introduction\n\n## Section\nDetails",
  ],
  ["## Body section\nDetails", "Existing title", "## Body section\nDetails"],
  [
    "An opening paragraph\n\n# Body heading",
    "Existing title",
    "An opening paragraph\n\n# Body heading",
  ],
])(
  "applies assistant output without duplicating a leading title: %s",
  async (reply, title, body) => {
    assistantReply.text = reply;
    render(<PostComposer onClose={() => {}} initialBody="" />);
    fireEvent.change(
      await screen.findByLabelText("communityCompose.postTitle"),
      { target: { value: "Existing title" } },
    );
    fireEvent.change(screen.getByLabelText("communityCompose.body"), {
      target: {
        value: "Previous body\n\n![Screenshot](https://example.com/image.png)",
      },
    });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(
      screen.getByRole("button", { name: "communityAssist.assist" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Apply assistant draft" }),
    );
    expect(screen.getByLabelText("communityCompose.postTitle")).toHaveValue(
      title,
    );
    expect(screen.getByLabelText("communityCompose.body")).toHaveValue(
      `${body}\n\n![Screenshot](https://example.com/image.png)`,
    );
    expect(screen.getByRole("checkbox")).not.toBeChecked();
  },
);

it.each(["browser", "desktop"])(
  "restores writing after route navigation in the %s router",
  async (mode) => {
    const originalUrl = window.location.pathname + window.location.search;
    window.history.replaceState({}, "", "/write");
    const routes = (
      <Routes>
        <Route
          path="/write"
          element={
            <>
              <Link to="/other">Leave editor</Link>
              <PostComposer
                onClose={() => {}}
                initialType="discussion"
                presentation="page"
              />
            </>
          }
        />
        <Route
          path="/other"
          element={<Link to="/write">Return to editor</Link>}
        />
      </Routes>
    );
    try {
      render(
        mode === "desktop" ? (
          <MemoryRouter initialEntries={["/write"]}>{routes}</MemoryRouter>
        ) : (
          <BrowserRouter>{routes}</BrowserRouter>
        ),
      );
      fireEvent.change(
        await screen.findByLabelText("communityCompose.postTitle"),
        { target: { value: "Unsaved title" } },
      );
      fireEvent.change(screen.getByLabelText("communityCompose.body"), {
        target: { value: "Unsaved body" },
      });
      fireEvent.click(
        screen.getByRole("button", { name: "communityAssist.assist" }),
      );
      fireEvent.click(
        await screen.findByRole("button", { name: "Simulate reply" }),
      );
      fireEvent.click(screen.getByRole("link", { name: "Leave editor" }));
      expect(
        screen.queryByLabelText("communityCompose.body"),
      ).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("link", { name: "Return to editor" }));
      await waitFor(() =>
        expect(screen.getByLabelText("communityCompose.body")).toHaveValue(
          "Unsaved body",
        ),
      );
      expect(screen.getByLabelText("communityCompose.postTitle")).toHaveValue(
        "Unsaved title",
      );
      expect(
        await screen.findByText("Remember this reply"),
      ).toBeInTheDocument();
    } finally {
      window.history.replaceState({}, "", originalUrl);
    }
  },
);

it("keeps unsaved cloud-draft edits when returning instead of fetching stale cloud content", async () => {
  vi.mocked(request).mockImplementation(async (path) =>
    String(path).startsWith("/community/drafts/cloud?")
      ? ({
          id: "cloud",
          title: "Cloud title",
          content: "Cloud body",
          type: "discussion",
          resources: [],
          editable: true,
        } as never)
      : ({ resources: [] } as never),
  );
  const first = render(
    <PostComposer
      onClose={() => {}}
      draftId="cloud"
      initialType="discussion"
    />,
  );
  await waitFor(() =>
    expect(screen.getByLabelText("communityCompose.body")).toHaveValue(
      "Cloud body",
    ),
  );
  fireEvent.change(screen.getByLabelText("communityCompose.body"), {
    target: { value: "Unsaved revision" },
  });
  first.unmount();
  render(
    <PostComposer
      onClose={() => {}}
      draftId="cloud"
      initialType="discussion"
    />,
  );
  await waitFor(() =>
    expect(screen.getByLabelText("communityCompose.body")).toHaveValue(
      "Unsaved revision",
    ),
  );
  expect(
    vi
      .mocked(request)
      .mock.calls.filter(([path]) =>
        String(path).startsWith("/community/drafts/cloud?"),
      ),
  ).toHaveLength(1);
});

it("does not restore another community account's writing session", async () => {
  const first = render(
    <PostComposer onClose={() => {}} initialType="discussion" />,
  );
  fireEvent.change(await screen.findByLabelText("communityCompose.body"), {
    target: { value: "Alice's private text" },
  });
  first.unmount();
  vi.mocked(communityConnectionApi.status).mockResolvedValue({
    status: "connected",
    account: { id: "b", display_name: "Bob" },
    sync_enabled: true,
    messages_enabled: true,
  });
  render(<PostComposer onClose={() => {}} initialType="discussion" />);
  expect(await screen.findByLabelText("communityCompose.body")).toHaveValue("");
  expect(screen.queryByText("Alice's private text")).not.toBeInTheDocument();
});
