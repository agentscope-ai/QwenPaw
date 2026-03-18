import { useState, useEffect, useRef } from "react";
import { Drawer, Button, Modal, message } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import type {
  MarketError,
  MarketplaceItem,
  MarketplaceMeta,
  SkillsMarketSpec,
} from "../../../../api/types";
import styles from "../index.module.less";

export interface MarketplaceDrawerProps {
  open: boolean;
  onClose: () => void;
  // Market config
  marketDrafts: SkillsMarketSpec[];
  marketCacheTtl: number;
  marketOverwriteDefault: boolean;
  savingMarkets: boolean;
  onAddMarket: () => void;
  onRemoveMarket: (idx: number) => void;
  onUpdateMarket: (idx: number, patch: Partial<SkillsMarketSpec>) => void;
  onValidateMarket: (idx: number, draft?: SkillsMarketSpec) => Promise<void>;
  onSaveMarkets: () => Promise<void>;
  onResetMarketTemplates: () => void;
  onCacheTtlChange: (val: number) => void;
  onOverwriteDefaultChange: (val: boolean) => void;
  // Marketplace items
  marketplace: MarketplaceItem[];
  marketErrors: MarketError[];
  marketMeta: MarketplaceMeta | null;
  marketplaceLoading: boolean;
  onRefreshMarketplace: () => void;
  installingSkillKey: string | null;
  onInstallSkill: (marketId: string, skillId: string) => Promise<boolean>;
  // Bulk operations
  onRunBulkAction: (params: {
    type: "enable" | "disable" | "delete";
    marketId: string;
    shouldStop: () => boolean;
    onProgress?: (skillKey: string | null) => void;
  }) => Promise<
    | {
        type: "enable";
        total: number;
        affected: number;
        failed: number;
        enabled: number;
        installed: number;
        stopped: boolean;
      }
    | {
        type: "disable";
        total: number;
        affected: number;
        failed: number;
        disabled: number;
        stopped: boolean;
      }
    | {
        type: "delete";
        total: number;
        affected: number;
        failed: number;
        deleted: number;
        stopped: boolean;
      }
  >;
}

