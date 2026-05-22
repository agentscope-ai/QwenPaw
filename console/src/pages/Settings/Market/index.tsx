import { useState } from "react";
import { Button, Card, Drawer, Tooltip } from "@agentscope-ai/design";
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
import styles from "./index.module.less";

// Map provider key → display label, kept in sync with the backend
// ProviderInfo.label so cards, badges, and filter chips all read the
// same Title-Case name.
const SOURCE_LABELS: Record<string, string> = {
  clawhub: "ClawHub",
  modelscope: "ModelScope",
  aliyun: "Aliyun",
};

function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source;
}

// Most upstream skills don't expose a per-skill logo (Aliyun's schema has no
// icon field at all; ModelScope's logo_url is empty for ~99% of skills), so
// cards almost always fall back to a colored provider monogram.
const PROVIDER_FALLBACK: Record<string, { letter: string; color: string }> = {
  clawhub: { letter: "C", color: "#f59e0b" },
  modelscope: { letter: "M", color: "#4f46e5" },
  aliyun: { letter: "A", color: "#ff6a00" },
};

function SkillIcon({
  url,
  alt,
  source,
}: {
  url: string | null | undefined;
  alt: string;
  source: string;
}) {
  const [imgFailed, setImgFailed] = useState(false);
  if (url && !imgFailed) {
    return (
      <img
        className={styles.skillIcon}
        src={url}
        alt={alt}
        loading="lazy"
        referrerPolicy="no-referrer"
        onError={() => setImgFailed(true)}
      />
    );
  }
  const fallback = PROVIDER_FALLBACK[source];
  if (fallback) {
    return (
      <div
        className={styles.skillIcon}
        aria-hidden
        style={{ background: fallback.color, color: "#fff", fontWeight: 600 }}
      >
        {fallback.letter}
      </div>
    );
  }
  return (
    <div className={styles.skillIcon} aria-hidden>
      🧩
    </div>
  );
}

