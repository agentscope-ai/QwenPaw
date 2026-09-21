import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, it, expect, vi } from "vitest";
import { PostComposer } from "./PostComposer";
import { communityConnectionApi } from "@/api/modules/community";
import { request } from "@/api/request";
vi.mock("@/api/modules/community", () => ({
  communityConnectionApi: { status: vi.fn(), start: vi.fn() },
}));
vi.mock("@/api/request", () => ({ request: vi.fn() }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
beforeEach(() => {
  vi.clearAllMocks();
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