export function MarketplaceDrawer({
  open,
  onClose,
  marketDrafts,
  marketCacheTtl,
  marketOverwriteDefault,
  savingMarkets,
  onAddMarket,
  onRemoveMarket,
  onUpdateMarket,
  onValidateMarket,
  onSaveMarkets,
  onResetMarketTemplates,
  onCacheTtlChange,
  onOverwriteDefaultChange,
  marketplace,
  marketErrors,
  marketMeta,
  marketplaceLoading,
  onRefreshMarketplace,
  installingSkillKey,
  onInstallSkill,
  onRunBulkAction,
}: MarketplaceDrawerProps) {
  const { t } = useTranslation();
  const [editingMarketIdx, setEditingMarketIdx] = useState<number | null>(null);
  const [rowBackup, setRowBackup] = useState<SkillsMarketSpec | null>(null);
  const [savingRow, setSavingRow] = useState(false);
  const [validatingMarketIdx, setValidatingMarketIdx] = useState<number | null>(
    null,
  );
  const [bulkActionState, setBulkActionState] = useState<{
    marketId: string;
    type: "enable" | "disable" | "delete";
  } | null>(null);
  const [activeBulkSkillKey, setActiveBulkSkillKey] = useState<string | null>(
    null,
  );
  const [selectedMarketId, setSelectedMarketId] = useState("__all__");
  const [marketSearch, setMarketSearch] = useState("");
  const prevOpenRef = useRef(false);
  const stopBulkRef = useRef(false);

  const marketIdOptions = Array.from(
    new Set(marketplace.map((item) => item.market_id).filter(Boolean)),
  ).sort();

  const marketItemCountMap = marketplace.reduce<Record<string, number>>(
    (acc, item) => {
      acc[item.market_id] = (acc[item.market_id] ?? 0) + 1;
      return acc;
    },
    {},
  );

  const searchKeyword = marketSearch.trim().toLowerCase();

  const renderHighlightedText = (text: string) => {
    if (!searchKeyword) return text;
    const normalizedText = text.toLowerCase();
    const matchedAt = normalizedText.indexOf(searchKeyword);
    if (matchedAt < 0) return text;
    const end = matchedAt + searchKeyword.length;
    return (
      <>
        {text.slice(0, matchedAt)}
        <span className={styles.marketSearchHighlight}>
          {text.slice(matchedAt, end)}
        </span>
        {text.slice(end)}
      </>
    );
  };

  const filteredMarketplace = marketplace.filter((item) => {
    if (selectedMarketId !== "__all__" && item.market_id !== selectedMarketId) {
      return false;
    }

    if (!searchKeyword) {
      return true;
    }

    const haystack = [
      item.name,
      item.skill_id,
      item.market_id,
      item.description ?? "",
    ]
      .join(" ")
      .toLowerCase();

    return haystack.includes(searchKeyword);
  });

  useEffect(() => {
    if (selectedMarketId === "__all__") return;
    if (!marketIdOptions.includes(selectedMarketId)) {
      setSelectedMarketId("__all__");
    }
  }, [selectedMarketId, marketIdOptions]);

  // Auto-refresh marketplace items when drawer first opens and list is empty
  useEffect(() => {
    if (open && !prevOpenRef.current) {
      setMarketSearch("");
      if (marketplace.length === 0) {
        onRefreshMarketplace();
      }
    }
    prevOpenRef.current = open;
  }, [open, marketplace.length, onRefreshMarketplace]);

  const handleEditRow = (idx: number) => {
    setRowBackup({ ...marketDrafts[idx] });
    setEditingMarketIdx(idx);
  };

  const handleCancelEdit = () => {
    if (editingMarketIdx !== null && rowBackup !== null) {
      onUpdateMarket(editingMarketIdx, rowBackup);
    }
    setEditingMarketIdx(null);
    setRowBackup(null);
  };

  const handleSaveRow = async () => {
    setSavingRow(true);
    try {
      await onSaveMarkets();
      setEditingMarketIdx(null);
      setRowBackup(null);
    } finally {
      setSavingRow(false);
    }
  };

  const inferMarketNameFromUrl = (raw: string) => {
    const text = (raw || "").trim();
    if (!text) return "";

    const parseOwnerRepo = (candidate: string) => {
      const cleaned = candidate.replace(/^\/+|\/+$/g, "");
      const parts = cleaned.split("/").filter(Boolean);
      if (parts.length >= 2) {
        return parts[1];
      }
      return "";
    };

    try {
      const u = new URL(text);
      if (u.hostname.includes("github.com")) {
        const repo = parseOwnerRepo(u.pathname);
        if (repo) return repo;
      }
      const hostFirst = u.hostname.split(".").filter(Boolean)[0];
      return hostFirst || "";
    } catch {
      const noProto = text.replace(/^https?:\/\//, "");
      if (noProto.includes("/")) {
        const repo = parseOwnerRepo(noProto);
        if (repo) return repo;
      }
      return "";
    }
  };

  const inferMarketIdFromUrl = (raw: string) => {
    const text = (raw || "").trim();
    if (!text) return "";

    const parseOwnerRepo = (candidate: string) => {
      const cleaned = candidate.replace(/^\/+|\/+$/g, "");
      const parts = cleaned.split("/").filter(Boolean);
      if (parts.length >= 2) {
        return { owner: parts[0], repo: parts[1].replace(/\.git$/i, "") };
      }
      return null;
    };

    try {
      const u = new URL(text);
      if (u.hostname.includes("github.com")) {
        const parsed = parseOwnerRepo(u.pathname);
        if (parsed) return `${parsed.owner}/${parsed.repo}`;
      }
      const noProto = text.replace(/^https?:\/\//, "");
      const parsed = parseOwnerRepo(noProto);
      if (parsed) return `${parsed.owner}-${parsed.repo}`;
    } catch {
      const parsed = parseOwnerRepo(text.replace(/^https?:\/\//, ""));
      if (parsed) return `${parsed.owner}-${parsed.repo}`;
    }

    return "";
  };

  const isGithubTreeUrl = (raw: string) => {
    const text = (raw || "").trim();
    if (!text) return false;
    try {
      const u = new URL(text);
      if (!u.hostname.includes("github.com")) return false;
      const parts = u.pathname.split("/").filter(Boolean);
      return parts.length >= 4 && (parts[2] === "tree" || parts[2] === "blob");
    } catch {
      return false;
    }
  };

  const maybeAutofillMarketName = (idx: number, market: SkillsMarketSpec) => {
    const patch: Partial<SkillsMarketSpec> = {};

    if (!market.id?.trim()) {
      const inferredId = inferMarketIdFromUrl(market.url);
      if (inferredId) {
        patch.id = inferredId;
      }
    }

    if (!market.name?.trim()) {
      const inferredName = inferMarketNameFromUrl(market.url);
      if (inferredName) {
        patch.name = inferredName;
      }
    }

    if (Object.keys(patch).length === 0) {
      return market;
    }

    onUpdateMarket(idx, patch);
    return { ...market, ...patch };
  };

  const handleAddMarketRow = () => {
    const nextIndex = marketDrafts.length;
    onAddMarket();
    setRowBackup(null);
    setEditingMarketIdx(nextIndex);
  };

  const handleValidateRow = async (idx: number, market: SkillsMarketSpec) => {
    const next = maybeAutofillMarketName(idx, market);
    setValidatingMarketIdx(idx);
    try {
      await onValidateMarket(idx, next);
    } finally {
      setValidatingMarketIdx(null);
    }
  };

  const runBulkAction = (
    type: "enable" | "disable" | "delete",
    marketId: string,
  ) => {
    if (bulkActionState?.marketId === marketId && bulkActionState.type === type) {
      stopBulkRef.current = true;
      return;
    }

    const actionTitle =
      type === "enable"
        ? t("skills.marketEnableAll")
        : type === "disable"
          ? t("skills.marketDisableAll")
          : t("skills.marketDeleteAll");
    const actionConfirm =
      type === "enable"
        ? t("skills.marketEnableAllConfirm")
        : type === "disable"
          ? t("skills.marketDisableAllConfirm")
          : t("skills.marketDeleteAllConfirm");
    const actionLoading =
      type === "enable"
        ? t("skills.marketBulkEnableLoading")
        : type === "disable"
          ? t("skills.marketBulkDisableLoading")
          : t("skills.marketBulkDeleteLoading");

    Modal.confirm({
      title: actionTitle,
      content: actionConfirm,
      okType: type === "delete" ? "danger" : "primary",
      onOk: async () => {
        const messageKey = `market-bulk-${marketId}`;
        stopBulkRef.current = false;
        setBulkActionState({ marketId, type });
        setActiveBulkSkillKey(null);
        message.open({
          key: messageKey,
          type: "loading",
          content: actionLoading,
          duration: 0,
        });
        try {
          const result = await onRunBulkAction({
            type,
            marketId,
            shouldStop: () => stopBulkRef.current,
            onProgress: setActiveBulkSkillKey,
          });

          if (result.type === "enable") {
            const notify = result.failed > 0 || result.stopped
              ? message.warning
              : message.success;
            notify({
              key: messageKey,
              content: t("skills.marketBulkEnableSummary", {
                action: t("skills.marketEnableAll"),
                total: result.total,
                enabled: result.enabled,
                installed: result.installed,
                failed: result.failed,
              }),
            });
          } else if (result.type === "disable") {
            const notify = result.failed > 0 || result.stopped
              ? message.warning
              : message.success;
            notify({
              key: messageKey,
              content: t("skills.marketBulkDisableSummary", {
                action: t("skills.marketDisableAll"),
                total: result.total,
                disabled: result.disabled,
                failed: result.failed,
              }),
            });
          } else {
            const notify = result.failed > 0 || result.stopped
              ? message.warning
              : message.success;
            notify({
              key: messageKey,
              content: t("skills.marketBulkDeleteSummary", {
                action: t("skills.marketDeleteAll"),
                total: result.total,
                deleted: result.deleted,
                failed: result.failed,
              }),
            });
          }
        } catch {
          message.error({
            key: messageKey,
            content: t("skills.marketBulkFailed", {
              action: actionTitle,
            }),
          });
        } finally {
          stopBulkRef.current = false;
          setActiveBulkSkillKey(null);
          setBulkActionState(null);
        }
      },
    });
  };

  const confirmResetMarkets = () => {
    Modal.confirm({
      title: t("skills.marketResetTemplate"),
      content: t("skills.marketResetTemplateConfirm"),
      okType: "danger",
      onOk: () => {
        onResetMarketTemplates();
      },
    });
  };

  return (
    <Drawer
      title={t("skills.marketplaceTitle")}
      open={open}
      onClose={onClose}
      width="80vw"
      placement="right"
      destroyOnClose={false}
    >
      {/* Market Config Section */}
      <div className={styles.marketEditor}>
        <div className={styles.marketEditorHeader}>
          <h3 className={styles.marketEditorTitle}>
            {t("skills.marketConfigTitle")}
          </h3>
          <div className={styles.marketEditorActions}>
            <Button onClick={handleAddMarketRow}>{t("skills.marketAdd")}</Button>
            <Button onClick={confirmResetMarkets}>
              {t("skills.marketResetTemplate")}
            </Button>
            <Button
              type="primary"
              loading={savingMarkets}
              onClick={() => {
                void onSaveMarkets();
              }}
            >
              {t("skills.marketSaveConfig")}
            </Button>
          </div>
        </div>

        <div className={styles.marketConfigRow}>
          <label className={styles.marketConfigLabel}>
            {t("skills.marketCacheTtlLabel")}
            <input
              className={styles.marketInputOrder}
              type="number"
              min={0}
              value={marketCacheTtl}
              onChange={(e) =>
                onCacheTtlChange(
                  Number.parseInt(e.target.value || "0", 10) || 0,
                )
              }
            />
          </label>
          <label className={styles.marketEnabledLabel}>
            <input
              type="checkbox"
              checked={marketOverwriteDefault}
              onChange={(e) => onOverwriteDefaultChange(e.target.checked)}
            />
            {t("skills.marketOverwriteDefaultLabel")}
          </label>
        </div>

        <div className={styles.marketRows}>
          {marketDrafts.map((market, idx) =>
            editingMarketIdx === idx ? (
              /* Edit mode */
              <div key={`${market.id}-${idx}`} className={styles.marketRow}>
                <div className={styles.marketRowFields}>
                  <input
                    className={styles.marketInput}
                    value={market.id}
                    onChange={(e) =>
                      onUpdateMarket(idx, { id: e.target.value })
                    }
                    placeholder={t("skills.marketIdPlaceholder")}
                  />
                  <input
                    className={styles.marketInput}
                    value={market.name}
                    onChange={(e) =>
                      onUpdateMarket(idx, { name: e.target.value })
                    }
                    placeholder={t("skills.marketNamePlaceholder")}
                  />
                  <input
                    className={styles.marketInputWide}
                    value={market.url}
                    onChange={(e) =>
                      onUpdateMarket(idx, { url: e.target.value })
                    }
                    onBlur={() => {
                      void maybeAutofillMarketName(idx, market);
                    }}
                    placeholder={t("skills.marketUrlPlaceholder")}
                  />
                  {isGithubTreeUrl(market.url) ? (
                    <div className={styles.marketUrlHint}>
                      {t("skills.marketUrlNormalizeHint")}
                    </div>
                  ) : null}
                  <input
                    className={styles.marketInput}
                    value={market.branch ?? ""}
                    onChange={(e) =>
                      onUpdateMarket(idx, { branch: e.target.value })
                    }
                    placeholder={t("skills.marketBranchPlaceholder")}
                  />
                  <input
                    className={styles.marketInput}
                    value={market.path}
                    onChange={(e) =>
                      onUpdateMarket(idx, { path: e.target.value })
                    }
                    placeholder={t("skills.marketPathPlaceholder")}
                  />
                  <input
                    className={styles.marketInputOrder}
                    type="number"
                    value={market.order}
                    onChange={(e) =>
                      onUpdateMarket(idx, {
                        order:
                          Number.parseInt(e.target.value || "0", 10) || 0,
                      })
                    }
                    placeholder="order"
                  />
                  <label className={styles.marketEnabledLabel}>
                    <input
                      type="checkbox"
                      checked={market.enabled}
                      onChange={(e) =>
                        onUpdateMarket(idx, { enabled: e.target.checked })
                      }
                    />
                    {t("common.enabled")}
                  </label>
                </div>
                <div className={styles.marketRowActions}>
                  <Button
                    size="small"
                    loading={validatingMarketIdx === idx}
                    onClick={() => {
                      void handleValidateRow(idx, market);
                    }}
                  >
                    {t("skills.marketValidate")}
                  </Button>
                  <Button
                    size="small"
                    type="primary"
                    loading={savingRow}
                    onClick={() => {
                      void handleSaveRow();
                    }}
                  >
                    {t("skills.marketSaveRow")}
                  </Button>
                  <Button size="small" onClick={handleCancelEdit}>
                    {t("skills.marketCancelEdit")}
                  </Button>
                  <Button
                    size="small"
                    danger
                    onClick={() => onRemoveMarket(idx)}
                  >
                    {t("skills.marketRemove")}
                  </Button>
                </div>
              </div>
            ) : (
              /* Read-only mode */
              (() => {
                const marketBusy = bulkActionState?.marketId === market.id;
                const runningType = marketBusy ? bulkActionState?.type : null;
                const anyBulkRunning = bulkActionState !== null;
                const marketDisabled = !market.enabled;
                return (
              <div
                key={`${market.id}-${idx}`}
                className={styles.marketRowReadonly}
              >
                <div className={styles.marketRowReadonlyInfo}>
                  <span className={styles.marketRowReadonlyId}>
                    {market.id || "—"}
                  </span>
                  <span className={styles.marketRowReadonlyName}>
                    {market.name || "—"}
                  </span>
                  <span
                    className={styles.marketRowReadonlyUrl}
                    title={market.url}
                  >
                    {market.url || "—"}
                  </span>
                </div>
                <div className={styles.marketRowBulkActions}>
                  <Button
                    size="small"
                    disabled={anyBulkRunning}
                    onClick={() => handleEditRow(idx)}
                  >
                    {t("skills.marketEditRow")}
                  </Button>
                  <span
                    className={
                      market.enabled
                        ? styles.marketRowBadgeEnabled
                        : styles.marketRowBadgeDisabled
                    }
                  >
                    {market.enabled ? t("common.enabled") : t("common.disabled")}
                  </span>
                  <span className={styles.marketRowDivider}>|</span>
                  <span className={styles.marketRowCount}>
                    {t("skills.marketMetaItems")}: {marketItemCountMap[market.id] ?? 0}
                  </span>
                  <Button
                    size="small"
                    type={runningType === "enable" ? "primary" : "default"}
                    danger={runningType === "enable"}
                    disabled={
                      marketDisabled ||
                      anyBulkRunning &&
                      !(marketBusy && runningType === "enable")
                    }
                    onClick={() => runBulkAction("enable", market.id)}
                  >
                    {runningType === "enable"
                      ? t("skills.marketAbortEnable")
                      : t("skills.marketEnableAll")}
                  </Button>
                  <Button
                    size="small"
                    type={runningType === "disable" ? "primary" : "default"}
                    danger={runningType === "disable"}
                    disabled={
                      marketDisabled ||
                      anyBulkRunning &&
                      !(marketBusy && runningType === "disable")
                    }
                    onClick={() => runBulkAction("disable", market.id)}
                  >
                    {runningType === "disable"
                      ? t("skills.marketAbortDisable")
                      : t("skills.marketDisableAll")}
                  </Button>
                  <Button
                    size="small"
                    danger
                    disabled={
                      marketDisabled ||
                      anyBulkRunning &&
                      !(marketBusy && runningType === "delete")
                    }
                    onClick={() => runBulkAction("delete", market.id)}
                  >
                    {runningType === "delete"
                      ? t("skills.marketAbortDelete")
                      : t("skills.marketDeleteAll")}
                  </Button>
                </div>
              </div>
                );
              })()
            ),
          )}
          {marketDrafts.length === 0 ? (
            <div className={styles.marketEmpty}>
              {t("skills.marketEmptyConfig")}
            </div>
          ) : null}
        </div>
      </div>

      {/* Marketplace Items Section */}
      <div className={styles.marketplaceItemsSection}>
        <div className={styles.marketplaceItemsHeader}>
          {marketMeta ? (
            <div className={styles.marketMetaRow}>
              <span>
                {t("skills.marketMetaMarkets")}:{" "}
                {marketMeta.enabled_market_count}
              </span>
              <span>
                {t("skills.marketMetaHealthy")}:{" "}
                {marketMeta.success_market_count}
              </span>
              <span>
                {t("skills.marketMetaItems")}: {marketMeta.item_count}
              </span>
            </div>
          ) : (
            <div />
          )}
          <Button
            onClick={() => {
              void onRefreshMarketplace();
            }}
            loading={marketplaceLoading}
          >
            {t("common.refresh")}
          </Button>
        </div>

        <div className={styles.marketFilterRow}>
          <input
            className={styles.marketSearchInput}
            value={marketSearch}
            onChange={(e) => setMarketSearch(e.target.value)}
            placeholder={t("skills.marketSearchPlaceholder")}
          />
          <label className={styles.marketFilterLabel}>
            {t("skills.marketFilterById")}
            <select
              className={styles.marketFilterSelect}
              value={selectedMarketId}
              onChange={(e) => setSelectedMarketId(e.target.value)}
            >
              <option value="__all__">{t("skills.marketFilterAll")}</option>
              {marketIdOptions.map((marketId) => (
                <option key={marketId} value={marketId}>
                  {marketId}
                </option>
              ))}
            </select>
          </label>
        </div>

        {marketErrors.length > 0 ? (
          <div className={styles.marketErrorBox}>
            {marketErrors.slice(0, 3).map((err) => (
              <div key={`${err.market_id}-${err.code}-${err.message}`}>
                [{err.market_id}] {err.code}: {err.message}
              </div>
            ))}
          </div>
        ) : null}

        <div className={styles.marketItems}>
          {filteredMarketplace.map((item) => {
            const key = `${item.market_id}/${item.skill_id}`;
            return (
              <div
                key={key}
                className={`${styles.marketItemCard} ${
                  activeBulkSkillKey === key ? styles.marketItemCardActive : ""
                }`}
              >
                <div className={styles.marketItemMain}>
                  <div className={styles.marketItemName}>
                    {renderHighlightedText(item.name)}
                  </div>
                  <div className={styles.marketItemMeta}>
                    {renderHighlightedText(item.market_id)} /{" "}
                    {renderHighlightedText(item.skill_id)}
                  </div>
                  {item.description ? (
                    <div className={styles.marketItemDesc}>
                      {renderHighlightedText(item.description)}
                    </div>
                  ) : null}
                </div>
                <Button
                  size="small"
                  loading={installingSkillKey === key}
                  onClick={() => {
                    void onInstallSkill(item.market_id, item.skill_id);
                  }}
                >
                  {t("skills.marketInstall")}
                </Button>
              </div>
            );
          })}
          {filteredMarketplace.length === 0 && !marketplaceLoading ? (
            <div className={styles.marketEmpty}>
              {searchKeyword
                ? t("skills.marketEmptySearch")
                : selectedMarketId === "__all__"
                  ? t("skills.marketEmptyItems")
                  : t("skills.marketEmptyFiltered")}
            </div>
          ) : null}
        </div>
      </div>
    </Drawer>
  );
}
