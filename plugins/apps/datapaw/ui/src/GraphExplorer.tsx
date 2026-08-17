import {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import type {
  CypherResponse,
  DataSourceMetadata,
  GraphData,
  GraphEdge,
  GraphNode,
  GraphSchema,
  GraphZone,
} from "./api";
import { normalizeEdge, normalizeNode } from "./api";
import { compactLabel, layoutGraph } from "./graph-layout";
import { CloseIcon, PlayIcon, SearchIcon } from "./icons";
import { PageHeader } from "./PageHeader";

interface GraphApi {
  graphSchema(): Promise<GraphSchema>;
  globalGraph(zone: GraphZone, datasourceId?: string): Promise<GraphData>;
  searchGraph(query: string, zone: GraphZone): Promise<GraphData>;
  executeCypher(cypher: string, datasourceId?: string): Promise<CypherResponse>;
}

const ZONES: Array<{ id: GraphZone; label: string }> = [
  { id: "all", label: "All layers" },
  { id: "metadata", label: "Metadata" },
  { id: "trace", label: "Trace" },
  { id: "knowledge", label: "Knowledge" },
];

const ZONE_COLORS: Record<string, string> = {
  metadata: "#6b5cff",
  trace: "#12a594",
  knowledge: "#e9873d",
  unknown: "#65758b",
};

function toGraph(data: GraphData): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const nodes = data.nodes.map(normalizeNode).filter((node) => node.id);
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges = data.edges
    .map(normalizeEdge)
    .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target));
  return { nodes, edges };
}

