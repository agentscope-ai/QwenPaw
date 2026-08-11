import { useCallback, useEffect, useMemo, useState } from "react";

import {
  createQwenPawDataApi,
  type AppStatus,
  type DataSourceMetadata,
} from "./api";
import { ChatWorkspace } from "./ChatWorkspace";
import { DataSources } from "./DataSources";
import { GraphExplorer } from "./GraphExplorer";
import { SemanticCatalog } from "./SemanticCatalog";
import type { PawAppSdk } from "./sdk";
import type { PawDependencyAction, PawDependencySnapshot } from "./sdk";
import { buildAppStatusModel } from "./status";

type Page = "analysis" | "semantic" | "graph" | "sources";

const NAVIGATION: Array<{ id: Page; icon: string; label: string }> = [
  { id: "analysis", icon: "✦", label: "Analysis" },
  { id: "semantic", icon: "◇", label: "Semantic model" },
  { id: "graph", icon: "⌘", label: "Context graph" },
  { id: "sources", icon: "◉", label: "Data sources" },
];

function StatusPanel({
  status,
  dependencies,
  selectedSourceId,
  onOpenDetails,
}: {
  status?: AppStatus;
  dependencies?: PawDependencySnapshot;
  selectedSourceId: string;
  onOpenDetails(): void;
}) {
  const model = buildAppStatusModel(status, dependencies, selectedSourceId);
  return (
    <div className={`datapaw-status-panel is-${model.tone}`}>
      <div className="datapaw-status-panel__summary">
        <i aria-hidden="true" />
        <span>
          <b>{model.label}</b>
          <small>{model.detail}</small>
        </span>
      </div>
      <ul>
        {model.categories.map((category) => (
          <li className={`is-${category.tone}`} key={category.id}>
            <i aria-hidden="true" />
            <span>{category.label}</span>
            <small>{category.detail}</small>
          </li>
        ))}
      </ul>
      <div className="datapaw-status-panel__footer">
        <span>
          {model.checkedAt
            ? `Checked ${new Date(model.checkedAt).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              })}`
            : "Waiting for first check"}
        </span>
        <button type="button" onClick={onOpenDetails}>
          Details →
        </button>
      </div>
    </div>
  );
}

export function App({ paw }: { paw: PawAppSdk }) {
  const api = useMemo(() => createQwenPawDataApi(paw), [paw]);
  const [page, setPage] = useState<Page>("analysis");
  const [status, setStatus] = useState<AppStatus>();
  const [dependencies, setDependencies] = useState<PawDependencySnapshot>();
  const [sources, setSources] = useState<DataSourceMetadata[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [sourceLoading, setSourceLoading] = useState(true);
  const [sourceError, setSourceError] = useState("");
  const [sourcesUpdatedAt, setSourcesUpdatedAt] = useState<Date>();

  const loadSources = useCallback(
    async (background = false) => {
      if (!background) setSourceLoading(true);
      setSourceError("");
      try {
        const response = await api.listDataSources();
        setSources(response.records ?? []);
        setSourcesUpdatedAt(new Date());
      } catch (error) {
        setSourceError(error instanceof Error ? error.message : String(error));
      } finally {
        if (!background) setSourceLoading(false);
      }
    },
    [api],
  );

  useEffect(() => {
    let cancelled = false;
    void Promise.allSettled([
      api.status().then((nextStatus) => {
        if (!cancelled) {
          setStatus(nextStatus);
          setDependencies(nextStatus.dependencies);
        }
      }),
      paw.storage.get<string>("selected-source", "").then((stored) => {
        if (!cancelled) setSelectedId(stored || "");
      }),
      loadSources(),
    ]);
    return () => {
      cancelled = true;
    };
  }, [api, loadSources, paw.storage]);

  useEffect(() => {
    const interval = window.setInterval(() => void loadSources(true), 5_000);
    return () => window.clearInterval(interval);
  }, [loadSources]);

  useEffect(() => {
    const subscription = paw.dependencies.subscribe(setDependencies, {
      intervalMs: 10_000,
    });
    return () => subscription.dispose();
  }, [paw.dependencies]);

  const selectedSource = sources.find(
    (source) => source.datasource_id === selectedId,
  );

  async function selectSource(id: string) {
    setSelectedId(id);
    await paw.storage.set("selected-source", id);
    await paw.toast(
      id ? "Default data source updated" : "Using all available context",
      "success",
    );
  }

  async function runDependencyAction(
    dependencyId: string,
    action: PawDependencyAction,
  ) {
    if (action === "check") {
      await paw.dependencies.check(dependencyId);
    } else {
      await paw.dependencies.action(dependencyId, action, {
        idempotencyKey: `${dependencyId}:${action}:${Date.now()}`,
      });
    }
    setDependencies(await paw.dependencies.list(true));
  }

  return (
    <div className="datapaw-app">
      <aside className="datapaw-nav">
        <div className="datapaw-brand">
          <div className="datapaw-brand__mark">
            <img
              src="/api/frontend_plugin/datapaw/files/ui/dist/app/logo-mark-v4.png"
              alt=""
            />
          </div>
          <div>
            <b>QwenPaw-Data</b>
            <span>Self-Evolving Agentic BI</span>
          </div>
        </div>
        <nav aria-label="QwenPaw-Data navigation">
          {NAVIGATION.map((item) => (
            <button
              key={item.id}
              type="button"
              className={page === item.id ? "is-active" : ""}
              onClick={() => setPage(item.id)}
            >
              <i aria-hidden="true">{item.icon}</i>
              <span>{item.label}</span>
            </button>
          ))}
        </nav>
        <div className="datapaw-nav__bottom">
          <StatusPanel
            status={status}
            dependencies={dependencies}
            selectedSourceId={selectedId}
            onOpenDetails={() => setPage("sources")}
          />
        </div>
      </aside>
      <main className="datapaw-main">
        <div hidden={page !== "analysis"}>
          <ChatWorkspace paw={paw} selectedSource={selectedSource} />
        </div>
        {page === "semantic" ? (
          <SemanticCatalog api={api} selectedSource={selectedSource} />
        ) : null}
        {page === "graph" ? (
          <GraphExplorer api={api} selectedSource={selectedSource} />
        ) : null}
        {page === "sources" ? (
          <DataSources
            sources={sources}
            selectedId={selectedId}
            loading={sourceLoading}
            error={sourceError}
            onSelect={(id) => void selectSource(id)}
            onReload={() => void loadSources()}
            lastUpdatedAt={sourcesUpdatedAt}
            dependencies={dependencies?.dependencies ?? []}
            onDependencyAction={runDependencyAction}
          />
        ) : null}
      </main>
    </div>
  );
}
