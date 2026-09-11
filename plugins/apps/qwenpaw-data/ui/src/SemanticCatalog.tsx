import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  DataSourceMetadata,
  SemanticCatalogSnapshot,
  SemanticRecord,
  SemanticResourceKey,
} from "./api";
import { PageHeader } from "./PageHeader";

interface SemanticApi {
  semanticCatalog(datasourceId?: string): Promise<SemanticCatalogSnapshot>;
}

interface ResourceDefinition {
  key: SemanticResourceKey;
  command: string;
  label: string;
  singular: string;
}

const RESOURCES: ResourceDefinition[] = [
  { key: "domains", command: "domain", label: "Domains", singular: "Domain" },
  {
    key: "datasets",
    command: "dataset",
    label: "Datasets",
    singular: "Dataset",
  },
  { key: "columns", command: "column", label: "Columns", singular: "Column" },
  {
    key: "dimensions",
    command: "dimension",
    label: "Dimensions",
    singular: "Dimension",
  },
  { key: "metrics", command: "metric", label: "Metrics", singular: "Metric" },
  {
    key: "formulas",
    command: "formula",
    label: "Formulas",
    singular: "Formula",
  },
  {
    key: "bindings",
    command: "binding",
    label: "Bindings",
    singular: "Binding",
  },
];

function text(record: SemanticRecord, ...keys: string[]): string {
  for (const key of keys) {
    const value = record[key];
    if (value !== null && value !== undefined && String(value).trim()) {
      return String(value);
    }
  }
  return "—";
}

function recordTitle(
  resource: SemanticResourceKey,
  record: SemanticRecord,
): string {
  switch (resource) {
    case "domains":
      return text(record, "display_name", "domain_name");
    case "datasets":
      return text(record, "dataset_name");
    case "columns":
      return text(record, "column_name", "column_name_cn");
    case "dimensions":
      return text(record, "dimension_name");
    case "metrics":
      return text(record, "metric_name");
    case "formulas":
      return text(record, "metric_name", "formula");
    case "bindings":
      return text(record, "dimension_name", "dataset_name");
  }
}

function recordContext(
  resource: SemanticResourceKey,
  record: SemanticRecord,
): string {
  if (resource === "columns") {
    return text(record, "dataset_name", "domain_name", "datasource_name");
  }
  if (resource === "formulas") {
    return text(record, "dataset_name", "domain_name", "datasource_name");
  }
  if (resource === "bindings") {
    return text(record, "dataset_name", "domain_name", "datasource_name");
  }
  return text(record, "domain_name", "datasource_name", "datasource_id");
}

function recordDefinition(
  resource: SemanticResourceKey,
  record: SemanticRecord,
): string {
  switch (resource) {
    case "domains":
      return text(record, "description", "aliases");
    case "datasets":
      return text(record, "dataset_comment", "sql_content", "dataset_type");
    case "columns":
      return text(record, "column_comment", "data_type", "column_type");
    case "dimensions":
      return text(record, "description", "synonyms", "enums");
    case "metrics":
      return text(record, "description", "unit", "synonyms");
    case "formulas":
      return text(record, "formula", "formula_evidence");
    case "bindings":
      return text(record, "calculate_expr", "dimension_type", "data_type");
  }
}

function recordId(record: SemanticRecord, index: number): string {
  return text(
    record,
    "id",
    "domain_id",
    "dataset_id",
    "metric_id",
    "column_name",
  ) === "—"
    ? String(index)
    : text(record, "id", "domain_id", "dataset_id", "metric_id", "column_name");
}