export function GraphExplorer({
  api,
  selectedSource,
}: {
  api: GraphApi;
  selectedSource?: DataSourceMetadata;
}) {
  const [zone, setZone] = useState<GraphZone>("all");
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [schema, setSchema] = useState<GraphSchema>();
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [search, setSearch] = useState("");
  const [cypher, setCypher] = useState("MATCH (n) RETURN n LIMIT 50");
  const [queryResult, setQueryResult] = useState<CypherResponse>();
  const [mode, setMode] = useState<"graph" | "query">("graph");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [size, setSize] = useState({ width: 900, height: 620 });
  const canvasRef = useRef<HTMLDivElement>(null);
  const requestRef = useRef(0);

  const datasourceId = selectedSource?.datasource_id;
  const selectedNode = nodes.find((node) => node.id === selectedNodeId);
  const positioned = useMemo(
    () => layoutGraph(nodes, edges, size.width, size.height),
    [nodes, edges, size],
  );
  const positions = useMemo(
    () => new Map(positioned.map((node) => [node.id, node])),
    [positioned],
  );

  useEffect(() => {
    const element = canvasRef.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      setSize({
        width: entry.contentRect.width,
        height: entry.contentRect.height,
      });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const loadGraph = useCallback(
    async (nextZone = zone) => {
      const requestId = ++requestRef.current;
      setLoading(true);
      setError("");
      try {
        const [graph, nextSchema] = await Promise.all([
          api.globalGraph(nextZone, datasourceId),
          schema ? Promise.resolve(schema) : api.graphSchema(),
        ]);
        if (requestRef.current !== requestId) return;
        const normalized = toGraph(graph);
        setNodes(normalized.nodes);
        setEdges(normalized.edges);
        setSchema(nextSchema);
        setSelectedNodeId("");
        setQueryResult(undefined);
      } catch (nextError) {
        if (requestRef.current !== requestId) return;
        setError(
          nextError instanceof Error ? nextError.message : String(nextError),
        );
      } finally {
        if (requestRef.current === requestId) setLoading(false);
      }
    },
    [api, datasourceId, schema, zone],
  );

  useEffect(() => {
    void loadGraph(zone);
  }, [datasourceId, zone]); // eslint-disable-line react-hooks/exhaustive-deps

  async function runSearch(event: FormEvent) {
    event.preventDefault();
    if (!search.trim()) {
      await loadGraph(zone);
      return;
    }
    const requestId = ++requestRef.current;
    setLoading(true);
    setError("");
    try {
      const result = await api.searchGraph(search.trim(), zone);
      if (requestRef.current !== requestId) return;
      const normalized = toGraph(result);
      setNodes(normalized.nodes);
      setEdges(normalized.edges);
      setSelectedNodeId("");
    } catch (nextError) {
      if (requestRef.current === requestId) {
        setError(
          nextError instanceof Error ? nextError.message : String(nextError),
        );
      }
    } finally {
      if (requestRef.current === requestId) setLoading(false);
    }
  }

  async function runCypher(event: FormEvent) {
    event.preventDefault();
    if (!cypher.trim()) return;
    setLoading(true);
    setError("");
    try {
      const result = await api.executeCypher(cypher.trim(), datasourceId);
      setQueryResult(result);
      if (result.graph) {
        const normalized = toGraph(result.graph);
        setNodes(normalized.nodes);
        setEdges(normalized.edges);
      }
    } catch (nextError) {
      setError(
        nextError instanceof Error ? nextError.message : String(nextError),
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="datapaw-graph-page">
      <PageHeader
        eyebrow="Context memory"
        title="Context graph"
        description="Explore semantic context, knowledge, and analysis relationships."
        actions={
          <div className="datapaw-segmented">
            <button
              className={mode === "graph" ? "is-active" : ""}
              onClick={() => setMode("graph")}
            >
              Explore
            </button>
            <button
              className={mode === "query" ? "is-active" : ""}
              onClick={() => setMode("query")}
            >
              Cypher
            </button>
          </div>
        }
      />

      <div className="datapaw-graph-layout">
        <aside className="datapaw-graph-sidebar">
          <form className="datapaw-search" onSubmit={runSearch}>
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search nodes and neighbors"
            />
            <button type="submit" aria-label="Search">
              <SearchIcon size={14} />
            </button>
          </form>
          <div className="datapaw-zone-list">
            <span>Graph layer</span>
            {ZONES.map((item) => (
              <button
                className={zone === item.id ? "is-active" : ""}
                key={item.id}
                onClick={() => setZone(item.id)}
                type="button"
              >
                <i style={{ background: ZONE_COLORS[item.id] || "#7f8da3" }} />
                {item.label}
              </button>
            ))}
          </div>
          {schema ? (
            <div className="datapaw-schema">
              <span>Node types</span>
              <div>
                {schema.node_labels.slice(0, 18).map((item) => (
                  <button
                    type="button"
                    key={`${item.zone}:${item.label}`}
                    onClick={() => setSearch(item.label)}
                  >
                    {item.label}
                    <b>{item.count}</b>
                  </button>
                ))}
              </div>
              <span>Relationships</span>
              <div>
                {schema.relationship_types.slice(0, 12).map((item) => (
                  <em key={`${item.zone}:${item.type}`}>
                    {item.type} <b>{item.count}</b>
                  </em>
                ))}
              </div>
            </div>
          ) : null}
        </aside>

        <div className="datapaw-graph-main">
          {mode === "query" ? (
            <form className="datapaw-cypher" onSubmit={runCypher}>
              <label htmlFor="datapaw-cypher-input">Read-only Cypher</label>
              <textarea
                id="datapaw-cypher-input"
                value={cypher}
                onChange={(event) => setCypher(event.target.value)}
                spellCheck={false}
              />
              <button type="submit" disabled={loading}>
                Run query{" "}
                <span>
                  <PlayIcon size={11} />
                </span>
              </button>
            </form>
          ) : null}
          {error ? <div className="datapaw-error-banner">{error}</div> : null}
          <div className="datapaw-graph-canvas" ref={canvasRef}>
            {loading ? (
              <div className="datapaw-loading">Loading graph…</div>
            ) : null}
            {!loading && nodes.length === 0 ? (
              <div className="datapaw-graph-empty">
                No graph nodes matched this view.
              </div>
            ) : null}
            <svg
              viewBox={`0 0 ${Math.max(size.width, 480)} ${Math.max(
                size.height,
                360,
              )}`}
              role="img"
              aria-label={`Context graph with ${nodes.length} nodes and ${edges.length} relationships`}
              onClick={() => setSelectedNodeId("")}
            >
              <defs>
                <marker
                  id="datapaw-arrow"
                  markerWidth="8"
                  markerHeight="8"
                  refX="7"
                  refY="3"
                  orient="auto"
                >
                  <path d="M0,0 L0,6 L8,3 z" fill="#a9b1c1" />
                </marker>
              </defs>
              <g className="datapaw-edges">
                {edges.map((edge) => {
                  const source = positions.get(edge.source);
                  const target = positions.get(edge.target);
                  if (!source || !target) return null;
                  return (
                    <g key={edge.id}>
                      <line
                        x1={source.x}
                        y1={source.y}
                        x2={target.x}
                        y2={target.y}
                        markerEnd="url(#datapaw-arrow)"
                      />
                      <text
                        x={(source.x + target.x) / 2}
                        y={(source.y + target.y) / 2 - 5}
                      >
                        {compactLabel(edge.type, 18)}
                      </text>
                    </g>
                  );
                })}
              </g>
              <g className="datapaw-nodes">
                {positioned.map((node) => {
                  const selected = selectedNodeId === node.id;
                  const fill = ZONE_COLORS[node.zone] || ZONE_COLORS.unknown;
                  return (
                    <g
                      className={selected ? "is-selected" : ""}
                      key={node.id}
                      transform={`translate(${node.x},${node.y})`}
                      onClick={(event) => {
                        event.stopPropagation();
                        setSelectedNodeId(node.id);
                      }}
                      role="button"
                      tabIndex={0}
                    >
                      <circle r={selected ? 24 : 19} fill={fill} />
                      <text className="datapaw-node-label" y={34}>
                        {compactLabel(node.label)}
                      </text>
                      <text className="datapaw-node-type" y={49}>
                        {compactLabel(node.type, 16)}
                      </text>
                    </g>
                  );
                })}
              </g>
            </svg>
          </div>
          <footer className="datapaw-graph-footer">
            <span>{nodes.length} nodes</span>
            <span>{edges.length} relationships</span>
            <span>
              {selectedSource?.datasource_name ||
                selectedSource?.datasource_id ||
                "All sources"}
            </span>
          </footer>
          {queryResult && queryResult.rows.length > 0 ? (
            <div className="datapaw-query-table">
              <div>
                <b>{queryResult.count} rows</b>
                <span>{queryResult.summary?.elapsed_ms ?? 0} ms</span>
              </div>
              <table>
                <thead>
                  <tr>
                    {queryResult.columns.map((column) => (
                      <th key={column}>{column}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {queryResult.rows.slice(0, 50).map((row, rowIndex) => (
                    <tr key={rowIndex}>
                      {queryResult.columns.map((column) => (
                        <td key={column}>
                          {typeof row[column] === "object"
                            ? JSON.stringify(row[column])
                            : String(row[column] ?? "")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>

        {selectedNode ? (
          <aside className="datapaw-properties">
            <button
              type="button"
              onClick={() => setSelectedNodeId("")}
              aria-label="Close properties"
            >
              <CloseIcon size={14} />
            </button>
            <span className="datapaw-eyebrow">{selectedNode.zone}</span>
            <h2>{selectedNode.label}</h2>
            <p>{selectedNode.type}</p>
            <dl>
              <div>
                <dt>key</dt>
                <dd>{selectedNode.id}</dd>
              </div>
              {Object.entries(selectedNode.properties)
                .slice(0, 24)
                .map(([key, value]) => (
                  <div key={key}>
                    <dt>{key}</dt>
                    <dd>
                      {typeof value === "object"
                        ? JSON.stringify(value)
                        : String(value ?? "")}
                    </dd>
                  </div>
                ))}
            </dl>
          </aside>
        ) : null}
      </div>
    </section>
  );
}
