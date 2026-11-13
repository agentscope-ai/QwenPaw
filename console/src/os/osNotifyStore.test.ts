import { beforeEach, describe, expect, it } from "vitest";
import { useOsNotify, type OsNotifyItem } from "./osNotifyStore";

function inboxItem(index: number): OsNotifyItem {
  return {
    id: `ib:${index}`,
    kind: "inbox",
    title: `Inbox ${index}`,
    body: "",
    createdAt: index,
    read: false,
  };
}

beforeEach(() => {
  useOsNotify.setState({
    history: [],
    toasts: [],
    approvalCount: 0,
    inboxCount: 0,
    centerOpen: false,
    seeded: false,
    knownIds: new Set<string>(),
    communityScope: undefined,
  });
});

describe("osNotifyStore", () => {
  it("replaces only community account history and silently seeds the new account", () => {
    const old = {
      ...inboxItem(1),
      id: "ib:community:alice",
      sourceType: "community",
    };
    const local = { ...inboxItem(2), sourceType: "cron" };
    const baseline = {
      ...inboxItem(3),
      id: "ib:community:bob",
      sourceType: "community",
    };
    useOsNotify.setState({
      seeded: true,
      communityScope: "alice-scope",
      knownIds: new Set([old.id, local.id]),
      history: [old, local],
      toasts: [old, local],
    });
    useOsNotify.getState().ingest([], [baseline, local], 2, "bob-scope");
    expect(useOsNotify.getState().history).toEqual([local]);
    expect(useOsNotify.getState().toasts).toEqual([local]);
    expect(useOsNotify.getState().knownIds.has(baseline.id)).toBe(true);
    expect(useOsNotify.getState().knownIds.has(old.id)).toBe(false);
    const fresh = { ...baseline, id: "ib:community:bob-new" };
    useOsNotify.getState().ingest([], [fresh, baseline, local], 3, "bob-scope");
    expect(useOsNotify.getState().toasts[0].id).toBe(fresh.id);
  });

  it("preserves unknown community state and clears only a confirmed disconnect", () => {
    const community = { ...inboxItem(1), sourceType: "community" };
    const local = { ...inboxItem(2), sourceType: "cron" };
    useOsNotify.setState({
      seeded: true,
      communityScope: "alice-scope",
      knownIds: new Set([local.id]),
      history: [community, local],
      toasts: [community, local],
    });
    useOsNotify.getState().ingest([], [local], 1, undefined);
    expect(useOsNotify.getState().history).toEqual([community, local]);
    expect(useOsNotify.getState().communityScope).toBe("alice-scope");
    useOsNotify.getState().ingest([], [local], 1, null);
    expect(useOsNotify.getState().history).toEqual([local]);
    expect(useOsNotify.getState().communityScope).toBeNull();
  });
  it("clears only community history and toasts when a community account is unbound", () => {
    const community = { ...inboxItem(1), sourceType: "community" };
    const cron = { ...inboxItem(2), sourceType: "cron" };
    useOsNotify.setState({
      history: [community, cron],
      toasts: [community, cron],
    });
    useOsNotify.getState().applyInboxChange({ clearSources: ["community"] });
    expect(useOsNotify.getState().history).toEqual([cron]);
    expect(useOsNotify.getState().toasts).toEqual([cron]);
  });

  it("applies scoped read-all to community and removes only read community toasts", () => {
    const community = { ...inboxItem(1), sourceType: "community" };
    const cron = { ...inboxItem(2), sourceType: "cron" };
    useOsNotify.setState({
      history: [community, cron],
      toasts: [community, cron],
    });
    useOsNotify
      .getState()
      .applyInboxChange({ readAll: true, sourceTypes: ["community"] });
    expect(useOsNotify.getState().history[0].read).toBe(true);
    expect(useOsNotify.getState().history[1].read).toBe(false);
    expect(useOsNotify.getState().toasts).toEqual([cron]);
  });
  it("uses the exact inbox count returned by the backend", () => {
    useOsNotify.getState().ingest([], [inboxItem(1)], 42);
    expect(useOsNotify.getState().inboxCount).toBe(42);
  });

  it("caps remembered inbox ids while retaining active approvals", () => {
    const approval: OsNotifyItem = {
      id: "ap:active",
      kind: "approval",
      title: "Approval",
      body: "",
      createdAt: 1,
      read: false,
    };
    const knownIds = new Set(
      Array.from({ length: 600 }, (_, index) => `ib:old-${index}`),
    );
    useOsNotify.setState({ seeded: true, knownIds });

    useOsNotify.getState().ingest([approval], [inboxItem(1)]);

    const next = useOsNotify.getState().knownIds;
    expect(next.has("ap:active")).toBe(true);
    expect([...next].filter((id) => id.startsWith("ib:"))).toHaveLength(500);
  });
});
