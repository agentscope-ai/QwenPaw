import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Input, Select, Tooltip } from "@agentscope-ai/design";
import { Button as AntButton } from "antd";
import { ChevronLeft, ChevronRight, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useMarketSearch } from "./useMarketSearch";
import type {
  InstallTarget,
  InstallQueueItem,
  MarketInstallController,
} from "./useMarketInstall";
import type { MarketResult } from "../../../api/modules/market";
import { ResultCard, DetailDrawer, QueueItem, EmptyState } from "./components";
import styles from "./index.module.less";

function getCardKey(item: MarketResult) {
  return `${item.source}:${item.slug}`;
}

/** Memoized install queue panel — only re-renders when queue changes */
export const InstallQueuePanel = memo(function InstallQueuePanel({
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

/** Multi-select source selector. */
const ProviderSelect = memo(function ProviderSelect({
  providers,
  selectedKeys,
  onSelect,
}: {
  providers: {
    key: string;
    label: string;
    available: boolean;
    reason?: string | null;
  }[];
  selectedKeys: Set<string>;
  onSelect: (keys: string[]) => void;
}) {
  const { t } = useTranslation();
  const availableKeys = useMemo(
    () => providers.filter((provider) => provider.available).map((p) => p.key),
    [providers],
  );
  const value = [...selectedKeys].filter((key) => availableKeys.includes(key));
  const options = useMemo(
    () =>
      providers.map((provider) => {
        const unavailableReason =
          provider.reason ?? t("market.providerUnavailable");
        return {
          value: provider.key,
          label: provider.available ? (
            provider.label
          ) : (
            <Tooltip title={unavailableReason}>
              <span className={styles.providerOption}>{provider.label}</span>
            </Tooltip>
          ),
          disabled: !provider.available,
        };
      }),
    [providers, t],
  );

  return (
    <Select
      className={styles.providerSelect}
      mode="multiple"
      value={value}
      options={options}
      onChange={(nextValues: string[]) => onSelect(nextValues)}
      popupMatchSelectWidth={false}
      popupClassName={styles.providerDropdown}
    />
  );
});

/** Expanded single-select category tags. */
const CategoryChips = memo(function CategoryChips({
  categories,
  active,
  onSelect,
}: {
  categories: { id: string; label: string }[];
  active: string;
  onSelect: (id: string) => void;
}) {
  const { t } = useTranslation();
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);
  const options = [{ id: "", label: t("market.categoryAll") }, ...categories];
  const optionsKey = options
    .map((option) => `${option.id}:${option.label}`)
    .join("|");

  const updateScrollState = useCallback(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    setCanScrollLeft(viewport.scrollLeft > 1);
    setCanScrollRight(
      viewport.scrollLeft + viewport.clientWidth < viewport.scrollWidth - 1,
    );
  }, []);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    updateScrollState();
    viewport.addEventListener("scroll", updateScrollState, { passive: true });
    const resizeObserver =
      typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(updateScrollState)
        : null;
    resizeObserver?.observe(viewport);
    return () => {
      viewport.removeEventListener("scroll", updateScrollState);
      resizeObserver?.disconnect();
    };
  }, [optionsKey, updateScrollState]);

  const scrollCategories = useCallback((direction: -1 | 1) => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    viewport.scrollBy({
      left: direction * viewport.clientWidth,
      behavior: "smooth",
    });
  }, []);

  return (
    <div className={styles.categoryNav}>
      <div
        ref={viewportRef}
        className={styles.categoryViewport}
        role="group"
        aria-label={t("market.categoryPlaceholder")}
      >
        <div className={styles.categoryChips}>
          {options.map((category) => (
            <button
              type="button"
              key={category.id || "all"}
              className={`${styles.categoryChip} ${
                active === category.id ? styles.categoryChipActive : ""
              }`}
              aria-pressed={active === category.id}
              onClick={() => onSelect(category.id)}
            >
              {category.label}
            </button>
          ))}
        </div>
      </div>
      <div className={styles.categoryNavActions}>
        <Button
          type="default"
          className={styles.categoryNavButton}
          icon={<ChevronLeft size={16} />}
          disabled={!canScrollLeft}
          onClick={() => scrollCategories(-1)}
          aria-label={t("common.back")}
          title={t("common.back")}
        />
        <Button
          type="default"
          className={styles.categoryNavButton}
          icon={<ChevronRight size={16} />}
          disabled={!canScrollRight}
          onClick={() => scrollCategories(1)}
          aria-label={t("common.next", "Next")}
          title={t("common.next", "Next")}
        />
      </div>
    </div>
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
  install,
}: {
  installTarget: InstallTarget;
  install: MarketInstallController;
}) {
  const { t } = useTranslation();
  const market = useMarketSearch();
  const [detailItem, setDetailItem] = useState<MarketResult | null>(null);

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
          <CategoryChips
            categories={market.categories}
            active={market.category}
            onSelect={market.setCategory}
          />
          <div className={styles.filters}>
            <Input.Search
              className={styles.searchInput}
              placeholder={t("market.searchPlaceholder")}
              allowClear
              value={market.query}
              onChange={(e) => market.setQuery(e.target.value)}
              aria-label={t("market.searchPlaceholder")}
            />
            <div className={styles.providerActions}>
              <ProviderSelect
                providers={market.providers}
                selectedKeys={market.selectedProviderKeys}
                onSelect={market.setSelectedProviders}
              />
              <AntButton
                type="default"
                className={styles.refreshButton}
                icon={<RefreshCw size={14} />}
                onClick={market.refresh}
                disabled={market.loading}
                aria-label={t("common.refresh")}
                title={t("common.refresh")}
              />
            </div>
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

      <DetailDrawer
        item={detailItem}
        onInstall={handleDetailInstall}
        onClose={handleDetailClose}
      />
    </div>
  );
}
