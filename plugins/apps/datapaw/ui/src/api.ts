import type {
  PawAppSdk,
  PawDependencySnapshot,
  PawRequestOptions,
} from "./sdk";

export type GraphZone = "all" | "knowledge" | "trace" | "metadata";

export interface ApiGraphNode {
  key?: string;
  id?: string;
  label: string;
  zone?: string;
  display_name?: string;
  properties?: Record<string, unknown>;
  group?: string;
}

export interface ApiGraphEdge {
  source_key?: string;
  target_key?: string;
  rel_type?: string;
  properties?: Record<string, unknown>;
  from?: string;
  to?: string;
  type?: string;
  props?: Record<string, unknown>;
}

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  zone: string;
  properties: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  properties: Record<string, unknown>;
}

export interface GraphData {
  nodes: ApiGraphNode[];
  edges: ApiGraphEdge[];
}

interface ApiEnvelope<T> {
  ok: boolean;
  data: T | null;
  error: { message?: string } | null;
  meta?: {
    total: number;
    page: number;
    page_size: number;
    has_more: boolean;
  } | null;
}

export interface GraphSchema {
  node_labels: Array<{ label: string; count: number; zone?: string }>;
  relationship_types: Array<{
    type: string;
    count: number;
    zone?: string;
    source_zone?: string;
  }>;
}

export interface CypherResponse {
  rows: Record<string, unknown>[];
  count: number;
  truncated: boolean;
  columns: string[];
  graph: GraphData | null;
  summary?: {
    result_type?: string;
    node_count?: number;
    edge_count?: number;
    elapsed_ms?: number;
  };
}

export interface DataSourceMetadata {
  datasource_id: string;
  datasource_name: string;
  datasource_type: string;
}

export interface DataSourcePage {
  records: DataSourceMetadata[];
  total: number;
  page: number;
  size: number;
}

export type SemanticResourceKey =
  | "domains"
  | "datasets"
  | "columns"
  | "dimensions"
  | "bindings"
  | "metrics"
  | "formulas";

export interface SemanticRecord {
  [key: string]: unknown;
  id?: number;
  domain_id?: number | null;
  dataset_id?: number | null;
  metric_id?: number | null;
  datasource_id?: string | null;
  datasource_name?: string | null;
  domain_name?: string | null;
  display_name?: string | null;
  dataset_name?: string | null;
  column_name?: string | null;
  dimension_name?: string | null;
  metric_name?: string | null;
  description?: string | null;
  formula?: string | null;
}

export interface SemanticPage<T> {
  records: T[];
  total: number;
  page: number;
  size: number;
}

export interface WeaveTask extends SemanticRecord {
  task_id?: string | null;
  task_name?: string | null;
  weave_mode?: string | null;
  status?: string | null;
  error_msg?: string | null;
  created_at?: string | null;
}

export interface SemanticCatalogSnapshot {
  datasource_id: string;
  fetched_at: string;
  resources: Record<SemanticResourceKey, SemanticRecord[]>;
  totals: Record<SemanticResourceKey, number>;
  weave_tasks: WeaveTask[];
}

interface RawDataSourcePage {
  records: Array<{
    datasource_id?: string | null;
    datasource_name?: string | null;
    datasource_type?: string | null;
  }>;
  total: number;
  page: number;
  size: number;
}

export interface AppStatus {
  app: "datapaw";
  service: { name: string; ready: boolean; mode: "managed" | "external" };
  health: Record<string, unknown> | null;
  skills_available: boolean;
  skills?: {
    available: boolean;
    count: number;
    providers: number;
  };
  dependencies: PawDependencySnapshot;
}

function unwrap<T>(response: ApiEnvelope<T>): T {
  if (!response.ok || response.data === null) {
    throw new Error(response.error?.message || "QwenPaw-Data request failed");
  }
  return response.data;
}

export function normalizeNode(node: ApiGraphNode): GraphNode {
  const explorerShape = Boolean(node.group);
  const id = String(
    explorerShape ? node.id ?? node.key ?? "" : node.key ?? node.id ?? "",
  );
  return {
    id,
    label: String(
      explorerShape ? node.label || id : node.display_name || node.label || id,
    ),
    type: String(explorerShape ? node.group : node.label || "Node"),
    zone: String(node.zone || "unknown"),
    properties: node.properties ?? {},
  };
}

export function normalizeEdge(edge: ApiGraphEdge, index = 0): GraphEdge {
  const source = String(edge.source_key ?? edge.from ?? "");
  const target = String(edge.target_key ?? edge.to ?? "");
  const type = String(edge.rel_type ?? edge.type ?? "RELATED");
  return {
    id: `${source}:${type}:${target}:${index}`,
    source,
    target,
    type,
    properties: edge.properties ?? edge.props ?? {},
  };
}

