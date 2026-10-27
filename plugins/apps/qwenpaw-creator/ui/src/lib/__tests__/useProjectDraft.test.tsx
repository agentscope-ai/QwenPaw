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

const renderDraft = (source: ExampleDocument) =>
  renderHook(
    ({ current }) =>
      useProjectDraft(current, "element:one", ["elements", "one"]),
    { initialProps: { current: source } },
  );

type Rendered = ReturnType<typeof renderDraft>["result"];
const edit = (result: Rendered, fn: (draft: ExampleDocument) => void) =>
  act(() => result.current.update(fn));

describe("useProjectDraft", () => {
  it("keeps edits local and builds one CAS operation per changed field", () => {
    const { result } = renderDraft(authority());

    edit(result, (draft) => {
      draft.label = "新名称";
      draft.creation.text = "新文案";
    });

    expect(result.current.dirty).toBe(true);
    expect(result.current.dirtyCount).toBe(2);
    expect(result.current.operations).toEqual([
      {
        op: "replace",
        path: "/elements/one/creation/text",
        before: "原文案",
        value: "新文案",
      },
      {
        op: "replace",
        path: "/elements/one/label",
        before: "原名称",
        value: "新名称",
      },
    ]);
  });

  it("discards every staged field back to the authoritative baseline", () => {
    const source = authority();
    const { result } = renderDraft(source);

    edit(result, (draft) => {
      draft.creation.references = ["asset-v2"];
    });
    expect(result.current.dirty).toBe(true);

    act(() => result.current.discard());

    expect(result.current.value).toEqual(source);
    expect(result.current.dirty).toBe(false);
    expect(result.current.operations).toEqual([]);
  });

  it("merges disjoint polling updates and flags overlapping ones before allowing an overwrite", () => {
    const { result, rerender } = renderDraft(authority());

    edit(result, (draft) => {
      draft.label = "我的名称";
    });
    const remote = authority();
    remote.creation.text = "Agent 更新的文案";
    rerender({ current: remote });

    expect(result.current.value).toEqual({ ...remote, label: "我的名称" });
    expect(result.current.conflictPaths).toEqual([]);

    const overlapping = authority();
    overlapping.label = "Agent 的名称";
    rerender({ current: overlapping });

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
