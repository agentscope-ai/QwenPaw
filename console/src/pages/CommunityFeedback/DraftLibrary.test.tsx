import { render, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { DraftLibrary } from "./DraftLibrary";

const listPostDrafts = vi.hoisted(() => vi.fn());
vi.mock("./postDrafts", () => ({
  listPostDrafts: (...args: unknown[]) => listPostDrafts(...args),
  removePostDraft: vi.fn(),
  savePostDraft: vi.fn(),
}));
vi.mock("./legacyPostDrafts", () => ({
  listPostDrafts: vi.fn(() => []),
}));
vi.mock("@/api/modules/community", () => ({
  communityConnectionApi: {
    status: vi.fn(() =>
      Promise.resolve({ status: "connected", account: { id: "alice" } }),
    ),
  },
}));

const articleDraft = {
  id: "d1",
  title: "Hangzhou",
  summary: "First line of the saved article body.",
  type: "beginner_tutorial",
  updatedAt: 0,
  resources: [],
};
const questionDraft = {
  id: "d2",
  title: "Why does it fail",
  summary: "First line of the saved question body.",
  type: "question",
  updatedAt: 0,
  resources: [],
};

beforeEach(() => {
  listPostDrafts.mockReset();
  listPostDrafts.mockResolvedValue({
    items: [articleDraft, questionDraft],
    total: 2,
  });
});

it("lists article and question drafts together with a one-line preview", async () => {
  const { container, findByText } = render(
    <DraftLibrary onOpen={() => {}} onBack={() => {}} />,
  );
  // No type filter: every draft (article + question) lands in one list.
  await waitFor(() => expect(listPostDrafts).toHaveBeenCalledWith("alice", 1));
  expect(await findByText("Hangzhou")).toBeTruthy();
  expect(await findByText("Why does it fail")).toBeTruthy();
  // The Platform list only carries `summary`; it renders as the preview.
  expect(
    await findByText("First line of the saved article body."),
  ).toBeTruthy();
  expect(
    await findByText("First line of the saved question body."),
  ).toBeTruthy();
  // No article/question tab switch is rendered.
  expect(container.querySelectorAll(".ant-segmented-item")).toHaveLength(0);
});
