import type { DataSourceMetadata } from "./api";
import type { PawDependencyAction, PawDependencyStatus } from "./sdk";
import { useState } from "react";
import { groupDependencies } from "./status";

function sourceInitial(source: DataSourceMetadata): string {
  return (source.datasource_name || source.datasource_id || "D")
    .slice(0, 1)
    .toUpperCase();
}

export function DataSources({
  sources,
  selectedId,
  loading,
  error,
  onSelect,
  onReload,
  lastUpdatedAt,
  dependencies,
  onDependencyAction,
}: {
  sources: DataSourceMetadata[];
  selectedId: string;
  loading: boolean;
  error: string;
  onSelect(id: string): void;
  onReload(): void;
  lastUpdatedAt?: Date;
  dependencies: PawDependencyStatus[];
  onDependencyAction(id: string, action: PawDependencyAction): Promise<void>;
}) {
  const [activeAction, setActiveAction] = useState("");

  async function runAction(id: string, action: PawDependencyAction) {
    const actionKey = `${id}:${action}`;
    setActiveAction(actionKey);
    try {
      await onDependencyAction(id, action);
    } finally {
      setActiveAction("");
    }
  }

  return (
    <section className="datapaw-sources">
      <header className="datapaw-section-heading">
        <div>
          <span className="datapaw-eyebrow">Query scope</span>
          <h1>Data sources</h1>
          <p>Select the default source for chat and graph exploration.</p>
        </div>
        <div className="datapaw-live-controls">
          <span className="datapaw-live-status">
            <i /> Live
            {lastUpdatedAt
              ? ` · ${lastUpdatedAt.toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                  second: "2-digit",
                })}`
              : ""}
          </span>
          <button
            className="datapaw-secondary-button"
            type="button"
            onClick={onReload}
          >
            Reload
          </button>
        </div>
      </header>

      {error ? <div className="datapaw-error-banner">{error}</div> : null}
      <div className="datapaw-dependency-sections">
        {groupDependencies(dependencies).map((group) => (
          <section key={group.id}>
            <header>
              <div>
                <h2>{group.label}</h2>
                <p>{group.description}</p>
              </div>
              <span>{group.dependencies.length}</span>
            </header>
            <div className="datapaw-dependency-grid">
              {group.dependencies.map((dependency) => {
                const primaryAction =
                  dependency.actions.includes("start") &&
                  dependency.health === "unavailable"
                    ? "start"
                    : "check";
                const actionKey = `${dependency.id}:${primaryAction}`;
                const selectedDependency =
                  dependency.id === `source:${selectedId}`;
                return (
                  <article
                    className={`datapaw-dependency-card is-${dependency.health}`}
                    key={dependency.id}
                  >
                    <div>
                      <i aria-hidden="true" />
                      <span>
                        <b>{dependency.display_name}</b>
                        <small>
                          {dependency.health} · {dependency.lifecycle}
                          {dependency.latency_ms !== null
                            ? ` · ${dependency.latency_ms}ms`
                            : ""}
                        </small>
                      </span>
                      <em>
                        {dependency.required
                          ? "Required"
                          : selectedDependency
                          ? "Active scope"
                          : "Optional"}
                      </em>
                    </div>
                    <p>{dependency.remediation || dependency.message}</p>
                    <button
                      type="button"
                      className="datapaw-inline-action"
                      disabled={activeAction === actionKey}
                      onClick={() =>
                        void runAction(dependency.id, primaryAction)
                      }
                    >
                      {activeAction === actionKey
                        ? "Working…"
                        : primaryAction === "start"
                        ? "Start"
                        : "Recheck"}
                    </button>
                  </article>
                );
              })}
            </div>
          </section>
        ))}
      </div>
      <div className="datapaw-source-grid" aria-busy={loading}>
        <button
          type="button"
          className={`datapaw-source-card ${selectedId ? "" : "is-selected"}`}
          onClick={() => onSelect("")}
        >
          <span className="datapaw-source-card__icon">∞</span>
          <span>
            <b>All available context</b>
            <small>Let the analysis choose from configured sources</small>
          </span>
          <i>{selectedId ? "" : "Selected"}</i>
        </button>
        {sources.map((source) => (
          <button
            type="button"
            className={`datapaw-source-card ${
              selectedId === source.datasource_id ? "is-selected" : ""
            }`}
            key={source.datasource_id}
            onClick={() => onSelect(source.datasource_id)}
          >
            <span className="datapaw-source-card__icon">
              {sourceInitial(source)}
            </span>
            <span>
              <b>{source.datasource_name || source.datasource_id}</b>
              <small>
                {source.datasource_type || "data source"} ·{" "}
                {source.datasource_id}
              </small>
            </span>
            <i>{selectedId === source.datasource_id ? "Selected" : ""}</i>
          </button>
        ))}
      </div>
      {!loading && sources.length === 0 ? (
        <div className="datapaw-empty-panel">
          <strong>No data sources configured yet.</strong>
          <span>
            Add a source with the QwenPaw-Data CLI. This page refreshes every
            five seconds.
          </span>
        </div>
      ) : null}
    </section>
  );
}
