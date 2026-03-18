import { useEffect, useMemo, useState } from "react";
import {
  Button,
  Card,
  Empty,
  Form,
  Modal,
  Tag,
  message,
} from "@agentscope-ai/design";
import {
  CloudDownloadOutlined,
  DownloadOutlined,
  EditOutlined,
  MinusCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import type {
  MarketplaceItem,
  SkillSpec,
  SkillsMarketSpec,
} from "../../../api/types";
import { SkillCard, SkillDrawer } from "./components";
import { useSkills } from "./useSkills";
import { useTranslation } from "react-i18next";
import styles from "./index.module.less";

type SkillsView = "local" | "marketplace";
type MarketValidationState = {
  ok: boolean;
  warnings: string[];
};

type ParsedMarketUrl = {
  repoUrl: string;
  ownerRepo: string;
  branch?: string;
  path?: string;
};

function parseMarketUrlInput(input: string): ParsedMarketUrl | null {
  const text = (input || "").trim();
  if (!text) {
    return null;
  }

  const ownerRepoMatch = text.match(/^([\w.-]+)\/([\w.-]+)$/);
  if (ownerRepoMatch) {
    const owner = ownerRepoMatch[1];
    const repo = ownerRepoMatch[2];
    return {
      repoUrl: `https://github.com/${owner}/${repo}.git`,
      ownerRepo: `${owner}/${repo}`,
    };
  }

  try {
    const parsed = new URL(text);
    const host = parsed.hostname.toLowerCase();
    if (host !== "github.com" && host !== "www.github.com") {
      return null;
    }

    const parts = parsed.pathname.split("/").filter(Boolean);
    if (parts.length < 2) {
      return null;
    }

    const owner = parts[0];
    const repo = parts[1].replace(/\.git$/i, "");
    const result: ParsedMarketUrl = {
      repoUrl: `https://github.com/${owner}/${repo}.git`,
      ownerRepo: `${owner}/${repo}`,
    };

    if (parts.length >= 4 && (parts[2] === "tree" || parts[2] === "blob")) {
      result.branch = parts[3];
      if (parts.length > 4) {
        result.path = parts.slice(4).join("/");
      }
    }

    return result;
  } catch {
    return null;
  }
}

function buildSkillDefinitionUrl(item: MarketplaceItem): string {
  const base = (item.install_url || item.source_url || "").trim();
  if (!base) {
    return "";
  }
  if (base.endsWith("/SKILL.md") || base.endsWith("SKILL.md")) {
    return base;
  }
  return `${base.replace(/\/$/, "")}/SKILL.md`;
}

function SkillsPage() {
  const { t } = useTranslation();
  const {
    skills,
    markets,
    marketplace,
    marketErrors,
    marketMeta,
    loading,
    marketplaceLoading,
    installingSkillKey,
    importing,
    createSkill,
    importFromHub,
    validateMarket,
    saveMarkets,
    fetchMarketplace,
    installFromMarketplace,
    toggleEnabled,
    deleteSkill,
  } = useSkills();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [importUrl, setImportUrl] = useState("");
  const [importUrlError, setImportUrlError] = useState("");
  const [editingSkill, setEditingSkill] = useState<SkillSpec | null>(null);
  const [hoverKey, setHoverKey] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<SkillsView>("local");
  const [marketSearch, setMarketSearch] = useState("");
  const [manageMarketsOpen, setManageMarketsOpen] = useState(false);
  const [savingMarkets, setSavingMarkets] = useState(false);
  const [validatingMarketId, setValidatingMarketId] = useState<string | null>(
    null,
  );
  const [marketDraft, setMarketDraft] = useState<SkillsMarketSpec[]>([]);
  const [autoParseEnabled, setAutoParseEnabled] = useState(true);
  const [marketValidation, setMarketValidation] = useState<
    Record<string, MarketValidationState>
  >({});
  const [refreshProgress, setRefreshProgress] = useState(0);
  const [form] = Form.useForm<SkillSpec>();

  useEffect(() => {
    if (!marketplaceLoading) {
      setRefreshProgress((prev) => (prev > 0 ? 100 : 0));
      const timeout = setTimeout(() => {
        setRefreshProgress(0);
      }, 300);
      return () => clearTimeout(timeout);
    }

    setRefreshProgress((prev) => (prev > 6 ? prev : 6));
    const timer = setInterval(() => {
      setRefreshProgress((prev) => {
        if (prev >= 92) {
          return prev;
        }
        const next = prev + Math.max(2, Math.round((100 - prev) * 0.08));
        return Math.min(92, next);
      });
    }, 220);

    return () => clearInterval(timer);
  }, [marketplaceLoading]);

  const supportedSkillUrlPrefixes = [
    "https://skills.sh/",
    "https://clawhub.ai/",
    "https://skillsmp.com/",
    "https://lobehub.com/",
    "https://market.lobehub.com/",
    "https://github.com/",
    "https://modelscope.cn/skills/",
  ];

  const isSupportedSkillUrl = (url: string) => {
    return supportedSkillUrlPrefixes.some((prefix) => url.startsWith(prefix));
  };

  const handleCreate = () => {
    setEditingSkill(null);
    form.resetFields();
    form.setFieldsValue({
      enabled: false,
    });
    setDrawerOpen(true);
  };

  const closeImportModal = () => {
    if (importing) {
      return;
    }
    setImportModalOpen(false);
    setImportUrl("");
    setImportUrlError("");
  };

  const handleImportFromHub = () => {
    setImportModalOpen(true);
  };

  const handleImportUrlChange = (value: string) => {
    setImportUrl(value);
    const trimmed = value.trim();
    if (trimmed && !isSupportedSkillUrl(trimmed)) {
      setImportUrlError(t("skills.invalidSkillUrlSource"));
      return;
    }
    setImportUrlError("");
  };

  const handleConfirmImport = async () => {
    if (importing) return;
    const trimmed = importUrl.trim();
    if (!trimmed) return;
    if (!isSupportedSkillUrl(trimmed)) {
      setImportUrlError(t("skills.invalidSkillUrlSource"));
      return;
    }
    const success = await importFromHub(trimmed);
    if (success) {
      closeImportModal();
    }
  };

  const handleEdit = (skill: SkillSpec) => {
    setEditingSkill(skill);
    form.setFieldsValue(skill);
    setDrawerOpen(true);
  };

  const handleToggleEnabled = async (skill: SkillSpec, e: React.MouseEvent) => {
    e.stopPropagation();
    await toggleEnabled(skill);
  };

  const handleDelete = async (skill: SkillSpec, e?: React.MouseEvent) => {
    e?.stopPropagation();
    await deleteSkill(skill);
  };

  const handleDrawerClose = () => {
    setDrawerOpen(false);
    setEditingSkill(null);
  };

  const handleSubmit = async (values: { name: string; content: string }) => {
    try {
      const success = await createSkill(values.name, values.content);
      if (success) {
        setDrawerOpen(false);
      }
    } catch (error) {
      console.error("Submit failed", error);
    }
  };

  const filteredMarketplace = useMemo(() => {
    const q = marketSearch.trim().toLowerCase();
    if (!q) {
      return marketplace;
    }
    return marketplace.filter((item) => {
      const tagsText = item.tags.join(" ").toLowerCase();
      return (
        item.name.toLowerCase().includes(q) ||
        item.skill_id.toLowerCase().includes(q) ||
        item.description.toLowerCase().includes(q) ||
        tagsText.includes(q)
      );
    });
  }, [marketSearch, marketplace]);

  const handleInstallMarketplaceSkill = async (item: MarketplaceItem) => {
    await installFromMarketplace(item);
  };

  const refreshMarketplace = async () => {
    await fetchMarketplace(true);
  };

  const enabledMarketCount = markets.filter((m) => m.enabled).length;
  const showInitialMarketplaceLoading =
    marketplaceLoading && marketplace.length === 0;
  const marketNameMap = useMemo(
    () => Object.fromEntries(markets.map((market) => [market.id, market.name])),
    [markets],
  );

  const openManageMarkets = () => {
    setMarketDraft(markets.map((m) => ({ ...m })));
    setAutoParseEnabled(true);
    setMarketValidation(
      Object.fromEntries(
        markets.map((market) => [market.id, { ok: true, warnings: [] }]),
      ),
    );
    setManageMarketsOpen(true);
  };

  const handleAddMarket = () => {
    const nextIndex = marketDraft.length + 1;
    const newMarket = {
      id: `market_${Date.now()}`,
      name: "",
      url: "",
      branch: "",
      path: "skills",
      enabled: true,
      order: nextIndex,
    };
    setMarketDraft((prev) => [...prev, newMarket]);
    setMarketValidation((prev) => ({
      ...prev,
      [newMarket.id]: { ok: false, warnings: [] },
    }));
  };

  const handleRemoveMarket = (id: string) => {
    setMarketDraft((prev) => prev.filter((item) => item.id !== id));
    setMarketValidation((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  };

  const updateMarketField = (
    id: string,
    key: "id" | "name" | "url" | "branch" | "path" | "enabled" | "order",
    value: string | number | boolean,
  ) => {
    setMarketDraft((prev) => {
      let nextId = id;
      const nextDraft = prev.map((item) => {
        if (item.id !== id) return item;
        const nextItem = {
          ...item,
          [key]: value,
        };
        nextId = nextItem.id;
        return nextItem;
      });
      setMarketValidation((current) => {
        const next = { ...current };
        delete next[id];
        next[nextId] = { ok: false, warnings: [] };
        return next;
      });
      return nextDraft;
    });
  };

  const applyMarketUrlDerivation = (id: string) => {
    if (!autoParseEnabled) {
      return;
    }
    setMarketDraft((prev) => {
      let changed = false;
      let changedBranch = "";
      let changedPath = "";
      const nextDraft = prev.map((item) => {
        if (item.id !== id) {
          return item;
        }

        const parsed = parseMarketUrlInput(item.url);
        if (!parsed) {
          return item;
        }

        const nextUrl = parsed.repoUrl;
        const nextBranch = parsed.branch ?? item.branch;
        const nextPath = parsed.path ?? item.path;
        const nextName = item.name.trim() ? item.name : parsed.ownerRepo;
        changed =
          nextUrl !== item.url ||
          nextBranch !== item.branch ||
          nextPath !== item.path ||
          nextName !== item.name;
        changedBranch = nextBranch || "";
        changedPath = nextPath || "";

        return {
          ...item,
          url: nextUrl,
          name: nextName,
          branch: nextBranch,
          path: nextPath,
        };
      });

      setMarketValidation((current) => {
        const next = { ...current };
        next[id] = { ok: false, warnings: [] };
        return next;
      });

      if (changed) {
        message.success(
          t("skills.marketUrlAutoParsed", {
            branch: changedBranch || "-",
            path: changedPath || "-",
          }),
        );
      }

      return nextDraft;
    });
  };

  const handleMarketUrlInput = (id: string, value: string) => {
    const trimmed = value.trim();
    if (!autoParseEnabled) {
      updateMarketField(id, "url", trimmed);
      return;
    }

    const parsed = parseMarketUrlInput(trimmed);
    if (!parsed) {
      updateMarketField(id, "url", trimmed);
      return;
    }

    setMarketDraft((prev) => {
      let changed = false;
      let changedBranch = "";
      let changedPath = "";
      const nextDraft = prev.map((item) => {
        if (item.id !== id) {
          return item;
        }

        const nextUrl = parsed.repoUrl;
        const nextBranch = parsed.branch ?? item.branch;
        const nextPath = parsed.path ?? item.path;
        const nextName = item.name.trim() ? item.name : parsed.ownerRepo;
        changed =
          nextUrl !== item.url ||
          nextBranch !== item.branch ||
          nextPath !== item.path ||
          nextName !== item.name;
        changedBranch = nextBranch || "";
        changedPath = nextPath || "";

        return {
          ...item,
          url: nextUrl,
          name: nextName,
          branch: nextBranch,
          path: nextPath,
        };
      });

      setMarketValidation((current) => {
        const next = { ...current };
        next[id] = { ok: false, warnings: [] };
        return next;
      });

      if (changed) {
        message.success(
          t("skills.marketUrlAutoParsed", {
            branch: changedBranch || "-",
            path: changedPath || "-",
          }),
        );
      }

      return nextDraft;
    });
  };

  const handleValidateMarket = async (id: string) => {
    const target = marketDraft.find((m) => m.id === id);
    if (!target) {
      return;
    }
    setValidatingMarketId(id);
    const result = await validateMarket(target);
    if (result?.normalized) {
      const normalizedId = result.normalized.id;
      setMarketDraft((prev) =>
        prev.map((item) =>
          item.id === id ? { ...item, ...result.normalized } : item,
        ),
      );
      setMarketValidation((prev) => {
        const next = { ...prev };
        delete next[id];
        next[normalizedId] = {
          ok: true,
          warnings: result.warnings ?? [],
        };
        return next;
      });
    }
    setValidatingMarketId(null);
  };

  const hasIncompleteMarket = marketDraft.some(
    (market) => !market.id.trim() || !market.name.trim() || !market.url.trim(),
  );
  const marketIdCount = marketDraft.reduce<Record<string, number>>(
    (acc, market) => {
      const id = market.id.trim();
      if (!id) {
        return acc;
      }
      acc[id] = (acc[id] || 0) + 1;
      return acc;
    },
    {},
  );
  const hasDuplicatedMarketId = Object.values(marketIdCount).some(
    (count) => count > 1,
  );
  const hasUnvalidatedMarket = marketDraft.some(
    (market) => !marketValidation[market.id]?.ok,
  );
  const canSaveMarkets =
    !savingMarkets &&
    !hasIncompleteMarket &&
    !hasDuplicatedMarketId &&
    !hasUnvalidatedMarket;

  const handleSaveMarkets = async () => {
    if (!canSaveMarkets) {
      return;
    }
    setSavingMarkets(true);
    const success = await saveMarkets(marketDraft);
    setSavingMarkets(false);
    if (success) {
      setManageMarketsOpen(false);
    }
  };

  return (
    <div className={styles.skillsPage}>
      <div className={styles.header}>
        <div className={styles.headerInfo}>
          <h1 className={styles.title}>{t("skills.title")}</h1>
          <p className={styles.description}>{t("skills.description")}</p>
        </div>
        <div className={styles.headerActions}>
          {viewMode === "local" ? (
            <>
              <Button
                type="primary"
                onClick={handleImportFromHub}
                icon={<DownloadOutlined />}
              >
                {t("skills.importSkills")}
              </Button>
              <Button
                type="primary"
                onClick={handleCreate}
                icon={<PlusOutlined />}
              >
                {t("skills.createSkill")}
              </Button>
            </>
          ) : (
            <>
              <Button icon={<EditOutlined />} onClick={openManageMarkets}>
                {t("skills.manageMarkets")}
              </Button>
              <Button
                type="primary"
                icon={<ReloadOutlined />}
                onClick={refreshMarketplace}
                loading={marketplaceLoading}
              >
                {t("skills.refreshMarketplace")}
              </Button>
            </>
          )}
        </div>
      </div>

      <Modal
        title={t("skills.manageMarkets")}
        open={manageMarketsOpen}
        onCancel={() => setManageMarketsOpen(false)}
        width={920}
        footer={
          <div className={styles.marketManageFooter}>
            <Button onClick={handleAddMarket} icon={<PlusOutlined />}>
              {t("skills.addMarket")}
            </Button>
            <div>
              <Button
                onClick={() => setManageMarketsOpen(false)}
                style={{ marginRight: 8 }}
                disabled={savingMarkets}
              >
                {t("common.cancel")}
              </Button>
              <Button
                type="primary"
                loading={savingMarkets}
                onClick={handleSaveMarkets}
                disabled={!canSaveMarkets}
              >
                {t("common.save")}
              </Button>
            </div>
          </div>
        }
      >
        <div className={styles.marketManageList}>
          {!canSaveMarkets ? (
            <div className={styles.marketManageNotice}>
              {hasIncompleteMarket
                ? t("skills.marketSaveRequiresFields")
                : hasDuplicatedMarketId
                ? t("skills.marketSaveRequiresUniqueId")
                : t("skills.marketSaveRequiresValidation")}
            </div>
          ) : null}
          {marketDraft.map((market) => (
            <div className={styles.marketManageCard} key={market.id}>
              <div className={styles.marketManageHeader}>
                <div className={styles.marketManageTitleRow}>
                  <strong>{market.id}</strong>
                  <span
                    className={`${styles.marketValidationBadge} ${
                      marketValidation[market.id]?.ok
                        ? styles.marketValidationOk
                        : styles.marketValidationPending
                    }`}
                  >
                    {marketValidation[market.id]?.ok
                      ? t("skills.marketValidated")
                      : t("skills.marketPendingValidation")}
                  </span>
                </div>
                <Button
                  size="small"
                  icon={<MinusCircleOutlined />}
                  onClick={() => handleRemoveMarket(market.id)}
                >
                  {t("skills.removeMarket")}
                </Button>
              </div>
              <div className={styles.marketManageGrid}>
                <label className={styles.marketManageFieldFull}>
                  <span>{t("skills.marketUrl")}</span>
                  <div className={styles.marketUrlInputRow}>
                    <input
                      className={styles.marketManageInput}
                      value={market.url}
                      onChange={(e) =>
                        handleMarketUrlInput(market.id, e.target.value)
                      }
                      onBlur={() => applyMarketUrlDerivation(market.id)}
                      placeholder={t("skills.marketUrlPlaceholder")}
                    />
                    <label className={styles.marketAutoParseToggle}>
                      <input
                        type="checkbox"
                        checked={autoParseEnabled}
                        onChange={(e) => setAutoParseEnabled(e.target.checked)}
                      />
                      <span>{t("skills.marketAutoParse")}</span>
                    </label>
                  </div>
                  <div className={styles.marketUrlExample}>
                    {t("skills.marketUrlExamples")}
                  </div>
                </label>
                <label>
                  <span>{t("skills.marketId")}</span>
                  <input
                    className={styles.marketManageInput}
                    value={market.id}
                    onChange={(e) =>
                      updateMarketField(market.id, "id", e.target.value.trim())
                    }
                  />
                </label>
                <label>
                  <span>{t("skills.marketName")}</span>
                  <input
                    className={styles.marketManageInput}
                    value={market.name}
                    onChange={(e) =>
                      updateMarketField(market.id, "name", e.target.value)
                    }
                  />
                </label>
                <label>
                  <span>{t("skills.marketBranch")}</span>
                  <input
                    className={styles.marketManageInput}
                    value={market.branch || ""}
                    onChange={(e) =>
                      updateMarketField(market.id, "branch", e.target.value)
                    }
                  />
                </label>
                <label>
                  <span>{t("skills.marketPath")}</span>
                  <input
                    className={styles.marketManageInput}
                    value={market.path || "skills"}
                    onChange={(e) =>
                      updateMarketField(market.id, "path", e.target.value.trim())
                    }
                  />
                </label>
                <label>
                  <span>{t("skills.marketOrder")}</span>
                  <input
                    className={styles.marketManageInput}
                    type="number"
                    value={market.order}
                    onChange={(e) =>
                      updateMarketField(
                        market.id,
                        "order",
                        Number(e.target.value || 0),
                      )
                    }
                  />
                </label>
              </div>
              <div className={styles.marketManageActions}>
                <label className={styles.marketEnabledToggle}>
                  <input
                    type="checkbox"
                    checked={!!market.enabled}
                    onChange={(e) =>
                      updateMarketField(market.id, "enabled", e.target.checked)
                    }
                  />
                  <span>{t("skills.marketEnabled")}</span>
                </label>
                <Button
                  size="small"
                  loading={validatingMarketId === market.id}
                  disabled={
                    !market.id.trim() ||
                    !market.name.trim() ||
                    !market.url.trim() ||
                    (marketIdCount[market.id.trim()] || 0) > 1
                  }
                  onClick={() => handleValidateMarket(market.id)}
                >
                  {t("skills.validateMarket")}
                </Button>
              </div>
              {marketValidation[market.id]?.ok &&
              marketValidation[market.id]?.warnings.length ? (
                <div className={styles.marketValidationWarnings}>
                  {marketValidation[market.id].warnings.join(" ")}
                </div>
              ) : null}
            </div>
          ))}
          {marketDraft.length === 0 ? (
            <Empty description={t("skills.noMarketsConfigured")} />
          ) : null}
        </div>
      </Modal>

      <div className={styles.viewSwitch}>
        <button
          className={`${styles.viewButton} ${
            viewMode === "local" ? styles.viewButtonActive : ""
          }`}
          onClick={() => setViewMode("local")}
          type="button"
        >
          {t("skills.localSkillsTab")}
        </button>
        <button
          className={`${styles.viewButton} ${
            viewMode === "marketplace" ? styles.viewButtonActive : ""
          }`}
          onClick={() => setViewMode("marketplace")}
          type="button"
        >
          {t("skills.marketplaceTab")}
        </button>
      </div>

      <Modal
        title={t("skills.importSkills")}
        open={importModalOpen}
        onCancel={closeImportModal}
        maskClosable={!importing}
        closable={!importing}
        keyboard={!importing}
        footer={
          <div style={{ textAlign: "right" }}>
            <Button
              onClick={closeImportModal}
              style={{ marginRight: 8 }}
              disabled={importing}
            >
              {t("common.cancel")}
            </Button>
            <Button
              type="primary"
              onClick={handleConfirmImport}
              loading={importing}
              disabled={importing || !importUrl.trim() || !!importUrlError}
            >
              {t("skills.importSkills")}
            </Button>
          </div>
        }
        width={760}
      >
        <div className={styles.importHintBlock}>
          <p className={styles.importHintTitle}>
            {t("skills.supportedSkillUrlSources")}
          </p>
          <ul className={styles.importHintList}>
            <li>https://skills.sh/</li>
            <li>https://clawhub.ai/</li>
            <li>https://skillsmp.com/</li>
            <li>https://lobehub.com/</li>
            <li>https://market.lobehub.com/</li>
            <li>https://github.com/</li>
            <li>https://modelscope.cn/skills/</li>
          </ul>
          <p className={styles.importHintTitle}>{t("skills.urlExamples")}</p>
          <ul className={styles.importHintList}>
            <li>https://skills.sh/vercel-labs/skills/find-skills</li>
            <li>https://lobehub.com/zh/skills/openclaw-skills-cli-developer</li>
            <li>
              https://market.lobehub.com/api/v1/skills/openclaw-skills-cli-developer/download
            </li>
            <li>
              https://github.com/anthropics/skills/tree/main/skills/skill-creator
            </li>
            <li>https://modelscope.cn/skills/@anthropics/skill-creator</li>
          </ul>
        </div>

        <input
          className={styles.importUrlInput}
          value={importUrl}
          onChange={(e) => handleImportUrlChange(e.target.value)}
          placeholder={t("skills.enterSkillUrl")}
          disabled={importing}
        />
        {importUrlError ? (
          <div className={styles.importUrlError}>{importUrlError}</div>
        ) : null}
        {importing ? (
          <div className={styles.importLoadingText}>{t("common.loading")}</div>
        ) : null}
      </Modal>

      {viewMode === "local" ? (
        loading ? (
          <div className={styles.loading}>
            <span className={styles.loadingText}>{t("common.loading")}</span>
          </div>
        ) : (
          <div className={styles.skillsGrid}>
            {skills
              .slice()
              .sort((a, b) => {
                if (a.enabled && !b.enabled) return -1;
                if (!a.enabled && b.enabled) return 1;
                return a.name.localeCompare(b.name);
              })
              .map((skill) => (
                <SkillCard
                  key={skill.name}
                  skill={skill}
                  isHover={hoverKey === skill.name}
                  onClick={() => handleEdit(skill)}
                  onMouseEnter={() => setHoverKey(skill.name)}
                  onMouseLeave={() => setHoverKey(null)}
                  onToggleEnabled={(e) => handleToggleEnabled(skill, e)}
                  onDelete={(e) => handleDelete(skill, e)}
                />
              ))}
          </div>
        )
      ) : (
        <div className={styles.marketplaceSection}>
          {refreshProgress > 0 ? (
            <div className={styles.refreshProgressWrap}>
              <div className={styles.refreshProgressTrack}>
                <div
                  className={styles.refreshProgressFill}
                  style={{ width: `${refreshProgress}%` }}
                />
              </div>
              <span className={styles.refreshProgressText}>
                {t("skills.refreshingMarketplace", {
                  progress: refreshProgress,
                })}
              </span>
            </div>
          ) : null}

          <div className={styles.marketplaceToolbar}>
            <div className={styles.marketStats}>
              <Tag color="blue">
                {t("skills.marketCount", {
                  enabled: enabledMarketCount,
                  total: markets.length,
                })}
              </Tag>
              {marketMeta ? (
                <Tag color="green">
                  {t("skills.marketRefreshSummary", {
                    success: marketMeta.success_market_count,
                    total: marketMeta.enabled_market_count,
                  })}
                </Tag>
              ) : null}
            </div>
            <input
              className={styles.marketSearchInput}
              value={marketSearch}
              onChange={(e) => setMarketSearch(e.target.value)}
              placeholder={t("skills.searchMarketplacePlaceholder")}
            />
          </div>

          {marketErrors.length > 0 ? (
            <div className={styles.marketErrors}>
              {marketErrors.map((error) => (
                <div
                  className={styles.marketErrorItem}
                  key={`${error.market_id}-${error.code}-${error.message}`}
                >
                  <strong>{error.market_id}</strong>: {error.message}
                </div>
              ))}
            </div>
          ) : null}

          {showInitialMarketplaceLoading ? (
            <div className={styles.loading}>
              <span className={styles.loadingText}>{t("common.loading")}</span>
            </div>
          ) : filteredMarketplace.length === 0 ? (
            <Empty description={t("skills.marketplaceEmpty")} />
          ) : (
            <div className={styles.marketplaceContentWrap}>
              <div
                className={`${styles.marketplaceGrid} ${
                  marketplaceLoading ? styles.marketplaceGridLoading : ""
                }`}
              >
                {filteredMarketplace.map((item) => {
                  const key = `${item.market_id}/${item.skill_id}`;
                  const isInstalling = installingSkillKey === key;
                  const skillDefinitionUrl = buildSkillDefinitionUrl(item);
                  return (
                    <Card key={key} className={styles.marketCard} hoverable>
                      <div className={styles.marketCardBody}>
                        <div className={styles.marketCardHeader}>
                          <h3 className={styles.marketSkillName}>{item.name}</h3>
                          <Tag color="geekblue">
                            {marketNameMap[item.market_id] || item.market_id}
                          </Tag>
                        </div>

                        <div className={styles.descriptionSection}>
                          <div className={styles.infoLabel}>
                            {t("skills.skillDescription")}
                          </div>
                          <div
                            className={`${styles.infoBlock} ${styles.marketSkillDescription}`}
                            title={item.description || item.skill_id}
                          >
                            {item.description || item.skill_id}
                          </div>
                        </div>

                        <div className={styles.marketSkillMeta}>
                          <div className={styles.infoSection}>
                            <div className={styles.infoLabel}>{t("skills.source")}</div>
                            <div>
                              <Tag color="blue">{item.skill_id}</Tag>
                            </div>
                          </div>
                          <div className={styles.infoSection}>
                            <div className={styles.infoLabel}>{t("skills.path")}</div>
                            <div
                              className={`${styles.infoBlock} ${styles.singleLineValue}`}
                              title={item.install_url || item.source_url}
                            >
                              {item.install_url || item.source_url}
                            </div>
                          </div>
                        </div>

                        <div className={styles.marketTagList}>
                          {item.tags.slice(0, 4).map((tag: string) => (
                            <Tag key={`${key}-${tag}`}>{tag}</Tag>
                          ))}
                          {item.version ? <Tag color="green">v{item.version}</Tag> : null}
                        </div>

                        <div className={styles.marketCardFooter}>
                          <a
                            href={skillDefinitionUrl}
                            target="_blank"
                            rel="noreferrer"
                            className={styles.marketSourceLink}
                          >
                            {t("skills.viewSource")}
                          </a>
                          <Button
                            type="primary"
                            size="small"
                            icon={<CloudDownloadOutlined />}
                            loading={isInstalling}
                            onClick={() => handleInstallMarketplaceSkill(item)}
                          >
                            {t("skills.installFromMarketplace")}
                          </Button>
                        </div>
                      </div>
                    </Card>
                  );
                })}
              </div>
              {marketplaceLoading ? (
                <div className={styles.marketplaceLoadingMask}>
                  <span>{t("skills.refreshingMarketplace", { progress: refreshProgress })}</span>
                </div>
              ) : null}
            </div>
          )}
        </div>
      )}

      <SkillDrawer
        open={drawerOpen}
        editingSkill={editingSkill}
        form={form}
        onClose={handleDrawerClose}
        onSubmit={handleSubmit}
      />
    </div>
  );
}

export default SkillsPage;
