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
  });
});

describe("osNotifyStore", () => {
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
