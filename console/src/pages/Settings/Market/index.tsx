import { memo, useCallback, useMemo, useRef, useState } from "react";
import { Button, Tooltip } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "../../../stores/agentStore";
import { PageHeader } from "@/components/PageHeader";
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

/** Memoized provider chip list */
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
              {p.label}
            </span>
          </Tooltip>
        );
      })}
    </div>
  );
});

function MarketPage() {
  const { t } = useTranslation();
  const selectedAgent = useAgentStore((s) => s.selectedAgent);
  const market = useMarketSearch();
  const [cardTargets, setCardTargets] = useState<Record<string, InstallTarget>>(
    {},
  );
  const [detailItem, setDetailItem] = useState<MarketResult | null>(null);

  // Use ref to avoid stale closure in callbacks that depend on latest cardTargets
  const cardTargetsRef = useRef(cardTargets);
  cardTargetsRef.current = cardTargets;

  const targetFor = useCallback(
    (item: MarketResult): InstallTarget =>
      cardTargetsRef.current[getCardKey(item)] ?? "workspace",
    [],
  );

  const setCardTarget = useCallback(
    (item: MarketResult, next: InstallTarget) => {
      setCardTargets((prev) => ({ ...prev, [getCardKey(item)]: next }));
    },
    [],
  );

  const install = useMarketInstall({ selectedAgent });

  const onInstall = useCallback(
    (item: MarketResult) => {
      const target = cardTargetsRef.current[getCardKey(item)] ?? "workspace";
      install.enqueue([item], target);
    },
    [install],
  );

  // Stable callbacks for DetailDrawer
  const detailItemRef = useRef(detailItem);
  detailItemRef.current = detailItem;

  const handleDetailTargetChange = useCallback(
    (next: InstallTarget) => {
      const current = detailItemRef.current;
      if (current) setCardTarget(current, next);
    },
    [setCardTarget],
  );

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

  // Memoize breadcrumb items to avoid re-creating each render
  const headerItems = useMemo(
    () => [{ title: t("nav.settings") }, { title: t("nav.market") }],
    [t],
  );

  return (
    <div className={styles.marketPage}>
      <PageHeader items={headerItems} />
      <div className={styles.content}>
        <div className={styles.toolbar}>
          <div className={styles.searchContainer}>
            <input
              className={styles.searchInput}
              placeholder={t("market.searchPlaceholder")}
              value={market.query}
              onChange={(e) => market.setQuery(e.target.value)}
              type="search"
              aria-label={t("market.searchPlaceholder")}
            />
            <Button
              type="primary"
              className={styles.searchButton}
              loading={market.loading && market.results.length === 0}
            >
              {t("common.search")}
            </Button>
          </div>
        </div>

        <ProviderChips
          providers={market.providers}
          selectedKeys={market.selectedProviderKeys}
          onToggle={market.toggleProvider}
        />

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
        ) : market.results.length === 0 && market.query.trim() ? (
          <EmptyState text={t("market.noResults")} />
        ) : market.results.length === 0 ? (
          <EmptyState text={t("market.startTyping")} />
        ) : (
          <>
            <div className={styles.resultsGrid}>
              {market.results.map((item) => (
                <ResultCard
                  key={getCardKey(item)}
                  item={item}
                  target={targetFor(item)}
                  onTargetChange={(next) => setCardTarget(item, next)}
                  onInstall={() => onInstall(item)}
                  onOpenDetail={() => setDetailItem(item)}
                />
              ))}
            </div>
            <div className={styles.loadMoreRow}>
              {market.hasMore ? (
                <Button onClick={market.loadMore} loading={market.loading}>
                  {t("market.loadMore")}
                </Button>
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
          onClearCompleted={install.clearCompleted}
          onCancel={install.cancel}
          onRetry={install.retry}
        />
      )}

      <DetailDrawer
        item={detailItem}
        target={detailItem ? targetFor(detailItem) : "workspace"}
        onTargetChange={handleDetailTargetChange}
        onInstall={handleDetailInstall}
        onClose={handleDetailClose}
      />
    </div>
  );
}

export default MarketPage;
