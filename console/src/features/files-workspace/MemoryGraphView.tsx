import {
  CircleAlert,
  ExternalLink,
  Link2,
  LoaderCircle,
  Maximize2,
  RefreshCw,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { useTranslation } from "react-i18next";
import { agentsApi } from "../../api/modules/agents";
import type {
  MemoryGraphEdge,
  MemoryGraphNode,
  MemoryGraphSnapshot,
} from "../../api/types";
import type { MemorySection } from "../../api/types/workspace";
import type { MemoryGraphRoot } from "./types";
import styles from "./MemoryGraphView.module.less";

interface PositionedNode extends MemoryGraphNode {
  degree: number;
  layer: 0 | 1 | 2;
  x: number;
  y: number;
  radius: number;
}

interface GraphLabel {
  id: string;
  text: string;
  width: number;
  x: number;
  y: number;
}

interface PositionedGraph {
  nodes: PositionedNode[];
  byId: Map<string, PositionedNode>;
  labels: GraphLabel[];
}

interface NodeOffset {
  x: number;
  y: number;
}

interface DragSession {
  baseOffsets: Record<string, NodeOffset>;
  followers: Map<string, number>;
  pointerId: number;
  start: NodeOffset;
}

const GRAPH_WIDTH = 1080;
const GRAPH_HEIGHT = 680;
const GRAPH_PADDING = 54;
const INNER_RING_RADIUS = 164;
const OUTER_RING_RADIUS = GRAPH_HEIGHT / 2 - GRAPH_PADDING - 16;

function nodeLabel(node: MemoryGraphNode): string {
  return (
    node.name || node.path.split("/").pop()?.replace(/\.md$/i, "") || node.path
  );
}

function shortLabel(node: MemoryGraphNode): string {
  const label = nodeLabel(node);
  if (/^[a-f\d]{24,}$/i.test(label))
    return `${label.slice(0, 7)}…${label.slice(-4)}`;
  return label.length > 25 ? `${label.slice(0, 22)}…` : label;
}

function nodeFileTarget(
  node: MemoryGraphNode,
): { section: MemorySection; path: string } | null {
  if (!node.indexed || node.virtual) return null;
  if (node.section && node.relative_path) {
    return { section: node.section, path: node.relative_path };
  }

  // Older graph endpoints did not include navigation metadata. Keep the
  // standard ReMe/QwenPaw roots openable while the backend is being upgraded.
  const normalizedPath = node.path.replace(/\\/g, "/").replace(/^\/+/, "");
  const conventionalRoots: Array<[MemorySection, string]> = [
    ["digest", "digest/"],
    ["daily", "memory/"],
    ["daily", "daily/"],
  ];
  for (const [section, prefix] of conventionalRoots) {
    if (normalizedPath.startsWith(prefix)) {
      return { section, path: normalizedPath.slice(prefix.length) };
    }
  }
  return null;
}

function graphDegrees(snapshot: MemoryGraphSnapshot): Map<string, number> {
  const degree = new Map(snapshot.nodes.map((node) => [node.id, 0]));
  snapshot.edges.forEach((edge) => {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
  });
  return degree;
}

function graphBelowRoot(
  snapshot: MemoryGraphSnapshot,
  root: MemoryGraphRoot,
): MemoryGraphSnapshot {
  const rootNode = snapshot.nodes.find(
    (node) =>
      node.id === `virtual:${root}` || (node.virtual && node.name === root),
  );
  if (!rootNode) return { ...snapshot, nodes: [], edges: [] };
  const outgoing = new Map<string, string[]>();
  snapshot.edges.forEach((edge) => {
    outgoing.set(edge.source, [
      ...(outgoing.get(edge.source) ?? []),
      edge.target,
    ]);
  });
  const reachable = new Set([rootNode.id]);
  const queue = [rootNode.id];
  while (queue.length > 0) {
    const current = queue.shift() as string;
    (outgoing.get(current) ?? []).forEach((target) => {
      if (reachable.has(target)) return;
      reachable.add(target);
      queue.push(target);
    });
  }
  return {
    ...snapshot,
    nodes: snapshot.nodes
      .filter((node) => reachable.has(node.id))
      .map((node) =>
        node.id === rootNode.id ? { ...node, virtual: true } : node,
      ),
    edges: snapshot.edges.filter(
      (edge) => reachable.has(edge.source) && reachable.has(edge.target),
    ),
  };
}

function downstreamFollowers(
  rootId: string,
  snapshot: MemoryGraphSnapshot,
): Map<string, number> {
  const outgoing = new Map<string, string[]>();
  snapshot.edges.forEach((edge) => {
    outgoing.set(edge.source, [
      ...(outgoing.get(edge.source) ?? []),
      edge.target,
    ]);
  });
  const followers = new Map<string, number>([[rootId, 1]]);
  const queue: Array<{ id: string; depth: number }> = [
    { id: rootId, depth: 0 },
  ];
  while (queue.length > 0) {
    const current = queue.shift() as { id: string; depth: number };
    (outgoing.get(current.id) ?? []).forEach((target) => {
      if (followers.has(target)) return;
      const depth = current.depth + 1;
      followers.set(target, Math.max(0.2, 0.68 ** depth));
      queue.push({ id: target, depth });
    });
  }
  return followers;
}

function pointerGraphPosition(
  event: ReactPointerEvent<SVGGElement>,
  zoom: number,
): NodeOffset {
  const bounds = event.currentTarget.ownerSVGElement?.getBoundingClientRect();
  if (!bounds || bounds.width === 0 || bounds.height === 0) {
    return { x: event.clientX, y: event.clientY };
  }
  const viewX = ((event.clientX - bounds.left) / bounds.width) * GRAPH_WIDTH;
  const viewY = ((event.clientY - bounds.top) / bounds.height) * GRAPH_HEIGHT;
  return {
    x: GRAPH_WIDTH / 2 + (viewX - GRAPH_WIDTH / 2) / zoom,
    y: GRAPH_HEIGHT / 2 + (viewY - GRAPH_HEIGHT / 2) / zoom,
  };
}

/** Lay out the category tree in stable, parent-owned radial sectors. */
function layoutGraph(snapshot: MemoryGraphSnapshot): PositionedGraph {
  const degree = graphDegrees(snapshot);
  const root =
    snapshot.nodes.find((node) => node.virtual) ??
    snapshot.nodes.find((node) => node.id.startsWith("virtual:")) ??
    snapshot.nodes[0];
  const nodes: PositionedNode[] = snapshot.nodes.map((node) => {
    const itemDegree = degree.get(node.id) ?? 0;
    return {
      ...node,
      virtual: node.id === root?.id ? true : node.virtual,
      degree: itemDegree,
      layer: node.id === root?.id ? 0 : 2,
      x: GRAPH_WIDTH / 2,
      y: GRAPH_HEIGHT / 2,
      radius:
        node.id === root?.id || node.virtual
          ? 11
          : node.indexed
          ? Math.min(9, 4 + Math.sqrt(itemDegree) * 1.35)
          : 4,
    };
  });
  const nodeById = new Map(nodes.map((node) => [node.id, node]));

  if (root) {
    const outgoing = new Map<string, string[]>();
    snapshot.edges.forEach((edge) => {
      if (!nodeById.has(edge.source) || !nodeById.has(edge.target)) return;
      outgoing.set(edge.source, [
        ...(outgoing.get(edge.source) ?? []),
        edge.target,
      ]);
    });
    const inner = [...new Set(outgoing.get(root.id) ?? [])]
      .filter((id) => id !== root.id && nodeById.has(id))
      .sort(
        (left, right) =>
          (degree.get(right) ?? 0) - (degree.get(left) ?? 0) ||
          left.localeCompare(right),
      );
    const innerSet = new Set(inner);
    const outer = nodes
      .filter((node) => node.id !== root.id && !innerSet.has(node.id))
      .map((node) => node.id);
    const startAngle = -Math.PI / 2;
    const innerAngles = new Map<string, number>();
    inner.forEach((id, index) => {
      const angle =
        startAngle + (index / Math.max(1, inner.length)) * Math.PI * 2;
      innerAngles.set(id, angle);
      const node = nodeById.get(id);
      if (!node) return;
      node.layer = 1;
      node.x = GRAPH_WIDTH / 2 + Math.cos(angle) * INNER_RING_RADIUS;
      node.y = GRAPH_HEIGHT / 2 + Math.sin(angle) * INNER_RING_RADIUS;
    });

    // Assign every outer node to its nearest inner branch for stable ordering.
    // The final positions still use equal angular spacing on the outer ring.
    const branchOwner = new Map(inner.map((id) => [id, id]));
    const branchQueue = [...inner];
    while (branchQueue.length > 0) {
      const current = branchQueue.shift() as string;
      (outgoing.get(current) ?? []).forEach((target) => {
        if (target === root.id || branchOwner.has(target)) return;
        branchOwner.set(target, branchOwner.get(current) as string);
        branchQueue.push(target);
      });
    }
    outer.sort((left, right) => {
      const leftOwnerAngle = innerAngles.get(branchOwner.get(left) ?? "");
      const rightOwnerAngle = innerAngles.get(branchOwner.get(right) ?? "");
      const normalized = (angle: number | undefined) =>
        angle === undefined
          ? Number.POSITIVE_INFINITY
          : (angle - startAngle + Math.PI * 2) % (Math.PI * 2);
      return (
        normalized(leftOwnerAngle) - normalized(rightOwnerAngle) ||
        (degree.get(right) ?? 0) - (degree.get(left) ?? 0) ||
        left.localeCompare(right)
      );
    });
    outer.forEach((id, index) => {
      const angle =
        startAngle + (index / Math.max(1, outer.length)) * Math.PI * 2;
      const node = nodeById.get(id);
      if (!node) return;
      node.layer = 2;
      node.x = GRAPH_WIDTH / 2 + Math.cos(angle) * OUTER_RING_RADIUS;
      node.y = GRAPH_HEIGHT / 2 + Math.sin(angle) * OUTER_RING_RADIUS;
    });
  }

  const labelLimit = Math.min(
    10,
    Math.max(5, Math.ceil(Math.sqrt(nodes.length) * 1.5)),
  );
  const occupied: Array<{
    left: number;
    right: number;
    top: number;
    bottom: number;
  }> = [];
  const labels: GraphLabel[] = [];
  const labelCandidates = [...nodes].sort(
    (left, right) =>
      Number(Boolean(right.virtual)) - Number(Boolean(left.virtual)) ||
      right.degree - left.degree ||
      left.id.localeCompare(right.id),
  );
  labelCandidates.slice(0, labelLimit * 2).forEach((node) => {
    if (labels.length >= labelLimit) return;
    const text = shortLabel(node);
    const width = Math.min(176, text.length * 6.4 + 14);
    const placements = [node.y + node.radius + 18, node.y - node.radius - 10];
    const y = placements.find((candidateY) => {
      const box = {
        left: node.x - width / 2,
        right: node.x + width / 2,
        top: candidateY - 12,
        bottom: candidateY + 3,
      };
      return !occupied.some(
        (other) =>
          box.left < other.right &&
          box.right > other.left &&
          box.top < other.bottom &&
          box.bottom > other.top,
      );
    });
    if (y === undefined) return;
    occupied.push({
      left: node.x - width / 2,
      right: node.x + width / 2,
      top: y - 12,
      bottom: y + 3,
    });
    labels.push({ id: node.id, text, width, x: node.x, y });
  });

  const positioned: PositionedNode[] = nodes.map((node) => ({
    id: node.id,
    path: node.path,
    name: node.name,
    description: node.description,
    indexed: node.indexed,
    virtual: node.virtual,
    degree: node.degree,
    layer: node.layer,
    x: node.x,
    y: node.y,
    radius: node.radius,
  }));
  return {
    nodes: positioned,
    byId: new Map(positioned.map((node) => [node.id, node])),
    labels,
  };
}

function edgePath(
  edge: MemoryGraphEdge,
  graph: PositionedGraph,
  reciprocalEdges: Set<string>,
): string {
  const source = graph.byId.get(edge.source);
  const target = graph.byId.get(edge.target);
  if (!source || !target) return "";
  const dx = target.x - source.x;
  const dy = target.y - source.y;
  const distance = Math.max(1, Math.hypot(dx, dy));
  const startX = source.x + (dx / distance) * (source.radius + 2);
  const startY = source.y + (dy / distance) * (source.radius + 2);
  const endX = target.x - (dx / distance) * (target.radius + 6);
  const endY = target.y - (dy / distance) * (target.radius + 6);
  if (!reciprocalEdges.has(`${edge.source}\u0000${edge.target}`)) {
    return `M ${startX} ${startY} L ${endX} ${endY}`;
  }
  const direction = edge.source.localeCompare(edge.target) < 0 ? 1 : -1;
  const curve = 16 * direction;
  const midX = (startX + endX) / 2 - (dy / distance) * curve;
  const midY = (startY + endY) / 2 + (dx / distance) * curve;
  return `M ${startX} ${startY} Q ${midX} ${midY} ${endX} ${endY}`;
}

export default function MemoryGraphView({
  agentId,
  root,
  onOpenFile,
}: {
  agentId: string;
  root: MemoryGraphRoot;
  onOpenFile: (section: MemorySection, path: string) => void;
}) {
  const { t } = useTranslation();
  const [snapshot, setSnapshot] = useState<MemoryGraphSnapshot | null>(null);
  const [snapshotAgentId, setSnapshotAgentId] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [hoveredId, setHoveredId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [offsets, setOffsets] = useState<Record<string, NodeOffset>>({});
  const [draggingId, setDraggingId] = useState("");
  const [draggedIds, setDraggedIds] = useState<string[]>([]);
  const dragSession = useRef<DragSession | null>(null);
  const didDrag = useRef(false);
  const requestSequence = useRef(0);

  const load = useCallback(
    async (clearSnapshot = false) => {
      const sequence = ++requestSequence.current;
      setLoading(true);
      setError(false);
      if (clearSnapshot) {
        setSnapshot(null);
        setSnapshotAgentId("");
      }
      setSelectedId("");
      setOffsets({});
      setZoom(1);
      setDraggingId("");
      setDraggedIds([]);
      dragSession.current = null;
      try {
        const next = await agentsApi.getMemoryGraph(agentId);
        if (sequence !== requestSequence.current) return;
        setSnapshot(next);
        setSnapshotAgentId(agentId);
        setSelectedId((current) =>
          next.nodes.some((node) => node.id === current) ? current : "",
        );
      } catch {
        if (sequence !== requestSequence.current) return;
        setError(true);
      } finally {
        if (sequence === requestSequence.current) setLoading(false);
      }
    },
    [agentId],
  );

  useEffect(() => {
    void load(true);
    return () => {
      requestSequence.current += 1;
    };
  }, [load]);

  useEffect(() => {
    setSelectedId("");
    setHoveredId("");
    setOffsets({});
    setZoom(1);
  }, [root]);

  const currentSnapshot = snapshotAgentId === agentId ? snapshot : null;
  const graphSnapshot = useMemo(
    () => (currentSnapshot ? graphBelowRoot(currentSnapshot, root) : null),
    [currentSnapshot, root],
  );

  const baseGraph = useMemo(
    () => layoutGraph(graphSnapshot ?? { version: 1, nodes: [], edges: [] }),
    [graphSnapshot],
  );
  const graph = useMemo(() => {
    const nodes = baseGraph.nodes.map((node) => ({
      ...node,
      x: node.x + (offsets[node.id]?.x ?? 0),
      y: node.y + (offsets[node.id]?.y ?? 0),
    }));
    return {
      nodes,
      byId: new Map(nodes.map((node) => [node.id, node])),
      labels: baseGraph.labels.map((label) => ({
        ...label,
        x: label.x + (offsets[label.id]?.x ?? 0),
        y: label.y + (offsets[label.id]?.y ?? 0),
      })),
    };
  }, [baseGraph, offsets]);
  const activeId = hoveredId || selectedId;
  const selected = graphSnapshot?.nodes.find((node) => node.id === selectedId);
  const selectedFileTarget = selected ? nodeFileTarget(selected) : null;
  const inbound =
    graphSnapshot?.edges.filter((edge) => edge.target === selectedId) ?? [];
  const outbound =
    graphSnapshot?.edges.filter((edge) => edge.source === selectedId) ?? [];
  const activeNeighbors = useMemo(() => {
    const neighbors = new Set<string>();
    (graphSnapshot?.edges ?? []).forEach((edge) => {
      if (edge.source === activeId) neighbors.add(edge.target);
      if (edge.target === activeId) neighbors.add(edge.source);
    });
    return neighbors;
  }, [activeId, graphSnapshot]);
  const reciprocalEdges = useMemo(() => {
    const keys = new Set(
      (graphSnapshot?.edges ?? []).map(
        (edge) => `${edge.source}\u0000${edge.target}`,
      ),
    );
    return new Set(
      [...keys].filter((key) => {
        const [source, target] = key.split("\u0000");
        return keys.has(`${target}\u0000${source}`);
      }),
    );
  }, [graphSnapshot]);
  const draggedSet = useMemo(() => new Set(draggedIds), [draggedIds]);

  const startDrag = (event: ReactPointerEvent<SVGGElement>, nodeId: string) => {
    if (event.button !== 0 || !graphSnapshot) return;
    event.preventDefault();
    event.stopPropagation();
    const followers = downstreamFollowers(nodeId, graphSnapshot);
    dragSession.current = {
      baseOffsets: { ...offsets },
      followers,
      pointerId: event.pointerId,
      start: pointerGraphPosition(event, zoom),
    };
    didDrag.current = false;
    setDraggingId(nodeId);
    setDraggedIds([...followers.keys()]);
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const moveDrag = (event: ReactPointerEvent<SVGGElement>) => {
    const session = dragSession.current;
    if (!session || session.pointerId !== event.pointerId) return;
    event.preventDefault();
    const pointer = pointerGraphPosition(event, zoom);
    const dx = pointer.x - session.start.x;
    const dy = pointer.y - session.start.y;
    if (Math.hypot(dx, dy) > 2) didDrag.current = true;
    const next = { ...session.baseOffsets };
    session.followers.forEach((factor, id) => {
      const base = session.baseOffsets[id] ?? { x: 0, y: 0 };
      next[id] = { x: base.x + dx * factor, y: base.y + dy * factor };
    });
    setOffsets(next);
  };

  const endDrag = (event: ReactPointerEvent<SVGGElement>) => {
    const session = dragSession.current;
    if (!session || session.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    dragSession.current = null;
    setDraggingId("");
    setDraggedIds([]);
  };

  if (loading && !currentSnapshot) {
    return (
      <div className={styles.state} aria-label={t("files.memoryGraphLoading")}>
        <LoaderCircle className={styles.spin} size={20} />
        {t("files.memoryGraphLoading")}
      </div>
    );
  }

  if (error && !currentSnapshot) {
    return (
      <div className={styles.state} role="alert">
        <CircleAlert size={20} />
        <span>{t("files.memoryGraphLoadFailed")}</span>
        <button type="button" onClick={() => void load()}>
          {t("common.retry")}
        </button>
      </div>
    );
  }

  return (
    <section
      className={styles.graphView}
      data-root={root}
      aria-label={t("files.memoryGraph")}
    >
      <header className={styles.toolbar}>
        <div>
          <strong>
            {t("files.memoryGraph")} · {root}
          </strong>
          <span>
            {t("files.memoryGraphCounts", {
              nodes: graphSnapshot?.nodes.length ?? 0,
              edges: graphSnapshot?.edges.length ?? 0,
            })}
          </span>
        </div>
        <div className={styles.toolbarActions}>
          <button
            type="button"
            onClick={() => setZoom((current) => Math.max(0.7, current - 0.15))}
            aria-label={t("files.memoryGraphZoomOut")}
          >
            <ZoomOut size={15} />
          </button>
          <button
            type="button"
            onClick={() => setZoom((current) => Math.min(1.6, current + 0.15))}
            aria-label={t("files.memoryGraphZoomIn")}
          >
            <ZoomIn size={15} />
          </button>
          <button
            type="button"
            onClick={() => setZoom(1)}
            aria-label={t("files.memoryGraphFit")}
          >
            <Maximize2 size={15} />
          </button>
          <button
            type="button"
            onClick={() => void load()}
            aria-label={t("common.refresh")}
          >
            <RefreshCw className={loading ? styles.spin : ""} size={15} />
          </button>
        </div>
      </header>

      {(graphSnapshot?.nodes.length ?? 0) === 0 ? (
        <div className={styles.state}>
          <Link2 size={20} />
          {t("files.memoryGraphEmpty")}
        </div>
      ) : (
        <div
          className={`${styles.content} ${
            selected ? styles.contentWithDetails : ""
          }`}
        >
          <div className={styles.canvas} onClick={() => setSelectedId("")}>
            <svg viewBox={`0 0 ${GRAPH_WIDTH} ${GRAPH_HEIGHT}`} role="img">
              <title>{t("files.memoryGraph")}</title>
              <defs>
                <marker
                  id="memory-graph-arrow"
                  viewBox="0 0 10 10"
                  refX="9"
                  refY="5"
                  markerWidth="5"
                  markerHeight="5"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 0 L 10 5 L 0 10 z" />
                </marker>
              </defs>
              <g
                transform={`translate(${GRAPH_WIDTH / 2} ${
                  GRAPH_HEIGHT / 2
                }) scale(${zoom}) translate(${-GRAPH_WIDTH / 2} ${
                  -GRAPH_HEIGHT / 2
                })`}
              >
                <g
                  className={styles.orbitGuides}
                  data-testid="memory-graph-orbits"
                  aria-hidden="true"
                >
                  <circle
                    cx={GRAPH_WIDTH / 2}
                    cy={GRAPH_HEIGHT / 2}
                    r={INNER_RING_RADIUS}
                  />
                  {graph.nodes.some((node) => node.layer === 2) && (
                    <circle
                      cx={GRAPH_WIDTH / 2}
                      cy={GRAPH_HEIGHT / 2}
                      r={OUTER_RING_RADIUS}
                    />
                  )}
                </g>
                <g className={styles.edges}>
                  {graphSnapshot?.edges.map((edge) => {
                    const related =
                      edge.source === activeId || edge.target === activeId;
                    return (
                      <path
                        key={`${edge.source}:${edge.target}:${
                          edge.target_anchor ?? ""
                        }`}
                        d={edgePath(edge, graph, reciprocalEdges)}
                        pathLength={1}
                        className={`${related ? styles.edgeActive : ""} ${
                          activeId && !related ? styles.edgeMuted : ""
                        } ${
                          draggingId &&
                          draggedSet.has(edge.source) &&
                          draggedSet.has(edge.target)
                            ? styles.edgeDragging
                            : ""
                        }`}
                        markerEnd="url(#memory-graph-arrow)"
                      >
                        <title>
                          {edge.source} → {edge.target}
                          {edge.target_anchor ? `#${edge.target_anchor}` : ""}
                        </title>
                      </path>
                    );
                  })}
                </g>
                <g className={styles.nodes}>
                  {graph.nodes.map((node, index) => {
                    const active = node.id === activeId;
                    const related = activeNeighbors.has(node.id);
                    const muted = Boolean(activeId) && !active && !related;
                    return (
                      <g
                        key={node.id}
                        className={`${styles.node} ${
                          node.virtual
                            ? styles.nodeRoot
                            : node.indexed
                            ? styles.nodeIndexed
                            : styles.nodeUnresolved
                        } ${node.degree >= 5 ? styles.nodeHub : ""} ${
                          node.degree <= 1 ? styles.nodeLeaf : ""
                        } ${node.layer === 2 ? styles.nodeOuter : ""} ${
                          node.layer === 1 ? styles.nodeInner : ""
                        } ${active ? styles.nodeActive : ""} ${
                          related ? styles.nodeRelated : ""
                        } ${muted ? styles.nodeMuted : ""} ${
                          node.id === draggingId ? styles.nodeDragging : ""
                        } ${
                          draggingId &&
                          node.id !== draggingId &&
                          draggedSet.has(node.id)
                            ? styles.nodeFollowing
                            : ""
                        }`}
                        style={{
                          transform: `translate(${node.x}px, ${node.y}px)`,
                          animationDelay: `${Math.min(index, 24) * 14}ms`,
                        }}
                        role="button"
                        tabIndex={0}
                        aria-label={nodeLabel(node)}
                        onClick={(event) => {
                          event.stopPropagation();
                          if (didDrag.current) {
                            didDrag.current = false;
                            return;
                          }
                          setSelectedId(node.id);
                        }}
                        onPointerDown={(event) => startDrag(event, node.id)}
                        onPointerMove={moveDrag}
                        onPointerUp={endDrag}
                        onPointerCancel={endDrag}
                        onMouseEnter={() => setHoveredId(node.id)}
                        onMouseLeave={() => setHoveredId("")}
                        onFocus={() => setHoveredId(node.id)}
                        onBlur={() => setHoveredId("")}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            setSelectedId(node.id);
                          }
                        }}
                      >
                        <circle
                          className={styles.nodeHalo}
                          r={node.radius + 6}
                        />
                        <circle className={styles.nodeDot} r={node.radius} />
                        <title>{node.path}</title>
                      </g>
                    );
                  })}
                </g>
                <g className={styles.labels}>
                  {graph.labels
                    .filter((label) => label.id !== activeId)
                    .map((label) => (
                      <g
                        key={label.id}
                        style={{
                          transform: `translate(${label.x}px, ${label.y}px)`,
                        }}
                        className={
                          activeId && !activeNeighbors.has(label.id)
                            ? styles.labelMuted
                            : ""
                        }
                      >
                        <rect
                          x={-label.width / 2}
                          y={-13}
                          width={label.width}
                          height={19}
                          rx={6}
                        />
                        <text textAnchor="middle">{label.text}</text>
                      </g>
                    ))}
                  {activeId &&
                    graph.byId.get(activeId) &&
                    (() => {
                      const node = graph.byId.get(activeId) as PositionedNode;
                      const text = shortLabel(node);
                      const width = Math.min(190, text.length * 6.8 + 18);
                      return (
                        <g
                          style={{
                            transform: `translate(${node.x}px, ${
                              node.y + node.radius + 22
                            }px)`,
                          }}
                          className={styles.activeLabel}
                        >
                          <rect
                            x={-width / 2}
                            y={-14}
                            width={width}
                            height={21}
                            rx={7}
                          />
                          <text textAnchor="middle">{text}</text>
                        </g>
                      );
                    })()}
                </g>
              </g>
            </svg>
            <div className={styles.legend}>
              <span>
                <i data-kind="indexed" />
                {t("files.memoryGraphIndexed")}
              </span>
              <span>
                <i data-kind="unresolved" />
                {t("files.memoryGraphUnresolved")}
              </span>
              <span>
                <b>→</b>
                {t("files.memoryGraphDirection")}
              </span>
            </div>
          </div>

          {selected && (
            <aside className={styles.details}>
              <span
                className={styles.nodeStatus}
                data-indexed={selected.indexed}
                data-virtual={selected.virtual}
              >
                {selected.virtual
                  ? root
                  : selected.indexed
                  ? t("files.memoryGraphIndexed")
                  : t("files.memoryGraphUnresolved")}
              </span>
              <h2>{nodeLabel(selected)}</h2>
              <code>{selected.path}</code>
              {selected.description && <p>{selected.description}</p>}
              {selectedFileTarget && (
                <button
                  type="button"
                  className={styles.openFileButton}
                  onClick={() =>
                    onOpenFile(
                      selectedFileTarget.section,
                      selectedFileTarget.path,
                    )
                  }
                >
                  <span>{t("files.memoryGraphOpenFile")}</span>
                  <ExternalLink size={14} />
                </button>
              )}
              <div className={styles.linkSection}>
                <strong>
                  {t("files.memoryGraphOutbound", { count: outbound.length })}
                </strong>
                {outbound.map((edge) => (
                  <button
                    type="button"
                    key={`${edge.target}:${edge.target_anchor ?? ""}`}
                    onClick={() => setSelectedId(edge.target)}
                  >
                    <span>
                      {nodeLabel(
                        graph.byId.get(edge.target) ?? {
                          ...selected,
                          name: "",
                          path: edge.target,
                        },
                      )}
                    </span>
                    <small>
                      {edge.target_anchor ? `#${edge.target_anchor}` : "→"}
                    </small>
                  </button>
                ))}
              </div>
              <div className={styles.linkSection}>
                <strong>
                  {t("files.memoryGraphInbound", { count: inbound.length })}
                </strong>
                {inbound.map((edge) => (
                  <button
                    type="button"
                    key={`${edge.source}:${edge.target_anchor ?? ""}`}
                    onClick={() => setSelectedId(edge.source)}
                  >
                    <span>
                      {nodeLabel(
                        graph.byId.get(edge.source) ?? {
                          ...selected,
                          name: "",
                          path: edge.source,
                        },
                      )}
                    </span>
                    <small>←</small>
                  </button>
                ))}
              </div>
            </aside>
          )}
        </div>
      )}
    </section>
  );
}