export function createQwenPawDataApi(paw: PawAppSdk) {
  const contextGet = <T>(path: string, options?: PawRequestOptions) =>
    paw.api.get<T>(`/context/${path.replace(/^\//, "")}`, options);
  const contextPost = <T>(path: string, body?: unknown) =>
    paw.api.post<T>(`/context/${path.replace(/^\//, "")}`, body);
  const semanticPage = <T>(
    path: string,
    datasourceId?: string,
  ): Promise<SemanticPage<T>> =>
    contextGet<SemanticPage<T>>(`semantic-config/${path}`, {
      query: {
        page: 1,
        size: 200,
        ...(datasourceId ? { datasource_id: datasourceId } : {}),
      },
    });

  return {
    status: () => paw.api.get<AppStatus>("/status"),
    listDataSources: async (): Promise<DataSourcePage> => {
      const response = await contextGet<RawDataSourcePage>(
        "v1/cm/datasources",
        {
          query: { page: 1, size: 200 },
        },
      );
      return {
        ...response,
        records: (response.records ?? [])
          .filter((source) => Boolean(source.datasource_id))
          .map((source) => ({
            datasource_id: String(source.datasource_id),
            datasource_name: String(
              source.datasource_name || source.datasource_id,
            ),
            datasource_type: String(source.datasource_type || "unknown"),
          })),
      };
    },
    semanticCatalog: async (
      datasourceId?: string,
    ): Promise<SemanticCatalogSnapshot> => {
      const [
        domains,
        datasets,
        columns,
        dimensions,
        bindings,
        metrics,
        formulas,
        weaveTasks,
      ] = await Promise.all([
        semanticPage<SemanticRecord>("biz-domain", datasourceId),
        semanticPage<SemanticRecord>("dataset-meta", datasourceId),
        semanticPage<SemanticRecord>("dataset-column-meta", datasourceId),
        semanticPage<SemanticRecord>("dimension", datasourceId),
        semanticPage<SemanticRecord>("dataset-dimension", datasourceId),
        semanticPage<SemanticRecord>("metric-lib", datasourceId),
        semanticPage<SemanticRecord>("metric-formula-lib", datasourceId),
        semanticPage<WeaveTask>("weave-task"),
      ]);
      const resources = {
        domains: domains.records,
        datasets: datasets.records,
        columns: columns.records,
        dimensions: dimensions.records,
        bindings: bindings.records,
        metrics: metrics.records,
        formulas: formulas.records,
      };
      return {
        datasource_id: datasourceId || "",
        fetched_at: new Date().toISOString(),
        resources,
        totals: {
          domains: domains.total,
          datasets: datasets.total,
          columns: columns.total,
          dimensions: dimensions.total,
          bindings: bindings.total,
          metrics: metrics.total,
          formulas: formulas.total,
        },
        weave_tasks: weaveTasks.records.filter(
          (task) => !datasourceId || task.datasource_id === datasourceId,
        ),
      };
    },
    graphSchema: async () =>
      unwrap(
        await contextGet<ApiEnvelope<GraphSchema>>("v1/admin/explorer/schema"),
      ),
    globalGraph: async (zone: GraphZone, datasourceId?: string) =>
      unwrap(
        await contextPost<ApiEnvelope<GraphData>>(
          "v1/admin/explorer/global-graph",
          {
            max_nodes: 120,
            max_edges: 240,
            skeleton: true,
            domain_roots_only: zone === "metadata",
            task_roots: zone === "trace",
            max_task_roots: 12,
            zone_mode: zone,
            datasource_id: zone === "knowledge" ? "" : datasourceId || "",
          },
        ),
      ),
    searchGraph: async (query: string, zone: GraphZone) =>
      unwrap(
        await contextPost<
          ApiEnvelope<GraphData & { hit_nodes?: ApiGraphNode[] }>
        >("v1/admin/explorer/search-subgraph", {
          query,
          scope: zone === "all" ? ["metadata", "trace", "knowledge"] : [zone],
          match_mode: "fuzzy",
          hops: 1,
          limit: 60,
        }),
      ),
    executeCypher: async (cypher: string, datasourceId?: string) =>
      unwrap(
        await contextPost<ApiEnvelope<CypherResponse>>("v1/admin/cypher", {
          cypher,
          response_format: "auto",
          limit: 100,
          ...(datasourceId ? { datasource_id: datasourceId } : {}),
        }),
      ),
  };
}