function MarketPage() {
  const { t } = useTranslation();
  const selectedAgent = useAgentStore((s) => s.selectedAgent);
  const market = useMarketSearch();
  const [cardTargets, setCardTargets] = useState<Record<string, InstallTarget>>(
    {},
  );
  const [detailItem, setDetailItem] = useState<MarketResult | null>(null);

  const cardKey = (item: MarketResult) => `${item.source}:${item.slug}`;
  const targetFor = (item: MarketResult): InstallTarget =>
    cardTargets[cardKey(item)] ?? "workspace";
  const setCardTarget = (item: MarketResult, next: InstallTarget) => {
    setCardTargets((prev) => ({ ...prev, [cardKey(item)]: next }));
  };

  const install = useMarketInstall({ selectedAgent });

  const onInstall = (item: MarketResult) => {
    install.enqueue([item], targetFor(item));
  };

  return (
    <div className={styles.marketPage}>
      <PageHeader
        items={[{ title: t("nav.settings") }, { title: t("nav.market") }]}
      />
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
          </div>
        </div>

        <div className={styles.providerChips}>
          {market.providers.map((p) => {
            const active = market.selectedProviderKeys.has(p.key);
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
                  onClick={
                    p.available ? () => market.toggleProvider(p.key) : undefined
                  }
                  role="button"
                  tabIndex={p.available ? 0 : -1}
                  onKeyDown={(e) => {
                    if (p.available && (e.key === "Enter" || e.key === " ")) {
                      e.preventDefault();
                      market.toggleProvider(p.key);
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
          <div className={styles.noSearchResults}>
            <span className={styles.noSearchResultsText}>
              {t("common.loading")}
            </span>
          </div>
        ) : market.results.length === 0 &&
          (market.globalError || market.errors.length > 0) ? (
          <EmptyState text={t("market.noResults")}>
            <Button onClick={() => market.retry()} loading={market.loading}>
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
                  key={`${item.source}:${item.slug}`}
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
                <Button
                  onClick={() => market.loadMore()}
                  loading={market.loading}
                >
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
        <div className={styles.queueDrawer}>
          <div className={styles.queueHeader}>
            <span>{t("market.installQueue")}</span>
            <Button size="small" onClick={install.clearCompleted}>
              {t("market.clearCompleted")}
            </Button>
          </div>
          <div className={styles.queueList}>
            {install.queue.map((q) => (
              <QueueItem
                key={q.id}
                item={q}
                onCancel={() => install.cancel(q.id)}
                onRetry={() => install.retry(q.id)}
              />
            ))}
          </div>
        </div>
      )}

      <DetailDrawer
        item={detailItem}
        target={detailItem ? targetFor(detailItem) : "workspace"}
        onTargetChange={(next) => {
          if (detailItem) setCardTarget(detailItem, next);
        }}
        onInstall={() => {
          if (detailItem) {
            onInstall(detailItem);
            setDetailItem(null);
          }
        }}
        onClose={() => setDetailItem(null)}
      />
    </div>
  );
}

function EmptyState({
  text,
  children,
}: {
  text: string;
  children?: React.ReactNode;
}) {
  return (
    <div className={styles.noSearchResults}>
      <span className={styles.noSearchResultsIcon}>📦</span>
      <span className={styles.noSearchResultsText}>{text}</span>
      {children}
    </div>
  );
}

interface ResultCardProps {
  item: MarketResult;
  target: InstallTarget;
  onTargetChange: (next: InstallTarget) => void;
  onInstall: () => void;
  onOpenDetail: () => void;
}

function ResultCard({
  item,
  target,
  onTargetChange,
  onInstall,
  onOpenDetail,
}: ResultCardProps) {
  const { t } = useTranslation();
  const [hover, setHover] = useState(false);
  return (
    <Card
      hoverable
      className={styles.skillCard}
      onClick={onOpenDetail}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{ cursor: "pointer" }}
    >
      <div className={styles.cardTopRow}>
        <SkillIcon url={item.icon_url} alt={item.name} source={item.source} />
        <span className={styles.sourceBadge}>{sourceLabel(item.source)}</span>
      </div>

      <div className={styles.titleRow}>
        <Tooltip title={item.name}>
          <h3 className={styles.skillTitle}>{item.name}</h3>
        </Tooltip>
      </div>

      <p className={styles.descriptionText}>
        {item.description || t("market.noDescription")}
      </p>

      {hover && (
        <div
          className={styles.cardFooter}
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => e.stopPropagation()}
        >
          <TargetToggle
            target={target}
            onChange={onTargetChange}
            size="small"
          />
          <Button
            type="primary"
            size="small"
            onClick={onInstall}
            className={styles.installButton}
          >
            {t("market.install")}
          </Button>
        </div>
      )}
    </Card>
  );
}

function TargetToggle({
  target,
  onChange,
  size,
}: {
  target: InstallTarget;
  onChange: (next: InstallTarget) => void;
  size?: "small" | "middle" | "large";
}) {
  const { t } = useTranslation();
  return (
    <div className={styles.targetToggle}>
      <Button
        size={size}
        type={target === "pool" ? "primary" : "default"}
        onClick={() => onChange("pool")}
      >
        {t("market.targetPool")}
      </Button>
      <Button
        size={size}
        type={target === "workspace" ? "primary" : "default"}
        onClick={() => onChange("workspace")}
      >
        {t("market.targetWorkspace")}
      </Button>
    </div>
  );
}

interface DetailDrawerProps {
  item: MarketResult | null;
  target: InstallTarget;
  onTargetChange: (next: InstallTarget) => void;
  onInstall: () => void;
  onClose: () => void;
}

const STAT_KEY_LABELS: Record<string, string> = {
  downloads: "market.stats.downloads",
  installs: "market.stats.installs",
  likes: "market.stats.likes",
  views: "market.stats.views",
  category: "market.stats.category",
  updated_at: "market.stats.updatedAt",
};

function formatStatValue(key: string, value: string | number): string {
  if (key === "updated_at" && typeof value === "string") {
    const d = new Date(value);
    if (!Number.isNaN(d.getTime())) return d.toLocaleDateString();
  }
  if (typeof value === "number") return value.toLocaleString();
  return String(value);
}

function DetailDrawer({
  item,
  target,
  onTargetChange,
  onInstall,
  onClose,
}: DetailDrawerProps) {
  const { t } = useTranslation();
  const open = !!item;
  const missing = t("market.detail.missing");
  const rows: Array<[string, React.ReactNode]> = item
    ? [
        [t("market.detail.author"), item.author || missing],
        [t("market.detail.version"), item.version || missing],
        [
          t("market.detail.sourceUrl"),
          <code key="src" className={styles.mono}>
            {item.source_url}
          </code>,
        ],
        [
          t("market.detail.slug"),
          <code key="slug" className={styles.mono}>
            {item.slug}
          </code>,
        ],
      ]
    : [];
  if (item?.stats) {
    for (const [key, value] of Object.entries(item.stats)) {
      const labelKey = STAT_KEY_LABELS[key];
      const label = labelKey ? t(labelKey) : key;
      rows.push([label, formatStatValue(key, value)]);
    }
  }

  return (
    <Drawer
      width={520}
      placement="right"
      title={t("market.detail.title")}
      open={open}
      onClose={onClose}
      destroyOnClose
      footer={
        item ? (
          <div className={styles.drawerFooter}>
            <TargetToggle target={target} onChange={onTargetChange} />
            <Button type="primary" onClick={onInstall}>
              {t("market.install")}
            </Button>
          </div>
        ) : null
      }
    >
      {item && (
        <>
          <div className={styles.detailHeader}>
            <SkillIcon
              url={item.icon_url}
              alt={item.name}
              source={item.source}
            />
            <div className={styles.detailHeaderText}>
              <h3 className={styles.detailTitle}>{item.name}</h3>
              <div className={styles.detailMeta}>
                <span className={styles.sourceBadge}>
                  {sourceLabel(item.source)}
                </span>
              </div>
            </div>
          </div>

          <div className={styles.detailDescription}>
            {item.description || t("market.noDescription")}
          </div>

          <dl className={styles.detailRows}>
            {rows.map(([key, value]) => (
              <div className={styles.detailRow} key={key}>
                <dt className={styles.detailKey}>{key}</dt>
                <dd className={styles.detailValue}>{value}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
    </Drawer>
  );
}

function QueueItem({
  item,
  onCancel,
  onRetry,
}: {
  item: InstallQueueItem;
  onCancel: () => void;
  onRetry: () => void;
}) {
  const { t } = useTranslation();
  const isTerminal =
    item.status === "completed" ||
    item.status === "failed" ||
    item.status === "cancelled";
  // Pool install is a one-shot HTTP with no real cancellation. Allow
  // cancel only while queued; once it's in flight the request can't be
  // interrupted, so don't promise something we can't deliver.
  const canCancel =
    !isTerminal && !(item.target === "pool" && item.status === "installing");
  const canRetry = item.status === "failed" || item.status === "cancelled";
  const targetLabel = t(
    item.target === "pool" ? "market.targetPool" : "market.targetWorkspace",
  );
  // Internal sentinel used by useMarketInstall for timeouts; everything
  // else is upstream text and shown as-is with a localized prefix.
  let displayMessage = "";
  if (item.message === "__TIMED_OUT__") {
    displayMessage = t("market.queueMsg.timedOut");
  } else if (item.message) {
    displayMessage =
      item.status === "failed"
        ? t("market.queueMsg.failedPrefix", { msg: item.message })
        : item.message;
  }
  return (
    <div className={styles.queueItem}>
      <div className={styles.queueItemTop}>
        <strong>{item.result.name}</strong>
        <span className={`${styles.statusTag} ${styles[item.status]}`}>
          {t(`market.status.${item.status}`)}
        </span>
      </div>
      <div className={styles.queueItemMeta}>
        {sourceLabel(item.result.source)} → {targetLabel}
      </div>
      {displayMessage && (
        <div className={styles.queueItemMessage}>{displayMessage}</div>
      )}
      <div className={styles.queueItemActions}>
        {canCancel && (
          <Button size="small" onClick={onCancel}>
            {t("common.cancel")}
          </Button>
        )}
        {canRetry && (
          <Button size="small" type="primary" onClick={onRetry}>
            {t("market.retry")}
          </Button>
        )}
      </div>
    </div>
  );
}

export default MarketPage;