export function SemanticCatalog({
  api,
  selectedSource,
}: {
  api: SemanticApi;
  selectedSource?: DataSourceMetadata;
}) {
  const [snapshot, setSnapshot] = useState<SemanticCatalogSnapshot>();
  const [activeResource, setActiveResource] =
    useState<SemanticResourceKey>("metrics");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const requestRef = useRef(0);
  const datasourceId = selectedSource?.datasource_id;

  const refresh = useCallback(
    async (initial = false) => {
      const requestId = ++requestRef.current;
      if (initial) setLoading(true);
      else setRefreshing(true);
      try {
        const next = await api.semanticCatalog(datasourceId);
        if (requestRef.current !== requestId) return;
        setSnapshot(next);
        setError("");
      } catch (nextError) {
        if (requestRef.current !== requestId) return;
        setError(
          nextError instanceof Error ? nextError.message : String(nextError),
        );
      } finally {
        if (requestRef.current === requestId) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    },
    [api, datasourceId],
  );

  useEffect(() => {
    void refresh(true);
    const interval = window.setInterval(() => void refresh(false), 5_000);
    return () => {
      window.clearInterval(interval);
      requestRef.current += 1;
    };
  }, [refresh]);

  const active =
    RESOURCES.find((resource) => resource.key === activeResource) ??
    RESOURCES[0];
  const records = snapshot?.resources[activeResource] ?? [];
  const totalObjects = useMemo(
    () =>
      snapshot
        ? Object.values(snapshot.totals).reduce(
            (total, value) => total + value,
            0,
          )
        : 0,
    [snapshot],
  );
  const cliBaseUrl = `${window.location.origin}/api/qwenpaw-data/context`;
  const datasourceFlag = datasourceId ? ` --datasource-id ${datasourceId}` : "";
  const cliCommand = `QWENPAW_DATA_CM_BASE_URL=${cliBaseUrl} qwenpaw-data semantic ${active.command} list${datasourceFlag} --all`;
  const lastUpdated = snapshot
    ? new Date(snapshot.fetched_at).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : "Not synced";

  return (
    <section className="qwenpaw-data-semantic">
      <PageHeader
        eyebrow="Configuration state"
        title="Semantic model"
        description="Live view of datasource and semantic changes made through the QwenPaw-Data CLI."
        actions={
          <div className="qwenpaw-data-live-controls">
            <span className="qwenpaw-data-live-status" aria-live="polite">
              <i /> {refreshing ? "Syncing…" : `Live · ${lastUpdated}`}
            </span>
            <button
              className="qwenpaw-data-secondary-button"
              type="button"
              onClick={() => void refresh(false)}
              disabled={refreshing}
            >
              Refresh
            </button>
          </div>
        }
      />

      <div className="qwenpaw-data-semantic__scope">
        <span>Scope</span>
        <b>
          {selectedSource?.datasource_name ||
            selectedSource?.datasource_id ||
            "All configured data sources"}
        </b>
        <small>{datasourceId || "No datasource filter"}</small>
      </div>

      {error ? <div className="qwenpaw-data-error-banner">{error}</div> : null}

      <div className="qwenpaw-data-semantic-summary" aria-busy={loading}>
        <article>
          <span>Semantic objects</span>
          <b>{loading ? "…" : totalObjects}</b>
        </article>
        <article>
          <span>Business domains</span>
          <b>{loading ? "…" : snapshot?.totals.domains ?? 0}</b>
        </article>
        <article>
          <span>Datasets</span>
          <b>{loading ? "…" : snapshot?.totals.datasets ?? 0}</b>
        </article>
        <article>
          <span>Metrics</span>
          <b>{loading ? "…" : snapshot?.totals.metrics ?? 0}</b>
        </article>
        <article>
          <span>Weave tasks</span>
          <b>{loading ? "…" : snapshot?.weave_tasks.length ?? 0}</b>
        </article>
      </div>

      <div className="qwenpaw-data-semantic-layout">
        <aside className="qwenpaw-data-semantic-nav">
          <span>Resource</span>
          {RESOURCES.map((resource) => (
            <button
              type="button"
              key={resource.key}
              className={activeResource === resource.key ? "is-active" : ""}
              onClick={() => setActiveResource(resource.key)}
            >
              <span>{resource.label}</span>
              <b>{snapshot?.totals[resource.key] ?? 0}</b>
            </button>
          ))}
        </aside>

        <div className="qwenpaw-data-semantic-table-wrap">
          <div className="qwenpaw-data-semantic-table-heading">
            <div>
              <span className="qwenpaw-data-eyebrow">{active.singular}</span>
              <h2>{active.label}</h2>
            </div>
            <span>{snapshot?.totals[activeResource] ?? 0} configured</span>
          </div>
          {loading ? (
            <div className="qwenpaw-data-semantic-placeholder">
              Loading semantic configuration…
            </div>
          ) : records.length ? (
            <div className="qwenpaw-data-semantic-table-scroll">
              <table className="qwenpaw-data-semantic-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Context</th>
                    <th>Definition</th>
                  </tr>
                </thead>
                <tbody>
                  {records.map((record, index) => (
                    <tr key={`${activeResource}:${recordId(record, index)}`}>
                      <td>
                        <b>{recordTitle(activeResource, record)}</b>
                        <small>#{recordId(record, index)}</small>
                      </td>
                      <td>{recordContext(activeResource, record)}</td>
                      <td>{recordDefinition(activeResource, record)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="qwenpaw-data-semantic-placeholder">
              <b>No {active.label.toLowerCase()} in this scope.</b>
              <span>
                Create or import them with the CLI; this view refreshes every
                five seconds.
              </span>
            </div>
          )}
        </div>
      </div>

      {snapshot?.weave_tasks.length ? (
        <section className="qwenpaw-data-weave-tasks">
          <div>
            <span className="qwenpaw-data-eyebrow">Publishing</span>
            <h2>Recent weave tasks</h2>
          </div>
          <ul>
            {snapshot.weave_tasks.slice(0, 8).map((task, index) => (
              <li key={task.task_id || task.id || index}>
                <i
                  className={`is-${String(
                    task.status || "unknown",
                  ).toLowerCase()}`}
                />
                <span>
                  <b>{task.task_name || task.task_id || "Semantic weave"}</b>
                  <small>
                    {task.datasource_name ||
                      task.datasource_id ||
                      "All sources"}
                  </small>
                </span>
                <em>{task.status || "unknown"}</em>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <details className="qwenpaw-data-cli-bridge">
        <summary>CLI connection</summary>
        <p>
          Point the new CLI at this portal to read and change the same managed
          semantic store.
        </p>
        <code>{cliCommand}</code>
      </details>
    </section>
  );
}
