import { describe, expect, it } from "vitest";
import type { CheckpointNode } from "@/api/types/checkpoints";
import { buildGraphRows } from "./graphLayout";

const node = (
  commit: string,
  parent_commit: string | null,
): CheckpointNode => ({
  ref: `refs/auto/s/${commit}`,
  kind: "auto",
  session_key: "s",
  name: commit,
  commit,
  sha: commit,
  timestamp_ms: 0,
  subject: commit,
  query: null,
  channel: "console",
  restore_index: null,
  parent_commit,
  is_head: false,
  user_id: "u",
  session_id: "s",
  session_title: "Session title",
});

describe("buildGraphRows", () => {
  it("keeps a linear history in one lane", () => {
    const rows = buildGraphRows([
      node("c3", "c2"),
      node("c2", "c1"),
      node("c1", null),
    ]);
    expect(rows.map((row) => row.lane)).toEqual([0, 0, 0]);
  });

  it("joins a restored branch back to an existing ancestor lane", () => {
    const rows = buildGraphRows([
      node("new", "base"),
      node("old", "base"),
      node("base", null),
    ]);
    expect(rows[0].lane).toBe(0);
    expect(rows[1].lane).toBe(1);
    expect(rows[1].parentLane).toBe(0);
  });
});
