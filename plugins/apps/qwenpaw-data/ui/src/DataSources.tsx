import type { PawDependencyAction, PawDependencyStatus } from "./sdk";
import { useState } from "react";
import { PageHeader } from "./PageHeader";
import { groupDependencies } from "./status";

export function DataSources({
  selectedId,
  error,
  onReload,
  onOpenManage,
  lastUpdatedAt,
  dependencies,
  onDependencyAction,
}: {
  selectedId: string;
  error: string;
  onReload(): void;
  onOpenManage(): void;
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
    <section className="qwenpaw-data-sources">
      <PageHeader
        eyebrow="Diagnostics"
        title="Runtime status"
        description="Health of the managed services and connections behind QwenPaw-Data. Add or edit connections in Manage."
        actions={
          <div className="qwenpaw-data-live-controls">
            <span className="qwenpaw-data-live-status">
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
              className="qwenpaw-data-secondary-button"
              type="button"
              onClick={onReload}
            >
              Reload
            </button>
            <button
              className="qwenpaw-data-secondary-button"
              type="button"
              onClick={onOpenManage}
            >
              Manage sources →
            </button>
          </div>
        }
      />

      {error ? <div className="qwenpaw-data-error-banner">{error}</div> : null}
      <div className="qwenpaw-data-dependency-sections">
        {groupDependencies(dependencies).map((group) => (
          <section key={group.id}>
            <header>
              <div>
                <h2>{group.label}</h2>
                <p>{group.description}</p>
              </div>
              <span>{group.dependencies.length}</span>
            </header>
            <div className="qwenpaw-data-dependency-grid">
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
                    className={`qwenpaw-data-dependency-card is-${dependency.health}`}
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
                      className="qwenpaw-data-inline-action"
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
    </section>
  );
}
