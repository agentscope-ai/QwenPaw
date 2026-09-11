import {
  CircleAlert,
  ExternalLink,
  Link2,
  LoaderCircle,
  Maximize2,
  Orbit,
  RefreshCw,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import SpriteText from "three-spritetext";
import {
  ACESFilmicToneMapping,
  AmbientLight,
  BackSide,
  Color,
  DirectionalLight,
  FogExp2,
  Group,
  HemisphereLight,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  SphereGeometry,
  SRGBColorSpace,
  TorusGeometry,
  type PerspectiveCamera,
} from "three";
import type {
  ForceGraph3DInstance,
  LinkObject,
  NodeObject,
} from "3d-force-graph";
import { agentsApi } from "../../api/modules/agents";
import type { MemoryGraphNode, MemoryGraphSnapshot } from "../../api/types";
import type { MemorySection } from "../../api/types/workspace";
import type { MemoryGraphRoot } from "./types";
import styles from "./MemoryGraphView.module.less";

interface GraphNode extends NodeObject {
  degree: number;
  id: string;
  isRoot: boolean;
  isRootDirect: boolean;
  memory: MemoryGraphNode;
}

interface GraphLink extends LinkObject<GraphNode> {
  id: string;
  source: string | GraphNode;
  target: string | GraphNode;
  targetAnchor: string | null;
}

interface GraphModel {
  byId: Map<string, GraphNode>;
  links: GraphLink[];
  nodes: GraphNode[];
  reciprocalEdges: Set<string>;
}

interface GraphPalette {
  active: string;
  ambientLight: string;
  direct: string;
  edge: string;
  edgeActive: string;
  edgeMuted: string;
  fillLight: string;
  hover: string;
  isDark: boolean;
  keyLight: string;
  label: string;
  labelBackground: string;
  labelBorder: string;
  muted: string;
  root: string;
  surface: string;
  file: string;
}

interface OrbitControlsLike {
  autoRotate: boolean;
  autoRotateSpeed: number;
  dampingFactor: number;
  enableDamping: boolean;
  maxDistance: number;
  minDistance: number;
  target: { x: number; y: number; z: number };
  graphFitDistance?: number;
}

interface GraphNodeVisual {
  core: Mesh<SphereGeometry, MeshStandardMaterial>;
  glow: Mesh<SphereGeometry, MeshBasicMaterial>;
  label: SpriteText | null;
  orbit: Mesh<TorusGeometry, MeshBasicMaterial>;
}

interface ChargeForceLike {
  strength: (strength: number) => unknown;
}

interface LinkForceLike {
  distance: (distance: number) => unknown;
  strength: (strength: number) => unknown;
}

const EMPTY_GRAPH: MemoryGraphSnapshot = {
  version: 1,
  nodes: [],
  edges: [],
};
const GRAPH_ZOOM_MIN_DISTANCE_FLOOR = 78;
const GRAPH_ZOOM_MIN_DISTANCE_RATIO = 0.72;
const GRAPH_ZOOM_MAX_DISTANCE_FLOOR = 420;
const GRAPH_ZOOM_MAX_DISTANCE_CEILING = 3600;
const GRAPH_ZOOM_MAX_DISTANCE_MULTIPLIER = 1.8;

function nodeLabel(node: MemoryGraphNode): string {
  return (
    node.name || node.path.split("/").pop()?.replace(/\.md$/i, "") || node.path
  );
}

function nodeFileTarget(
  node: MemoryGraphNode,
): { section: MemorySection; path: string } | null {
  if (!node.indexed || node.virtual) return null;
  if (node.section && node.relative_path) {
    return { section: node.section, path: node.relative_path };
  }

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

function toGraphModel(
  snapshot: MemoryGraphSnapshot,
  root: MemoryGraphRoot,
): GraphModel {
  const degree = new Map(snapshot.nodes.map((node) => [node.id, 0]));
  snapshot.edges.forEach((edge) => {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
  });

  const rootNode = snapshot.nodes.find(
    (node) =>
      node.id === `virtual:${root}` || (node.virtual && node.name === root),
  );
  const rootDirectIds = new Set(
    snapshot.edges
      .filter(
        (edge) => edge.source === rootNode?.id || edge.target === rootNode?.id,
      )
      .map((edge) =>
        edge.source === rootNode?.id ? edge.target : edge.source,
      ),
  );

  const nodes = snapshot.nodes.map<GraphNode>((memory) => ({
    degree: degree.get(memory.id) ?? 0,
    fx: memory.virtual ? 0 : undefined,
    fy: memory.virtual ? 0 : undefined,
    fz: memory.virtual ? 0 : undefined,
    id: memory.id,
    isRoot: memory.id === rootNode?.id,
    isRootDirect: rootDirectIds.has(memory.id),
    memory,
  }));
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const edgeKeys = new Set(
    snapshot.edges.map((edge) => `${edge.source}\u0000${edge.target}`),
  );
  const reciprocalEdges = new Set(
    [...edgeKeys].filter((key) => {
      const [source, target] = key.split("\u0000");
      return edgeKeys.has(`${target}\u0000${source}`);
    }),
  );
  const links = snapshot.edges.map<GraphLink>((edge, index) => ({
    id: `${edge.source}:${edge.target}:${edge.target_anchor ?? ""}:${index}`,
    source: edge.source,
    target: edge.target,
    targetAnchor: edge.target_anchor,
  }));

  return { byId, links, nodes, reciprocalEdges };
}

function graphNeighborIds(
  snapshot: MemoryGraphSnapshot | null,
  nodeId: string,
): Set<string> {
  const neighbors = new Set<string>();
  if (!nodeId) return neighbors;
  (snapshot?.edges ?? []).forEach((edge) => {
    if (edge.source === nodeId) neighbors.add(edge.target);
    if (edge.target === nodeId) neighbors.add(edge.source);
  });
  return neighbors;
}

function endpointId(endpoint: GraphLink["source"]): string {
  return typeof endpoint === "object" ? endpoint.id : String(endpoint);
}

function cssColorChannels(color: string): [number, number, number] | null {
  const hex = color.match(/^#([\da-f]{3}|[\da-f]{6})$/i)?.[1];
  if (hex) {
    const normalized =
      hex.length === 3
        ? hex
            .split("")
            .map((channel) => `${channel}${channel}`)
            .join("")
        : hex;
    return [0, 2, 4].map((offset) =>
      Number.parseInt(normalized.slice(offset, offset + 2), 16),
    ) as [number, number, number];
  }
  const rgb = color.match(
    /^rgba?\(\s*([\d.]+)\s*[, ]\s*([\d.]+)\s*[, ]\s*([\d.]+)/i,
  );
  return rgb ? (rgb.slice(1, 4).map(Number) as [number, number, number]) : null;
}

function opaqueThemeColor(color: string, surface: string): string {
  const rgba = color.match(
    /^rgba?\(\s*([\d.]+)\s*[, ]\s*([\d.]+)\s*[, ]\s*([\d.]+)(?:\s*[,/]\s*([\d.]+))?\s*\)$/i,
  );
  if (!rgba?.[4]) return color;
  const alpha = Math.min(1, Math.max(0, Number(rgba[4])));
  const background = cssColorChannels(surface) ?? [255, 253, 251];
  const foreground = rgba.slice(1, 4).map(Number);
  const composite = foreground.map((channel, index) => {
    return Math.round(channel * alpha + background[index] * (1 - alpha));
  });
  return `rgb(${composite.join(", ")})`;
}

function isDarkSurface(color: string): boolean {
  const channels = cssColorChannels(color);
  if (!channels) return false;
  const [red, green, blue] = channels.map((channel) => channel / 255);
  const luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue;
  return luminance < 0.28;
}

function graphPalette(element: HTMLElement): GraphPalette {
  const computed = window.getComputedStyle(element);
  const value = (name: string, fallback: string) =>
    computed.getPropertyValue(name).trim() || fallback;
  const surface = value("--graph-3d-surface", "#fffdfb");
  const opaqueValue = (name: string, fallback: string) =>
    opaqueThemeColor(value(name, fallback), surface);
  return {
    active: opaqueValue("--graph-3d-active", "#d9650b"),
    ambientLight: opaqueValue("--graph-3d-ambient-light", "#eee7e1"),
    direct: opaqueValue("--graph-3d-direct", "#389e5c"),
    edge: opaqueValue("--graph-3d-edge", "#d8cec6"),
    edgeActive: opaqueValue("--graph-3d-edge-active", "#d9650b"),
    edgeMuted: opaqueValue("--graph-3d-edge-muted", "#eee7e1"),
    fillLight: opaqueValue("--graph-3d-fill-light", "#fff2e8"),
    hover: opaqueValue("--graph-3d-hover", "#ff9a45"),
    isDark: isDarkSurface(surface),
    keyLight: opaqueValue("--graph-3d-key-light", "#fffdfb"),
    label: opaqueValue("--graph-3d-label", "#292522"),
    labelBackground: value("--graph-3d-label-background", "#fffdfb"),
    labelBorder: opaqueValue("--graph-3d-label-border", "#ffc58f"),
    muted: opaqueValue("--graph-3d-muted", "#c7bfb8"),
    root: opaqueValue("--graph-3d-root", "#ff7f16"),
    surface,
    file: opaqueValue("--graph-3d-file", "#71665e"),
  };
}

function baseNodeColor(node: GraphNode, palette: GraphPalette): string {
  if (node.isRoot) return palette.root;
  if (node.isRootDirect) return palette.direct;
  return palette.file;
}

function graphNodeRadius(node: GraphNode): number {
  if (node.isRoot) return 4.8;
  if (node.isRootDirect) return 3.55;
  if (!node.memory.indexed) return 2.55;
  return Math.min(3.35, 2.7 + Math.sqrt(node.degree) * 0.24);
}

function graphNodeValue(node: GraphNode): number {
  return graphNodeRadius(node) ** 3;
}

function graphLabelText(node: GraphNode): string {
  const label = nodeLabel(node.memory);
  return label.length > 22 ? `${label.slice(0, 21)}…` : label;
}

function shouldRenderGraphLabel(node: GraphNode, nodeCount: number): boolean {
  return nodeCount <= 42 || node.isRoot || node.degree >= 4;
}

function createGraphLights(palette: GraphPalette) {
  const ambient = new AmbientLight(
    palette.ambientLight,
    palette.isDark ? 1.45 : 1.25,
  );
  const hemisphere = new HemisphereLight(
    palette.keyLight,
    palette.ambientLight,
    palette.isDark ? 1.22 : 1.05,
  );
  const key = new DirectionalLight(
    palette.keyLight,
    palette.isDark ? 2.7 : 2.3,
  );
  key.position.set(110, 150, 190);
  const fill = new DirectionalLight(
    palette.fillLight,
    palette.isDark ? 1.08 : 0.82,
  );
  fill.position.set(-120, -55, -90);
  return [ambient, hemisphere, key, fill];
}

function createGraphNodeVisual(
  node: GraphNode,
  palette: GraphPalette,
  nodeCount: number,
): { object: Group; visual: GraphNodeVisual } {
  const radius = graphNodeRadius(node);
  const segments = nodeCount > 220 ? 14 : 24;
  const object = new Group();
  const baseColor = baseNodeColor(node, palette);
  const coreMaterial = new MeshStandardMaterial({
    color: baseColor,
    emissive: new Color(baseColor),
    emissiveIntensity: node.isRoot ? 0.14 : node.isRootDirect ? 0.07 : 0.03,
    metalness: node.isRoot || node.isRootDirect ? 0.08 : 0.035,
    opacity: node.memory.indexed || node.isRoot ? 1 : 0.74,
    roughness: node.isRoot ? 0.38 : node.isRootDirect ? 0.46 : 0.58,
    transparent: !node.memory.indexed,
    wireframe: !node.memory.indexed && !node.isRoot,
  });
  const core = new Mesh(
    new SphereGeometry(radius, segments, Math.max(10, segments - 6)),
    coreMaterial,
  );
  object.add(core);

  const orbitMaterial = new MeshBasicMaterial({
    color: node.isRoot ? palette.root : palette.active,
    depthWrite: false,
    opacity: node.isRoot ? 0.42 : 0,
    transparent: true,
  });
  const orbit = new Mesh(
    new TorusGeometry(radius * 1.43, radius * 0.035, 8, 44),
    orbitMaterial,
  );
  orbit.rotation.set(Math.PI * 0.38, Math.PI * 0.12, Math.PI * 0.08);
  orbit.visible = node.isRoot;
  object.add(orbit);

  const glowMaterial = new MeshBasicMaterial({
    color: palette.active,
    depthWrite: false,
    opacity: 0,
    side: BackSide,
    transparent: true,
  });
  const glow = new Mesh(
    new SphereGeometry(radius * 1.28, 18, 12),
    glowMaterial,
  );
  glow.visible = false;
  object.add(glow);

  let label: SpriteText | null = null;
  if (shouldRenderGraphLabel(node, nodeCount)) {
    label = new SpriteText(
      graphLabelText(node),
      node.isRoot ? 4.3 : 3.7,
      palette.label,
    );
    label.backgroundColor = node.isRoot
      ? palette.labelBackground
      : "transparent";
    label.borderColor = palette.labelBorder;
    label.borderRadius = 1.1;
    label.borderWidth = node.isRoot ? 0.14 : 0;
    label.fontFace = "Inter, ui-sans-serif, system-ui, sans-serif";
    label.fontSize = 76;
    label.fontWeight = node.isRoot ? "650" : "560";
    label.padding = node.isRoot ? [1.05, 0.68] : [0.32, 0.1];
    label.position.set(0, -(radius + 3.6), 0);
    label.renderOrder = 4;
    label.material.depthTest = false;
    label.material.depthWrite = false;
    label.material.toneMapped = false;
    object.add(label);
  }

  return { object, visual: { core, glow, label, orbit } };
}

function applyGraphVisualState(
  graph: ForceGraph3DInstance<GraphNode, GraphLink>,
  model: GraphModel,
  visuals: Map<string, GraphNodeVisual>,
  palette: GraphPalette,
  selectedId: string,
  selectedNeighbors: Set<string>,
  reducedMotion: boolean,
) {
  model.nodes.forEach((node) => {
    const visual = visuals.get(node.id);
    if (!visual) return;
    const isSelected = node.id === selectedId;
    const isNeighbor = selectedNeighbors.has(node.id);
    const isMuted = Boolean(selectedId) && !isSelected && !isNeighbor;
    const baseColor = baseNodeColor(node, palette);
    const nodeColor = isSelected
      ? palette.active
      : isMuted
      ? palette.muted
      : baseColor;

    visual.core.material.color.set(nodeColor);
    visual.core.material.emissive.set(isSelected ? palette.active : baseColor);
    visual.core.material.emissiveIntensity = isSelected
      ? 0.32
      : node.isRoot
      ? 0.13
      : node.isRootDirect
      ? 0.07
      : 0.03;
    visual.core.material.opacity = isMuted
      ? 0.24
      : node.memory.indexed || node.isRoot
      ? 1
      : 0.74;
    visual.core.material.transparent = isMuted || !node.memory.indexed;
    visual.core.material.needsUpdate = true;

    visual.orbit.visible = isSelected || node.isRoot;
    visual.orbit.material.color.set(isSelected ? palette.active : palette.root);
    visual.orbit.material.opacity = isSelected ? 0.78 : isMuted ? 0.12 : 0.42;
    visual.glow.visible = isSelected;
    visual.glow.material.color.set(palette.active);
    visual.glow.material.opacity = isSelected ? 0.13 : 0;

    if (visual.label) {
      visual.label.visible =
        !selectedId || isSelected || isNeighbor || node.isRoot;
      visual.label.color = isSelected
        ? palette.active
        : isMuted
        ? palette.muted
        : palette.label;
      visual.label.backgroundColor =
        node.isRoot || isSelected ? palette.labelBackground : "transparent";
      visual.label.borderColor = isSelected
        ? palette.active
        : palette.labelBorder;
      visual.label.borderWidth = node.isRoot || isSelected ? 0.14 : 0;
      visual.label.material.opacity = isMuted ? 0.3 : 1;
    }
  });

  const isActiveLink = (link: GraphLink) => {
    const source = endpointId(link.source);
    const target = endpointId(link.target);
    return source === selectedId || target === selectedId;
  };
  const showAmbientParticles = model.links.length <= 160;

  graph
    .linkColor((link) => {
      if (!selectedId) return palette.edge;
      if (isActiveLink(link)) return palette.edgeActive;
      return palette.edgeMuted;
    })
    .linkWidth((link) => {
      if (!selectedId) return 0.42;
      return isActiveLink(link) ? 1.05 : 0.08;
    })
    .linkDirectionalArrowLength((link) => {
      if (!selectedId) return 2.15;
      return isActiveLink(link) ? 3.25 : 0.8;
    })
    .linkDirectionalArrowColor((link) => {
      if (!selectedId) return palette.edge;
      if (isActiveLink(link)) return palette.edgeActive;
      return palette.edgeMuted;
    })
    .linkDirectionalParticles((link) => {
      if (reducedMotion) return 0;
      if (!selectedId) return showAmbientParticles ? 1 : 0;
      return isActiveLink(link) ? 2 : 0;
    })
    .linkDirectionalParticleSpeed(reducedMotion ? 0 : 0.0026)
    .linkDirectionalParticleWidth((link) => {
      if (!selectedId) return 0.62;
      return isActiveLink(link) ? 0.9 : 0;
    })
    .linkDirectionalParticleColor((link) =>
      selectedId && isActiveLink(link) ? palette.active : palette.edgeActive,
    );
}

function setHoveredGraphNodeColor(
  visuals: Map<string, GraphNodeVisual>,
  node: GraphNode | null,
  previousNode: GraphNode | null,
  palette: GraphPalette,
  selectedId: string,
  selectedNeighbors: Set<string>,
) {
  [node, previousNode].forEach((candidate) => {
    if (!candidate || candidate.id === selectedId) return;
    const visual = visuals.get(candidate.id);
    if (!visual) return;
    const isHovered = candidate.id === node?.id;
    const isMuted = Boolean(selectedId) && !selectedNeighbors.has(candidate.id);
    const color = isHovered
      ? palette.hover
      : isMuted
      ? palette.muted
      : baseNodeColor(candidate, palette);

    visual.core.material.color.set(color);
    visual.core.material.emissive.set(color);
    visual.core.material.needsUpdate = true;
  });
}

function applyGraphZoomLimits(
  graph: ForceGraph3DInstance<GraphNode, GraphLink>,
  fitDistance: number,
) {
  const controls = graph.controls() as OrbitControlsLike;
  controls.graphFitDistance = fitDistance;
  controls.minDistance = Math.max(
    GRAPH_ZOOM_MIN_DISTANCE_FLOOR,
    fitDistance * GRAPH_ZOOM_MIN_DISTANCE_RATIO,
  );
  controls.maxDistance = Math.max(
    fitDistance,
    Math.min(
      GRAPH_ZOOM_MAX_DISTANCE_CEILING,
      Math.max(
        GRAPH_ZOOM_MAX_DISTANCE_FLOOR,
        fitDistance * GRAPH_ZOOM_MAX_DISTANCE_MULTIPLIER,
      ),
    ),
  );

  const camera = graph.camera() as PerspectiveCamera;
  const requiredFarPlane = controls.maxDistance * 1.6;
  if (camera.far < requiredFarPlane) {
    camera.far = requiredFarPlane;
    camera.updateProjectionMatrix();
  }
}

function fitGraphModel(
  graph: ForceGraph3DInstance<GraphNode, GraphLink>,
  nodes: GraphNode[],
  duration: number,
) {
  const positioned = nodes.filter(
    (node) =>
      Number.isFinite(node.x) &&
      Number.isFinite(node.y) &&
      Number.isFinite(node.z),
  );
  if (positioned.length < 2) {
    if (nodes.length < 2) {
      applyGraphZoomLimits(
        graph,
        GRAPH_ZOOM_MIN_DISTANCE_FLOOR / GRAPH_ZOOM_MIN_DISTANCE_RATIO,
      );
    }
    graph.zoomToFit(duration, 64);
    return;
  }

  const bounds = positioned.reduce(
    (current, node) => ({
      maxX: Math.max(current.maxX, Number(node.x)),
      maxY: Math.max(current.maxY, Number(node.y)),
      maxZ: Math.max(current.maxZ, Number(node.z)),
      minX: Math.min(current.minX, Number(node.x)),
      minY: Math.min(current.minY, Number(node.y)),
      minZ: Math.min(current.minZ, Number(node.z)),
    }),
    {
      maxX: -Infinity,
      maxY: -Infinity,
      maxZ: -Infinity,
      minX: Infinity,
      minY: Infinity,
      minZ: Infinity,
    },
  );
  const target = {
    x: (bounds.minX + bounds.maxX) / 2,
    y: (bounds.minY + bounds.maxY) / 2,
    z: (bounds.minZ + bounds.maxZ) / 2,
  };
  const camera = graph.camera() as PerspectiveCamera;
  const viewRadius = Math.max(
    ...positioned.map((node) =>
      Math.hypot(
        Number(node.x) - target.x,
        Number(node.y) - target.y,
        Number(node.z) - target.z,
      ),
    ),
    30,
  );
  const distance = (viewRadius / Math.tan((camera.fov * Math.PI) / 360)) * 0.92;
  applyGraphZoomLimits(graph, distance);
  const currentCamera = graph.cameraPosition();
  const offset = {
    x: currentCamera.x - target.x,
    y: currentCamera.y - target.y,
    z: currentCamera.z - target.z,
  };
  const offsetLength = Math.hypot(offset.x, offset.y, offset.z) || 1;

  graph.cameraPosition(
    {
      x: target.x + (offset.x / offsetLength) * distance,
      y: target.y + (offset.y / offsetLength) * distance,
      z: target.z + (offset.z / offsetLength) * distance,
    },
    target,
    duration,
  );
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
  const canvasLabel = t("files.memoryGraphCanvasLabel");
  const [snapshot, setSnapshot] = useState<MemoryGraphSnapshot | null>(null);
  const [snapshotAgentId, setSnapshotAgentId] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [graphReady, setGraphReady] = useState(false);
  const [renderError, setRenderError] = useState(false);
  const [renderSequence, setRenderSequence] = useState(0);
  const [autoRotate, setAutoRotate] = useState(true);
  const [reducedMotion, setReducedMotion] = useState(false);
  const sceneRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<ForceGraph3DInstance<GraphNode, GraphLink> | null>(
    null,
  );
  const nodeVisualsRef = useRef(new Map<string, GraphNodeVisual>());
  const autoRotateRef = useRef(autoRotate);
  const selectedIdRef = useRef(selectedId);
  const hoveredIdRef = useRef("");
  const requestSequence = useRef(0);
  autoRotateRef.current = autoRotate;
  selectedIdRef.current = selectedId;

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
      try {
        const next = await agentsApi.getMemoryGraph(agentId);
        if (sequence !== requestSequence.current) return;
        setSnapshot(next);
        setSnapshotAgentId(agentId);
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
  }, [root]);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const syncPreference = () => setReducedMotion(query.matches);
    syncPreference();
    query.addEventListener("change", syncPreference);
    return () => query.removeEventListener("change", syncPreference);
  }, []);

  const currentSnapshot = snapshotAgentId === agentId ? snapshot : null;
  const graphSnapshot = useMemo(
    () => (currentSnapshot ? graphBelowRoot(currentSnapshot, root) : null),
    [currentSnapshot, root],
  );
  const graphModel = useMemo(
    () => toGraphModel(graphSnapshot ?? EMPTY_GRAPH, root),
    [graphSnapshot, root],
  );
  const selectedNeighbors = useMemo(
    () => graphNeighborIds(graphSnapshot, selectedId),
    [graphSnapshot, selectedId],
  );
  const visualStateRef = useRef({
    selectedId,
    selectedNeighbors,
  });
  visualStateRef.current = { selectedId, selectedNeighbors };
  const selected = graphSnapshot?.nodes.find((node) => node.id === selectedId);
  const selectedFileTarget = selected ? nodeFileTarget(selected) : null;
  const inbound =
    graphSnapshot?.edges.filter((edge) => edge.target === selectedId) ?? [];
  const outbound =
    graphSnapshot?.edges.filter((edge) => edge.source === selectedId) ?? [];

  const focusGraphNode = useCallback(
    (nodeId: string) => {
      const graph = graphRef.current;
      const node = graphModel.byId.get(nodeId);
      selectedIdRef.current = nodeId;
      setSelectedId(nodeId);
      if (!graph || !node) return;

      const target = {
        x: Number(node.x ?? node.fx ?? 0),
        y: Number(node.y ?? node.fy ?? 0),
        z: Number(node.z ?? node.fz ?? 0),
      };
      const camera = graph.cameraPosition();
      const offset = {
        x: camera.x - target.x,
        y: camera.y - target.y,
        z: camera.z - target.z,
      };
      const length = Math.hypot(offset.x, offset.y, offset.z) || 1;
      const distance = node.isRoot ? 185 : 118;
      const controls = graph.controls() as OrbitControlsLike;
      controls.minDistance = Math.min(controls.minDistance, distance);
      graph.cameraPosition(
        {
          x: target.x + (offset.x / length) * distance,
          y: target.y + (offset.y / length) * distance,
          z: target.z + (offset.z / length) * distance,
        },
        target,
        reducedMotion ? 0 : 720,
      );
    },
    [graphModel.byId, reducedMotion],
  );

  const fitGraph = useCallback(() => {
    const graph = graphRef.current;
    if (!graph) return;
    fitGraphModel(graph, graphModel.nodes, reducedMotion ? 0 : 520);
  }, [graphModel.nodes, reducedMotion]);

  const zoomGraph = useCallback(
    (factor: number) => {
      const graph = graphRef.current;
      if (!graph) return;
      const camera = graph.cameraPosition();
      const controls = graph.controls() as OrbitControlsLike;
      const selectedNode = graphModel.byId.get(selectedId);
      const target = selectedNode
        ? {
            x: Number(selectedNode.x ?? selectedNode.fx ?? 0),
            y: Number(selectedNode.y ?? selectedNode.fy ?? 0),
            z: Number(selectedNode.z ?? selectedNode.fz ?? 0),
          }
        : {
            x: Number(controls.target.x),
            y: Number(controls.target.y),
            z: Number(controls.target.z),
          };
      const currentDistance = Math.hypot(
        camera.x - target.x,
        camera.y - target.y,
        camera.z - target.z,
      );
      const nextDistance = Math.min(
        controls.maxDistance,
        Math.max(controls.minDistance, currentDistance * factor),
      );
      const scale = currentDistance > 0 ? nextDistance / currentDistance : 1;
      graph.cameraPosition(
        {
          x: target.x + (camera.x - target.x) * scale,
          y: target.y + (camera.y - target.y) * scale,
          z: target.z + (camera.z - target.z) * scale,
        },
        target,
        reducedMotion ? 0 : 220,
      );
    },
    [graphModel.byId, reducedMotion, selectedId],
  );

  useEffect(() => {
    const container = sceneRef.current;
    if (!container || graphModel.nodes.length === 0) return;
    const nodeVisuals = nodeVisualsRef.current;

    let cancelled = false;
    let graph: ForceGraph3DInstance<GraphNode, GraphLink> | null = null;
    let initialFrame = 0;
    let resizeFrame = 0;
    let handleWindowResize: (() => void) | null = null;
    let resizeObserver: ResizeObserver | null = null;
    let themeObserver: MutationObserver | null = null;
    setGraphReady(false);
    setRenderError(false);
    nodeVisuals.clear();

    void import("3d-force-graph")
      .then(({ default: ForceGraph3D }) => {
        if (cancelled) return;
        const palette = graphPalette(container);
        const createdGraph = new ForceGraph3D(container, {
          controlType: "orbit",
          rendererConfig: {
            alpha: false,
            antialias: true,
            powerPreference: "high-performance",
          },
        }) as unknown as ForceGraph3DInstance<GraphNode, GraphLink>;
        graph = createdGraph;
        graphRef.current = createdGraph;

        const resize = () => {
          if (!graph) return;
          const bounds = container.getBoundingClientRect();
          graph
            .width(Math.max(1, Math.round(bounds.width || 960)))
            .height(Math.max(1, Math.round(bounds.height || 620)));
        };
        const applyTheme = () => {
          if (!graph) return;
          const nextPalette = graphPalette(container);
          graph.backgroundColor(nextPalette.surface);
          graph.scene().fog = new FogExp2(
            nextPalette.surface,
            nextPalette.isDark ? 0.00085 : 0.0016,
          );
          graph.renderer().toneMappingExposure = nextPalette.isDark
            ? 1.1
            : 0.98;
          graph.lights(createGraphLights(nextPalette));
          applyGraphVisualState(
            graph,
            graphModel,
            nodeVisuals,
            nextPalette,
            visualStateRef.current.selectedId,
            visualStateRef.current.selectedNeighbors,
            reducedMotion,
          );
        };
        const resizeAndFit = () => {
          resize();
          window.cancelAnimationFrame(resizeFrame);
          resizeFrame = window.requestAnimationFrame(() => {
            if (!selectedIdRef.current) {
              if (graph) {
                fitGraphModel(graph, graphModel.nodes, reducedMotion ? 0 : 220);
              }
            }
          });
        };
        handleWindowResize = resizeAndFit;

        createdGraph
          .showNavInfo(false)
          .backgroundColor(palette.surface)
          .numDimensions(3)
          .nodeId("id")
          .nodeRelSize(1)
          .nodeVal(graphNodeValue)
          .nodeOpacity(1)
          .nodeResolution(24)
          .nodeThreeObject((node) => {
            const { object, visual } = createGraphNodeVisual(
              node,
              palette,
              graphModel.nodes.length,
            );
            nodeVisuals.set(node.id, visual);
            return object;
          })
          .nodeThreeObjectExtend(false)
          .nodeLabel(() => "")
          .linkOpacity(0.64)
          .linkResolution(4)
          .linkDirectionalArrowRelPos(0.94)
          .linkDirectionalArrowResolution(10)
          .linkDirectionalParticleResolution(6)
          .linkCurvature((link) => {
            const source = endpointId(link.source);
            const target = endpointId(link.target);
            if (!graphModel.reciprocalEdges.has(`${source}\u0000${target}`)) {
              return 0;
            }
            return source.localeCompare(target) < 0 ? 0.12 : -0.12;
          })
          .enableNodeDrag(false)
          .enableNavigationControls(true)
          .d3AlphaDecay(0.038)
          .d3VelocityDecay(0.3)
          .warmupTicks(52)
          .cooldownTicks(160)
          .onNodeHover((node, previousNode) => {
            const nextHoveredId = node?.id ?? "";
            if (hoveredIdRef.current === nextHoveredId) return;
            setHoveredGraphNodeColor(
              nodeVisuals,
              node,
              previousNode,
              graphPalette(container),
              selectedIdRef.current,
              graphNeighborIds(graphSnapshot, selectedIdRef.current),
            );
            hoveredIdRef.current = nextHoveredId;
          })
          .onNodeClick((node) => focusGraphNode(node.id))
          .onBackgroundClick(() => {
            selectedIdRef.current = "";
            setSelectedId("");
          })
          .graphData({ nodes: graphModel.nodes, links: graphModel.links });

        (
          createdGraph.d3Force("charge") as ChargeForceLike | undefined
        )?.strength(-108);
        const linkForce = createdGraph.d3Force("link") as
          | LinkForceLike
          | undefined;
        linkForce?.distance(72);
        linkForce?.strength(0.46);

        const controls = createdGraph.controls() as OrbitControlsLike;
        controls.autoRotate = autoRotateRef.current && !reducedMotion;
        controls.autoRotateSpeed = 0.14;
        controls.enableDamping = true;
        controls.dampingFactor = 0.08;
        controls.minDistance = GRAPH_ZOOM_MIN_DISTANCE_FLOOR;
        controls.maxDistance = GRAPH_ZOOM_MAX_DISTANCE_CEILING;

        const renderer = createdGraph.renderer();
        renderer.outputColorSpace = SRGBColorSpace;
        renderer.toneMapping = ACESFilmicToneMapping;
        renderer.toneMappingExposure = palette.isDark ? 1.1 : 0.98;
        const camera = createdGraph.camera() as PerspectiveCamera;
        camera.fov = 44;
        camera.near = 0.1;
        camera.far = GRAPH_ZOOM_MAX_DISTANCE_CEILING * 1.6;
        camera.updateProjectionMatrix();
        createdGraph.scene().fog = new FogExp2(
          palette.surface,
          palette.isDark ? 0.00085 : 0.0016,
        );
        createdGraph.lights(createGraphLights(palette));

        const canvas = renderer.domElement;
        canvas.setAttribute("role", "img");
        canvas.setAttribute("aria-label", canvasLabel);
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

        resize();
        resizeObserver = new ResizeObserver(resizeAndFit);
        resizeObserver.observe(container);
        window.addEventListener("resize", handleWindowResize);
        themeObserver = new MutationObserver(applyTheme);
        themeObserver.observe(document.documentElement, {
          attributeFilter: ["class"],
          attributes: true,
        });
        initialFrame = window.requestAnimationFrame(() => {
          if (graph) fitGraphModel(graph, graphModel.nodes, 0);
        });
        createdGraph.onEngineStop(() => {
          if (graph) {
            fitGraphModel(graph, graphModel.nodes, reducedMotion ? 0 : 480);
          }
        });
        setGraphReady(true);
      })
      .catch(() => {
        if (!cancelled) setRenderError(true);
      });

    return () => {
      cancelled = true;
      window.cancelAnimationFrame(initialFrame);
      window.cancelAnimationFrame(resizeFrame);
      if (handleWindowResize) {
        window.removeEventListener("resize", handleWindowResize);
      }
      resizeObserver?.disconnect();
      themeObserver?.disconnect();
      graph?._destructor();
      nodeVisuals.clear();
      hoveredIdRef.current = "";
      if (graphRef.current === graph) graphRef.current = null;
      container.replaceChildren();
    };
  }, [
    canvasLabel,
    focusGraphNode,
    graphModel,
    graphSnapshot,
    reducedMotion,
    renderSequence,
  ]);

  useEffect(() => {
    const graph = graphRef.current;
    const container = sceneRef.current;
    if (!graph || !container || !graphReady) return;
    applyGraphVisualState(
      graph,
      graphModel,
      nodeVisualsRef.current,
      graphPalette(container),
      selectedId,
      selectedNeighbors,
      reducedMotion,
    );
  }, [graphModel, graphReady, reducedMotion, selectedId, selectedNeighbors]);

  useEffect(() => {
    const graph = graphRef.current;
    if (!graph) return;
    const controls = graph.controls() as OrbitControlsLike;
    controls.autoRotate = autoRotate && !reducedMotion;
  }, [autoRotate, graphReady, reducedMotion]);

  useEffect(() => {
    if (selectedId) return;
    const graph = graphRef.current;
    if (!graph) return;
    const controls = graph.controls() as OrbitControlsLike;
    if (controls.graphFitDistance === undefined) return;
    controls.minDistance = Math.max(
      GRAPH_ZOOM_MIN_DISTANCE_FLOOR,
      controls.graphFitDistance * GRAPH_ZOOM_MIN_DISTANCE_RATIO,
    );
  }, [selectedId]);

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
            onClick={() => zoomGraph(1.18)}
            aria-label={t("files.memoryGraphZoomOut")}
            title={t("files.memoryGraphZoomOut")}
          >
            <ZoomOut size={16} />
          </button>
          <button
            type="button"
            onClick={() => zoomGraph(0.84)}
            aria-label={t("files.memoryGraphZoomIn")}
            title={t("files.memoryGraphZoomIn")}
          >
            <ZoomIn size={16} />
          </button>
          <button
            type="button"
            onClick={fitGraph}
            aria-label={t("files.memoryGraphFit")}
            title={t("files.memoryGraphFit")}
          >
            <Maximize2 size={16} />
          </button>
          <button
            type="button"
            className={autoRotate && !reducedMotion ? styles.actionActive : ""}
            onClick={() => setAutoRotate((current) => !current)}
            aria-label={t("files.memoryGraphAutoRotate")}
            aria-pressed={autoRotate && !reducedMotion}
            disabled={reducedMotion}
            title={
              reducedMotion
                ? t("files.memoryGraphMotionReduced")
                : t("files.memoryGraphAutoRotate")
            }
          >
            <Orbit size={16} />
          </button>
          <button
            type="button"
            onClick={() => void load()}
            aria-label={t("common.refresh")}
            title={t("common.refresh")}
          >
            <RefreshCw className={loading ? styles.spin : ""} size={16} />
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
          <div className={styles.canvas}>
            <div
              ref={sceneRef}
              className={styles.scene}
              data-testid="memory-graph-3d"
            />
            {!graphReady && !renderError && (
              <div className={styles.canvasState} role="status">
                <LoaderCircle className={styles.spin} size={18} />
                {t("files.memoryGraphRendering")}
              </div>
            )}
            {renderError && (
              <div className={styles.canvasState} role="alert">
                <CircleAlert size={18} />
                <span>{t("files.memoryGraphRenderFailed")}</span>
                <button
                  type="button"
                  onClick={() => setRenderSequence((current) => current + 1)}
                >
                  {t("common.retry")}
                </button>
              </div>
            )}
            <div className={styles.accessibleNodes}>
              {graphModel.nodes.map((node) => (
                <button
                  type="button"
                  key={node.id}
                  aria-label={nodeLabel(node.memory)}
                  aria-pressed={node.id === selectedId}
                  onClick={() => focusGraphNode(node.id)}
                >
                  {nodeLabel(node.memory)}
                </button>
              ))}
            </div>
            <div className={styles.legend}>
              <span>
                <i data-kind="root" />
                {t("files.memoryGraphRoot")}
              </span>
              <span>
                <i data-kind="direct" />
                {t("files.memoryGraphRootDirect")}
              </span>
              <span>
                <i data-kind="file" />
                {t("files.memoryGraphOtherFile")}
              </span>
              <span>
                <b>→</b>
                {t("files.memoryGraphDirection")}
              </span>
            </div>
          </div>

          {selected && (
            <aside className={styles.details}>
              <header className={styles.detailsHeader}>
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
                <button
                  type="button"
                  onClick={() => setSelectedId("")}
                  aria-label={t("files.memoryGraphCloseDetails")}
                  title={t("files.memoryGraphCloseDetails")}
                >
                  <X size={15} />
                </button>
              </header>
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
                    onClick={() => focusGraphNode(edge.target)}
                  >
                    <span>
                      {nodeLabel(
                        graphModel.byId.get(edge.target)?.memory ?? {
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
                    onClick={() => focusGraphNode(edge.source)}
                  >
                    <span>
                      {nodeLabel(
                        graphModel.byId.get(edge.source)?.memory ?? {
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
