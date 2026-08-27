import { describe, expect, it } from "vitest";

import { compactLabel, layoutGraph } from "./graph-layout";

describe("layoutGraph", () => {
  it("returns one finite position for every node", () => {
    const nodes = [
      { id: "a", label: "A", type: "Metric", zone: "metadata", properties: {} },
      { id: "b", label: "B", type: "Task", zone: "trace", properties: {} },
      {
        id: "c",
        label: "C",
        type: "Entity",
        zone: "knowledge",
        properties: {},
      },
    ];
    const result = layoutGraph(nodes, [], 900, 600);
    expect(result).toHaveLength(3);
    expect(
      result.every(
        (node) => Number.isFinite(node.x) && Number.isFinite(node.y),
      ),
    ).toBe(true);
  });

  it("compacts long labels without hiding both ends", () => {
    expect(compactLabel("metadata:orders:net_revenue", 15)).toBe(
      "metadat…revenue",
    );
  });
});
