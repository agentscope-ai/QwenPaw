import type { GraphEdge, GraphNode } from "./api";

export interface PositionedNode extends GraphNode {
  x: number;
  y: number;
}

const ZONE_ORDER = ["metadata", "trace", "knowledge", "unknown"];

export function layoutGraph(
  nodes: GraphNode[],
  edges: GraphEdge[],
  width: number,
  height: number,
): PositionedNode[] {
  if (nodes.length === 0) return [];
  const safeWidth = Math.max(width, 480);
  const safeHeight = Math.max(height, 360);
  const byZone = new Map<string, GraphNode[]>();
  for (const node of nodes) {
    const zone = node.zone || "unknown";
    const group = byZone.get(zone) ?? [];
    group.push(node);
    byZone.set(zone, group);
  }

  const degree = new Map<string, number>();
  for (const edge of edges) {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
  }

  const zones = [...byZone.keys()].sort((left, right) => {
    const leftIndex = ZONE_ORDER.indexOf(left);
    const rightIndex = ZONE_ORDER.indexOf(right);
    return (
      (leftIndex < 0 ? 99 : leftIndex) - (rightIndex < 0 ? 99 : rightIndex)
    );
  });
  const columns = Math.min(zones.length, 3);
  const rows = Math.ceil(zones.length / columns);
  const cellWidth = safeWidth / columns;
  const cellHeight = safeHeight / rows;
  const positioned: PositionedNode[] = [];

  zones.forEach((zone, zoneIndex) => {
    const group = [...(byZone.get(zone) ?? [])].sort(
      (left, right) => (degree.get(right.id) ?? 0) - (degree.get(left.id) ?? 0),
    );
    const centerX = ((zoneIndex % columns) + 0.5) * cellWidth;
    const centerY = (Math.floor(zoneIndex / columns) + 0.5) * cellHeight;
    const radius = Math.max(
      50,
      Math.min(cellWidth, cellHeight) * (group.length > 12 ? 0.42 : 0.34),
    );
    group.forEach((node, index) => {
      if (index === 0) {
        positioned.push({ ...node, x: centerX, y: centerY });
        return;
      }
      const ring = Math.floor(Math.sqrt(index));
      const ringStart = ring * ring;
      const ringSize = Math.max(6, ring * 7);
      const angle =
        ((index - ringStart) / ringSize) * Math.PI * 2 - Math.PI / 2;
      const distance = Math.min(radius, radius * (0.42 + ring * 0.24));
      positioned.push({
        ...node,
        x: centerX + Math.cos(angle) * distance,
        y: centerY + Math.sin(angle) * distance,
      });
    });
  });

  return positioned;
}

export function compactLabel(value: string, maxLength = 22): string {
  if (value.length <= maxLength) return value;
  const side = Math.max(5, Math.floor((maxLength - 1) / 2));
  return `${value.slice(0, side)}…${value.slice(-side)}`;
}
