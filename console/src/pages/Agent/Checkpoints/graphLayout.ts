import type { CheckpointNode } from "@/api/types/checkpoints";

export interface GraphRow {
  node: CheckpointNode;
  lane: number;
  lanesBefore: Array<string | null>;
  lanesAfter: Array<string | null>;
  parentLane: number | null;
}

/** Build a top-to-bottom Git lane layout from newest-first commits. */
export function buildGraphRows(nodes: CheckpointNode[]): GraphRow[] {
  const lanes: Array<string | null> = [];
  const rows: GraphRow[] = [];

  for (const node of nodes) {
    let lane = lanes.indexOf(node.commit);
    if (lane < 0) {
      lane = lanes.indexOf(null);
      if (lane < 0) lane = lanes.length;
      lanes[lane] = node.commit;
    }

    const before = [...lanes];
    let parentLane: number | null = null;
    if (node.parent_commit) {
      const existingParent = lanes.indexOf(node.parent_commit);
      if (existingParent >= 0 && existingParent !== lane) {
        parentLane = existingParent;
        lanes[lane] = null;
      } else {
        parentLane = lane;
        lanes[lane] = node.parent_commit;
      }
    } else {
      lanes[lane] = null;
    }

    while (lanes.length && lanes[lanes.length - 1] === null) lanes.pop();
    rows.push({
      node,
      lane,
      lanesBefore: before,
      lanesAfter: [...lanes],
      parentLane,
    });
  }

  return rows;
}

export function graphLaneCount(rows: GraphRow[]): number {
  return Math.max(
    1,
    ...rows.map((row) =>
      Math.max(row.lanesBefore.length, row.lanesAfter.length, row.lane + 1),
    ),
  );
}
