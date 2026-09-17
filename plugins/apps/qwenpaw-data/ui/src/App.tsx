import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import {
  createQwenPawDataApi,
  type AppStatus,
  type DataSourceMetadata,
} from "./api";
import { ChatWorkspace } from "./ChatWorkspace";
import { Configure } from "./Configure";
import { DataSources } from "./DataSources";
import { EmbeddedConsole } from "./EmbeddedConsole";
import {
  LayoutGridIcon,
  SettingsIcon,
  SparklesIcon,
  WrenchIcon,
} from "./icons";
import {
  LanguageProvider,
  persistLanguage,
  resolveInitialLanguage,
  useT,
} from "./language";
import { WordmarkLogo } from "./LogoMark";
import type { PawAppSdk } from "./sdk";
import type { PawDependencyAction, PawDependencySnapshot } from "./sdk";
import { buildAppStatusModel } from "./status";
import {
  localeTag,
  translate,
  type Language,
  type StringKey,
  type StringParams,
} from "./strings";

type Page = "analysis" | "manage" | "configure" | "health";

const NAVIGATION: Array<{
  id: Page;
  icon: ReactNode;
  labelKey: StringKey;
}> = [
  { id: "analysis", icon: <SparklesIcon />, labelKey: "nav.analyze" },
  { id: "manage", icon: <LayoutGridIcon />, labelKey: "nav.manage" },
  { id: "configure", icon: <WrenchIcon />, labelKey: "nav.configure" },
];

/**
 * Default deep link into the embedded Context console (hash-routed build).
 * The console ships its own sidebar covering data sources, datasets,
 * dimensions, metrics, semantic weaving, and the CM graph.
 */
const CONSOLE_HOME = "/data-source";

/** localStorage key the embedded console's i18next reads at boot. */
const CONSOLE_LANGUAGE_KEY = "language";

function StatusPanel({
  status,
  dependencies,
  selectedSourceId,
  language,
  onOpenDetails,
}: {
  status?: AppStatus;
  dependencies?: PawDependencySnapshot;
  selectedSourceId: string;
  language: Language;
  onOpenDetails(): void;
}) {
  const t = useT();
  const model = buildAppStatusModel(
    status,
    dependencies,
    selectedSourceId,
    language,
  );
  return (
    <div
      className={`qwenpaw-data-status-panel is-clickable is-${model.tone}`}
      role="button"
      tabIndex={0}
      aria-label={t("status.openDetails")}
      onClick={onOpenDetails}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpenDetails();
        }
      }}
    >
      <div className="qwenpaw-data-status-panel__summary">
        <i aria-hidden="true" />
        <span>
          <b>{model.label}</b>
          {model.detail ? <small>{model.detail}</small> : null}
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
      <div className="qwenpaw-data-status-panel__footer">
        <span>
          {model.checkedAt
            ? t("status.checked", {
                time: new Date(model.checkedAt).toLocaleTimeString(
                  localeTag(language),
                  {
                    hour: "2-digit",
                    minute: "2-digit",
                  },
                ),
              })
            : t("status.waitingFirstCheck")}
        </span>
      </div>
    </div>
  );
}

export function App({ paw }: { paw: PawAppSdk }) {
  const api = useMemo(() => createQwenPawDataApi(paw), [paw]);
  const [page, setPage] = useState<Page>("analysis");
  const [consoleRoute, setConsoleRoute] = useState(CONSOLE_HOME);
  const [consoleEpoch, setConsoleEpoch] = useState(0);
  const [language, setLanguage] = useState<Language>(resolveInitialLanguage);
  const [status, setStatus] = useState<AppStatus>();
  const [dependencies, setDependencies] = useState<PawDependencySnapshot>();
  const [sources, setSources] = useState<DataSourceMetadata[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [sourceError, setSourceError] = useState("");
  const [sourcesUpdatedAt, setSourcesUpdatedAt] = useState<Date>();

  const loadSources = useCallback(
    async (background = false) => {
      setSourceError("");
      try {
        const response = await api.listDataSources();
        setSources(response.records ?? []);
        setSourcesUpdatedAt(new Date());
      } catch (error) {
        setSourceError(error instanceof Error ? error.message : String(error));
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
      translate(language, id ? "toast.sourceUpdated" : "toast.sourceAll"),
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

  function openConfiguration() {
    setPage("configure");
  }

  async function toggleLanguage() {
    const next = language === "zh" ? "en" : "zh";
    persistLanguage(next);
    setLanguage(next);
    // The embedded console reads the language at boot; remount it.
    setConsoleEpoch((epoch) => epoch + 1);
    await paw.toast(
      next === "zh"
        ? "界面语言已切换为中文"
        : "Interface language set to English",
      "success",
    );
  }

  const t = (key: StringKey, params?: StringParams) =>
    translate(language, key, params);

  return (
    <LanguageProvider value={language}>
      <div className="qwenpaw-data-app">
        <header className="qwenpaw-data-topbar">
          <WordmarkLogo />
          <div className="qwenpaw-data-topbar__actions">
            <button
              type="button"
              className="qwenpaw-data-topbar__icon"
              title={t("topbar.configuration")}
              aria-label={t("topbar.configuration")}
              onClick={openConfiguration}
            >
              <SettingsIcon size={18} />
            </button>
            <button
              type="button"
              title={language === "zh" ? "Switch to English" : "切换为中文"}
              aria-label="Switch language"
              onClick={() => void toggleLanguage()}
            >
              {language === "zh" ? "中" : "EN"}
            </button>
          </div>
        </header>
        <div className="qwenpaw-data-body">
          <aside className="qwenpaw-data-nav">
            <nav aria-label={t("nav.aria")}>
              {NAVIGATION.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={page === item.id ? "is-active" : ""}
                  onClick={() => setPage(item.id)}
                >
                  <i aria-hidden="true">{item.icon}</i>
                  <span>{t(item.labelKey)}</span>
                </button>
              ))}
            </nav>
            <div className="qwenpaw-data-nav__bottom">
              <StatusPanel
                status={status}
                dependencies={dependencies}
                selectedSourceId={selectedId}
                language={language}
                onOpenDetails={() => setPage("health")}
              />
            </div>
          </aside>
          <main className="qwenpaw-data-main">
            <div hidden={page !== "analysis"}>
              <ChatWorkspace
                paw={paw}
                selectedSource={selectedSource}
                sources={sources}
                selectedSourceId={selectedId}
                onSelectSource={(id) => void selectSource(id)}
              />
            </div>
            <div hidden={page !== "manage"}>
              <EmbeddedConsole
                key={consoleEpoch}
                route={consoleRoute}
                active={page === "manage"}
              />
            </div>
            {page === "configure" ? (
              <Configure paw={paw} onRestart={() => void loadSources()} />
            ) : null}
            {page === "health" ? (
              <DataSources
                selectedId={selectedId}
                error={sourceError}
                onReload={() => void loadSources()}
                onOpenManage={() => {
                  setConsoleRoute(CONSOLE_HOME);
                  setPage("manage");
                }}
                lastUpdatedAt={sourcesUpdatedAt}
                dependencies={dependencies?.dependencies ?? []}
                onDependencyAction={runDependencyAction}
              />
            ) : null}
          </main>
        </div>
      </div>
    </LanguageProvider>
  );
}
