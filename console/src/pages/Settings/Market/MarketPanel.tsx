import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Input, Select, Tooltip } from "@agentscope-ai/design";
import { Check } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "../../../stores/agentStore";
import { useMarketSearch } from "./useMarketSearch";
import {
  useMarketInstall,
  type InstallTarget,
  type InstallQueueItem,
} from "./useMarketInstall";
import type { MarketResult } from "../../../api/modules/market";
import { ResultCard, DetailDrawer, QueueItem, EmptyState } from "./components";
import styles from "./index.module.less";

function getCardKey(item: MarketResult) {
  return `${item.source}:${item.slug}`;
}

/** Memoized install queue panel — only re-renders when queue changes */
const InstallQueuePanel = memo(function InstallQueuePanel({
  queue,
  onClearCompleted,
  onCancel,
  onRetry,
}: {
  queue: InstallQueueItem[];
  onClearCompleted: () => void;
  onCancel: (id: string) => void;
  onRetry: (id: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className={styles.queueDrawer}>
      <div className={styles.queueHeader}>
        <span>{t("market.installQueue")}</span>
        <Button size="small" onClick={onClearCompleted}>
          {t("market.clearCompleted")}
        </Button>
      </div>
      <div className={styles.queueList}>
        {queue.map((q) => (
          <QueueItem
            key={q.id}
            item={q}
            onCancel={onCancel}
            onRetry={onRetry}
          />
        ))}
      </div>
    </div>
  );
});

/** Multi-select provider chips (first filter layer) */
const ProviderChips = memo(function ProviderChips({
  providers,
  selectedKeys,
  onToggle,
}: {
  providers: {
    key: string;
    label: string;
    available: boolean;
    reason?: string | null;
  }[];
  selectedKeys: Set<string>;
  onToggle: (key: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className={styles.providerChips}>
      {providers.map((p) => {
        const active = selectedKeys.has(p.key);
        const klass = [
          styles.chip,
          active ? styles.chipActive : "",
          !p.available ? styles.chipDisabled : "",
        ]
          .filter(Boolean)
          .join(" ");
        return (
          <Tooltip
            key={p.key}
            title={
              p.available
                ? undefined
                : p.reason ?? t("market.providerUnavailable")
            }
          >
            <span
              className={klass}
              onClick={p.available ? () => onToggle(p.key) : undefined}
              role="button"
              tabIndex={p.available ? 0 : -1}
              onKeyDown={(e) => {
                if (p.available && (e.key === "Enter" || e.key === " ")) {
                  e.preventDefault();
                  onToggle(p.key);
                }
              }}
              aria-pressed={active}
              aria-disabled={!p.available}
            >
              {active && <Check size={12} strokeWidth={3} />}
              {p.label}
            </span>
          </Tooltip>
        );
      })}
    </div>
  );
});

/**
 * Single-select category dropdown (second filter layer).
 * The leading "All" option clears the filter.
 */
const CategorySelect = memo(function CategorySelect({
  categories,
  active,
  onSelect,
}: {
  categories: { id: string; label: string }[];
  active: string;
  onSelect: (id: string) => void;
}) {
  const { t } = useTranslation();
  const options = useMemo(
    () => [
      { value: "", label: t("market.categoryAll") },
      ...categories.map((c) => ({ value: c.id, label: c.label })),
    ],
    [categories, t],
  );
  return (
    <Select
      className={styles.categorySelect}
      value={active || undefined}
      onChange={(v) => onSelect(v ?? "")}
      options={options}
      placeholder={t("market.categoryPlaceholder")}
      showSearch
      allowClear
      optionFilterProp="label"
      popupMatchSelectWidth={false}
      aria-label={t("market.categoryPlaceholder")}
    />
  );
});

function LoadMoreSentinel({ onVisible }: { onVisible: () => void }) {
  const { t } = useTranslation();
  const nodeRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const node = nodeRef.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) onVisible();
      },
      { rootMargin: "200px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [onVisible]);
  return (
    <div ref={nodeRef} className={styles.sentinel}>
      {t("common.loading")}
    </div>
  );
}

/**
 * Embeddable market browser. The host page fixes the install destination:
 * Skills page saves into the current agent's workspace, Skill Pool page
 * imports into the pool.
 */
export function MarketPanel({
  installTarget,
}: {
  installTarget: InstallTarget;
}) {
  const { t } = useTranslation();
  const selectedAgent = useAgentStore((s) => s.selectedAgent);
  const market = useMarketSearch();
  const [detailItem, setDetailItem] = useState<MarketResult | null>(null);

  const install = useMarketInstall({ selectedAgent });

  const onInstall = useCallback(
    (item: MarketResult) => {
      install.enqueue([item], installTarget);
    },
    [install, installTarget],
  );

  // Stable callbacks for DetailDrawer
  const detailItemRef = useRef(detailItem);
  detailItemRef.current = detailItem;

  const handleDetailInstall = useCallback(() => {
    const current = detailItemRef.current;
    if (current) {
      onInstall(current);
      setDetailItem(null);
    }
  }, [onInstall]);

  const handleDetailClose = useCallback(() => {
    setDetailItem(null);
  }, []);

  const browseHintLabel = useMemo(() => {
    if (market.query.trim() || market.category) return "";
    return market.providers
      .filter(
        (p) =>
          p.available &&
          !p.supports_browse &&
          market.selectedProviderKeys.has(p.key),
      )
      .map((p) => p.label)
      .join(", ");
  }, [
    market.query,
    market.category,
    market.providers,
    market.selectedProviderKeys,
  ]);

  return (
    <div className={styles.marketPage}>
      <div className={styles.content}>
        <div className={styles.toolbar}>
          <ProviderChips
            providers={market.providers}
            selectedKeys={market.selectedProviderKeys}
            onToggle={market.toggleProvider}
          />
          <div className={styles.filters}>
            <CategorySelect
              categories={market.categories}
              active={market.category}
              onSelect={market.setCategory}
            />
            <Input.Search
              className={styles.searchInput}
              placeholder={t("market.searchPlaceholder")}
              allowClear
              value={market.query}
              onChange={(e) => market.setQuery(e.target.value)}
              aria-label={t("market.searchPlaceholder")}
            />
          </div>
        </div>

        {market.query.trim() && !market.loading && !market.globalError && (
          <div className={styles.searchHint}>
            {t("market.searchResult", {
              keyword: market.query.trim(),
              count: market.totalCount,
            })}
          </div>
        )}

        {browseHintLabel && (
          <div className={styles.browseHint}>
            {t("market.browseHint", { providers: browseHintLabel })}
          </div>
        )}

        {market.globalError && (
          <div className={styles.errorRow}>{market.globalError}</div>
        )}
        {market.errors.map((err) => {
          const provider = market.providers.find((p) => p.key === err.provider);
          const label = provider?.label ?? err.provider;
          return (
            <div className={styles.errorRow} key={err.provider}>
              <strong>{label}</strong>: {err.message}
            </div>
          );
        })}

        {market.loading && market.results.length === 0 ? (
          <EmptyState text={t("common.loading")} />
        ) : market.results.length === 0 &&
          (market.globalError || market.errors.length > 0) ? (
          <EmptyState text={t("market.noResults")}>
            <Button onClick={market.retry} loading={market.loading}>
              {t("market.retry")}
            </Button>
          </EmptyState>
        ) : market.results.length === 0 ? (
          <EmptyState text={t("market.noResults")} />
        ) : (
          <>
            <div className={styles.resultsGrid}>
              {market.results.map((item) => (
                <ResultCard
                  key={getCardKey(item)}
                  item={item}
                  onInstall={() => onInstall(item)}
                  onOpenDetail={() => setDetailItem(item)}
                />
              ))}
            </div>
            <div className={styles.loadMoreRow}>
              {market.hasMore && market.autoLoadBlocked ? (
                <Button onClick={market.loadMore} loading={market.loading}>
                  {t("market.loadMore")}
                </Button>
              ) : market.hasMore ? (
                <LoadMoreSentinel
                  key={market.results.length}
                  onVisible={market.autoLoadMore}
                />
              ) : (
                <span className={styles.noMoreText}>
                  {t("market.noMoreResults")}
                </span>
              )}
            </div>
          </>
        )}
      </div>

      {install.queue.length > 0 && (
        <InstallQueuePanel
          queue={install.queue}
          onClearCompleted={install.clearFinished}
          onCancel={install.cancel}
          onRetry={install.retry}
        />
      )}

      <DetailDrawer
        item={detailItem}
        onInstall={handleDetailInstall}
        onClose={handleDetailClose}
      />
    </div>
  );
}
