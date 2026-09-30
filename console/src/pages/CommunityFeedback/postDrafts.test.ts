import { beforeEach, expect, it, vi } from "vitest";
import {
  listPostDrafts,
  removePostDraft,
  savePostDraft,
} from "./legacyPostDrafts";

const content = {
  title: "Draft",
  content: "# Notes",
  type: "discussion",
  resources: [],
};
beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});
it("persists multiple drafts per account and updates the selected draft", () => {
  const first = savePostDraft("alice", content);
  savePostDraft("alice", { ...content, title: "Second" });
  savePostDraft("alice", { ...content, content: "Revised" }, first.id);
  expect(listPostDrafts("alice")).toHaveLength(2);
  expect(
    listPostDrafts("alice").find((item) => item.id === first.id)?.content,
  ).toBe("Revised");
  expect(listPostDrafts("bob")).toEqual([]);
  removePostDraft("bob", first.id);
  expect(listPostDrafts("alice")).toHaveLength(2);
  removePostDraft("alice", first.id);
  expect(listPostDrafts("alice")).toHaveLength(1);
});
it("preserves the previous draft when storage is full", () => {
  const draft = savePostDraft("alice", content);
  vi.spyOn(localStorage, "setItem").mockImplementationOnce(() => {
    throw new DOMException("Full", "QuotaExceededError");
  });
  expect(() =>
    savePostDraft("alice", { ...content, content: "New" }, draft.id),
  ).toThrow();
  expect(listPostDrafts("alice")[0].content).toBe(content.content);
});
it("does not overwrite unreadable stored drafts", () => {
  localStorage.setItem("qwenpaw.community.drafts.v1:alice", "broken");
  expect(() => savePostDraft("alice", content)).toThrow();
  expect(localStorage.getItem("qwenpaw.community.drafts.v1:alice")).toBe(
    "broken",
  );
});
