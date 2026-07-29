import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useProjectDraft } from "@/lib/useProjectDraft";

interface ExampleDocument {
  label: string;
  creation: {
    text: string;
    references: string[];
  };
}

const authority = (): ExampleDocument => ({
  label: "原名称",
  creation: {
    text: "原文案",
    references: ["asset-v1"],
  },
});

describe("useProjectDraft", () => {
  it("keeps edits local and builds one CAS operation per changed field", () => {
    const { result } = renderHook(() =>
      useProjectDraft(authority(), "element:one", [
        "timelines",
        "items",
        "main",
        "elements_by_id",
        "one",
      ]),
    );

    act(() => {
      result.current.update((draft) => {
        draft.label = "新名称";
        draft.creation.text = "新文案";
      });
    });

    expect(result.current.dirty).toBe(true);
    expect(result.current.dirtyCount).toBe(2);
    expect(result.current.operations).toEqual([
      {
        op: "replace",
        path: "/timelines/items/main/elements_by_id/one/creation/text",
        before: "原文案",
        value: "新文案",
      },
      {
        op: "replace",
        path: "/timelines/items/main/elements_by_id/one/label",
        before: "原名称",
        value: "新名称",
      },
    ]);
  });

  it("discards every staged field back to the authoritative baseline", () => {
    const source = authority();
    const { result } = renderHook(() =>
      useProjectDraft(source, "element:one", ["elements", "one"]),
    );

    act(() => {
      result.current.update((draft) => {
        draft.creation.references = ["asset-v2"];
      });
    });
    expect(result.current.operations).toEqual([
      {
        op: "replace",
        path: "/elements/one/creation/references",
        before: ["asset-v1"],
        value: ["asset-v2"],
      },
    ]);

    act(() => result.current.discard());

    expect(result.current.value).toEqual(source);
    expect(result.current.dirty).toBe(false);
    expect(result.current.operations).toEqual([]);
  });

  it("merges disjoint polling updates while preserving local dirty fields", () => {
    const source = authority();
    const { result, rerender } = renderHook(
      ({ current }) =>
        useProjectDraft(current, "element:one", ["elements", "one"]),
      { initialProps: { current: source } },
    );

    act(() => {
      result.current.update((draft) => {
        draft.label = "我的名称";
      });
    });
    const remote = authority();
    remote.creation.text = "Agent 更新的文案";
    rerender({ current: remote });

    expect(result.current.value).toEqual({
      ...remote,
      label: "我的名称",
    });
    expect(result.current.conflictPaths).toEqual([]);
    expect(result.current.operations[0]).toMatchObject({
      path: "/elements/one/label",
      before: "原名称",
      value: "我的名称",
    });
  });

  it("flags overlapping authority updates before allowing an overwrite", () => {
    const source = authority();
    const { result, rerender } = renderHook(
      ({ current }) =>
        useProjectDraft(current, "element:one", ["elements", "one"]),
      { initialProps: { current: source } },
    );

    act(() => {
      result.current.update((draft) => {
        draft.label = "我的名称";
      });
    });
    const remote = authority();
    remote.label = "Agent 的名称";
    rerender({ current: remote });

    expect(result.current.value.label).toBe("我的名称");
    expect(result.current.conflictPaths).toEqual(["/label"]);
    expect(result.current.operations[0]).toMatchObject({
      before: "Agent 的名称",
      value: "我的名称",
    });

    act(() => result.current.acceptConflicts());
    expect(result.current.conflictPaths).toEqual([]);
  });
});
