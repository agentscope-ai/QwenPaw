import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Select, Space, Segmented } from "antd";
import { useTranslation } from "react-i18next";
import type { ReportResource } from "@/api/modules/communityReport";
import { fetchMarketPlugins } from "@/api/modules/pluginMarket";
import { marketApi } from "@/api/modules/market";
import {
  communityResourceIdentity as identity,
  pluginMarketResource,
  skillMarketResource,
} from "@/utils/communityResources";
import styles from "./index.module.less";

type Source = "plugins" | "skills";
const resourceKind = (item: ReportResource) =>
  item.origin.resource_type === "skill" ? "skill" : "plugin";
interface Results {
  items: ReportResource[];
  page: number;
  more: boolean;
  loading: boolean;
  failed: boolean;
}
const emptyResults = (): Results => ({
  items: [],
  page: 0,
  more: false,
  loading: true,
  failed: false,
});
const PAGE_SIZE = 20;

export function ResourcePicker({
  installed,
  selected,
  disabled,
  onChange,
}: {
  installed: ReportResource[];
  selected: ReportResource[];
  disabled: boolean;
  onChange: (resources: ReportResource[]) => void;
}) {
  const { t, i18n } = useTranslation();
  const [kind, setKind] = useState("plugin");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Record<Source, Results>>({
    plugins: emptyResults(),
    skills: emptyResults(),
  });
  const controller = useRef<AbortController>();
  const load = useCallback(
    async (source: Source, page: number, signal: AbortSignal) => {
      setResults((current) => ({
        ...current,
        [source]: { ...current[source], loading: true, failed: false },
      }));
      try {
        let items: ReportResource[];
        let more: boolean;
        if (source === "plugins") {
          const data = await fetchMarketPlugins(
            { search: query.trim(), page_number: page, page_size: PAGE_SIZE },
            { signal },
          );
          items = data.plugins.flatMap(
            (entry) => pluginMarketResource(entry) || [],
          );
          more = page * PAGE_SIZE < data.total;
        } else {
          const data = await marketApi.searchMarket(
            {
              query: query.trim(),
              provider_pages: { qwenpaw: page },
              limit: PAGE_SIZE,
              lang: i18n.language,
            },
            { signal },
          );
          if (data.errors.some((error) => error.provider === "qwenpaw"))
            throw new Error("platform_search_failed");
          items = data.results.flatMap(
            (entry) => skillMarketResource(entry) || [],
          );
          more = data.by_provider.qwenpaw?.has_more || false;
        }
        if (signal.aborted) return;
        setResults((current) => ({
          ...current,
          [source]: {
            items: page === 1 ? items : [...current[source].items, ...items],
            page,
            more,
            loading: false,
            failed: false,
          },
        }));
      } catch {
        if (!signal.aborted)
          setResults((current) => ({
            ...current,
            [source]: { ...current[source], loading: false, failed: true },
          }));
      }
    },
    [query, i18n.language],
  );

  useEffect(() => {
    const pending = new AbortController();
    controller.current = pending;
    setResults({ plugins: emptyResults(), skills: emptyResults() });
    const timer = window.setTimeout(() => {
      void load("plugins", 1, pending.signal);
      void load("skills", 1, pending.signal);
    }, 300);
    return () => {
      window.clearTimeout(timer);
      pending.abort();
    };
  }, [load]);

  // Prefer local metadata; retain selections even when the search/page changes.
  const all = new Map<string, ReportResource>();
  [
    ...installed,
    ...selected,
    ...results.plugins.items,
    ...results.skills.items,
  ].forEach((item) => {
    const key = identity(item.origin);
    if (!all.has(key)) all.set(key, item);
  });
  const seen = new Set<string>();
  const group = (label: string, items: ReportResource[], filter = false) => ({
    label,
    options: items.flatMap((item) => {
      const key = identity(item.origin);
      if (
        resourceKind(item) !== kind ||
        seen.has(key) ||
        (filter &&
          !`${item.name} ${item.origin.resource_id} ${item.local_id || ""}`
            .toLowerCase()
            .includes(query.trim().toLowerCase()))
      )
        return [];
      seen.add(key);
      return [
        {
          value: key,
          label: `${item.name} · ${item.origin.resource_type} · ${item.origin.resource_id}`,
          title: `${item.name} · ${item.origin.resource_type}`,
        },
      ];
    }),
  });
  const groups = [
    group(t("communityAssist.installedResources"), installed, true),
    group(t("communityAssist.platformPlugins"), results.plugins.items),
    group(t("communityAssist.platformSkills"), results.skills.items),
    group(t("communityAssist.selectedResources"), selected),
  ].filter((entry) => entry.options.length);

  return (
    <div className={styles.resourcePicker}>
      <span className={styles.resourcePickerHint}>
        {t("communityAssist.resourceSearchHint")}
      </span>
      <Segmented
        value={kind}
        disabled={disabled}
        aria-label={t("communityAssist.resourceKind")}
        options={[
          {
            value: "plugin",
            label: `Plugin · ${
              selected.filter((item) => resourceKind(item) === "plugin").length
            }/3`,
          },
          {
            value: "skill",
            label: `Skill · ${
              selected.filter((item) => item.origin.resource_type === "skill")
                .length
            }/3`,
          },
        ]}
        onChange={(value) => {
          setKind(String(value));
          setQuery("");
        }}
      />
      <Select
        mode="multiple"
        showSearch
        autoFocus
        optionLabelProp="title"
        maxTagTextLength={28}
        filterOption={false}
        aria-label={t("communityAssist.searchPlatformResources")}
        placeholder={t("communityAssist.searchPlatformResources")}
        style={{ width: "100%" }}
        disabled={disabled}
        searchValue={query}
        autoClearSearchValue={false}
        onSearch={setQuery}
        loading={results.plugins.loading || results.skills.loading}
        value={selected
          .filter((item) => resourceKind(item) === kind)
          .map((item) => identity(item.origin))}
        options={groups}
        notFoundContent={t(
          results.plugins.loading || results.skills.loading
            ? "common.loading"
            : "communityAssist.noResourceResults",
        )}
        onChange={(keys: string[]) =>
          onChange([
            ...selected.filter((item) => resourceKind(item) !== kind),
            ...keys.flatMap((key) => all.get(key) || []),
          ])
        }
      />
      <Space wrap size="small">
        {(["plugins", "skills"] as Source[]).map((source) => {
          const state = results[source];
          if (
            source !== (kind === "plugin" ? "plugins" : "skills") ||
            (!state.more && !state.failed)
          )
            return null;
          const label = t(
            source === "plugins"
              ? "communityAssist.platformPlugins"
              : "communityAssist.platformSkills",
          );
          return (
            <div key={source}>
              {state.failed && (
                <Alert
                  type="warning"
                  showIcon
                  message={t("communityAssist.resourceSearchFailed", {
                    source: label,
                  })}
                />
              )}
              <Button
                size="small"
                type="link"
                disabled={disabled}
                loading={state.loading}
                onClick={() => {
                  if (controller.current && !state.loading)
                    void load(
                      source,
                      state.page + 1,
                      controller.current.signal,
                    );
                }}
              >
                {t(
                  state.failed
                    ? "communityAssist.retryResources"
                    : "communityAssist.moreResources",
                  { source: label },
                )}
              </Button>
            </div>
          );
        })}
      </Space>
    </div>
  );
}
