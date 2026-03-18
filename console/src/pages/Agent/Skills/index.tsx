import { useEffect, useState } from "react";
import { Button, Form, Modal } from "@agentscope-ai/design";
import { DownloadOutlined, PlusOutlined } from "@ant-design/icons";
import type { SkillSpec, SkillsMarketSpec } from "../../../api/types";
import { SkillCard, SkillDrawer } from "./components";
import { useSkills } from "./useSkills";
import { useTranslation } from "react-i18next";
import styles from "./index.module.less";

function getDefaultMarketTemplates(): SkillsMarketSpec[] {
  return [
    {
      id: "community",
      name: "Editor Skills",
      url: "https://github.com/futuremeng/editor-skills.git",
      branch: "main",
      path: "index.json",
      enabled: true,
      order: 1,
      trust: "community",
    },
    {
      id: "jiulu_mcp",
      name: "Jiulu MCP Skills",
      url: "https://github.com/your-org/jiulu-mcp-skills.git",
      branch: "main",
      path: "skills",
      enabled: false,
      order: 2,
      trust: "custom",
    },
  ];
}

function SkillsPage() {
  const { t } = useTranslation();
  const {
    skills,
    markets,
    marketConfig,
    marketplace,
    marketErrors,
    marketMeta,
    loading,
    marketplaceLoading,
    installingSkillKey,
    importing,
    cancelImport,
    validateMarket,
    fetchMarketplace,
    saveMarkets,
    installMarketplaceSkill,
    createSkill,
    importFromHub,
    toggleEnabled,
    deleteSkill,
  } = useSkills();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [importUrl, setImportUrl] = useState("");
  const [importUrlError, setImportUrlError] = useState("");
  const [editingSkill, setEditingSkill] = useState<SkillSpec | null>(null);
  const [hoverKey, setHoverKey] = useState<string | null>(null);
  const [marketDrafts, setMarketDrafts] = useState<SkillsMarketSpec[]>([]);
  const [marketCacheTtl, setMarketCacheTtl] = useState(600);
  const [marketOverwriteDefault, setMarketOverwriteDefault] = useState(false);
  const [savingMarkets, setSavingMarkets] = useState(false);
  const [form] = Form.useForm<SkillSpec>();

  useEffect(() => {
    setMarketDrafts(markets || []);
  }, [markets]);

  useEffect(() => {
    setMarketCacheTtl(marketConfig?.cache?.ttl_sec ?? 600);
    setMarketOverwriteDefault(
      marketConfig?.install?.overwrite_default ?? false,
    );
  }, [marketConfig]);

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

  const handleInstallMarketplaceSkill = async (
    marketId: string,
    skillId: string,
  ) => {
    await installMarketplaceSkill(marketId, skillId, {
      enable: true,
      overwrite: false,
    });
  };

  const handleAddMarket = () => {
    const next: SkillsMarketSpec = {
      id: `market-${Date.now()}`,
      name: "",
      url: "",
      branch: "",
      path: "index.json",
      enabled: true,
      order: marketDrafts.length + 1,
      trust: "community",
    };
    setMarketDrafts((prev) => [...prev, next]);
  };

  const handleRemoveMarket = (idx: number) => {
    setMarketDrafts((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleUpdateMarket = (
    idx: number,
    patch: Partial<SkillsMarketSpec>,
  ) => {
    setMarketDrafts((prev) =>
      prev.map((item, i) => (i === idx ? { ...item, ...patch } : item)),
    );
  };

  const handleValidateMarket = async (idx: number) => {
    const current = marketDrafts[idx];
    if (!current) return;
    const result = await validateMarket(current);
    if (result?.normalized) {
      handleUpdateMarket(idx, result.normalized);
    }
  };

  const handleSaveMarkets = async () => {
    const payload = {
      version: marketConfig?.version ?? 1,
      cache: {
        ttl_sec: marketCacheTtl,
      },
      install: {
        overwrite_default: marketOverwriteDefault,
      },
      markets: marketDrafts,
    };

    setSavingMarkets(true);
    try {
      const ok = await saveMarkets(payload);
      if (ok) {
        await fetchMarketplace(true);
      }
    } finally {
      setSavingMarkets(false);
    }
  };

  const handleResetMarketTemplates = () => {
    setMarketDrafts(getDefaultMarketTemplates());
  };

  return (
    <div className={styles.skillsPage}>
      <div className={styles.header}>
        <div className={styles.headerInfo}>
          <h1 className={styles.title}>{t("skills.title")}</h1>
          <p className={styles.description}>{t("skills.description")}</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Button
            type="primary"
            onClick={handleImportFromHub}
            icon={<DownloadOutlined />}
          >
            {t("skills.importSkills")}
          </Button>
          <Button type="primary" onClick={handleCreate} icon={<PlusOutlined />}>
            {t("skills.createSkill")}
          </Button>
        </div>
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
              onClick={importing ? cancelImport : closeImportModal}
              style={{ marginRight: 8 }}
            >
              {t(importing ? "skills.cancelImport" : "common.cancel")}
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

      <div className={styles.marketplacePanel}>
        <div className={styles.marketplaceHeader}>
          <div>
            <h2 className={styles.marketplaceTitle}>{t("skills.marketplaceTitle")}</h2>
            <p className={styles.marketplaceDesc}>{t("skills.marketplaceDesc")}</p>
          </div>
          <Button
            onClick={() => {
              void fetchMarketplace(true);
            }}
            loading={marketplaceLoading}
          >
            {t("common.refresh")}
          </Button>
        </div>

        <div className={styles.marketEditor}>
          <div className={styles.marketEditorHeader}>
            <h3 className={styles.marketEditorTitle}>{t("skills.marketConfigTitle")}</h3>
            <div className={styles.marketEditorActions}>
              <Button onClick={handleAddMarket}>{t("skills.marketAdd")}</Button>
              <Button onClick={handleResetMarketTemplates}>{t("skills.marketResetTemplate")}</Button>
              <Button
                type="primary"
                loading={savingMarkets}
                onClick={() => {
                  void handleSaveMarkets();
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
                  setMarketCacheTtl(
                    Number.parseInt(e.target.value || "0", 10) || 0,
                  )
                }
              />
            </label>
            <label className={styles.marketEnabledLabel}>
              <input
                type="checkbox"
                checked={marketOverwriteDefault}
                onChange={(e) => setMarketOverwriteDefault(e.target.checked)}
              />
              {t("skills.marketOverwriteDefaultLabel")}
            </label>
          </div>

          <div className={styles.marketRows}>
            {marketDrafts.map((market, idx) => (
              <div key={`${market.id}-${idx}`} className={styles.marketRow}>
                <div className={styles.marketRowFields}>
                  <input
                    className={styles.marketInput}
                    value={market.id}
                    onChange={(e) =>
                      handleUpdateMarket(idx, { id: e.target.value })
                    }
                    placeholder={t("skills.marketIdPlaceholder")}
                  />
                  <input
                    className={styles.marketInput}
                    value={market.name}
                    onChange={(e) =>
                      handleUpdateMarket(idx, { name: e.target.value })
                    }
                    placeholder={t("skills.marketNamePlaceholder")}
                  />
                  <input
                    className={styles.marketInputWide}
                    value={market.url}
                    onChange={(e) =>
                      handleUpdateMarket(idx, { url: e.target.value })
                    }
                    placeholder={t("skills.marketUrlPlaceholder")}
                  />
                  <input
                    className={styles.marketInput}
                    value={market.branch ?? ""}
                    onChange={(e) =>
                      handleUpdateMarket(idx, { branch: e.target.value })
                    }
                    placeholder={t("skills.marketBranchPlaceholder")}
                  />
                  <input
                    className={styles.marketInput}
                    value={market.path}
                    onChange={(e) =>
                      handleUpdateMarket(idx, { path: e.target.value })
                    }
                    placeholder={t("skills.marketPathPlaceholder")}
                  />
                  <input
                    className={styles.marketInputOrder}
                    type="number"
                    value={market.order}
                    onChange={(e) =>
                      handleUpdateMarket(idx, {
                        order: Number.parseInt(e.target.value || "0", 10) || 0,
                      })
                    }
                    placeholder="order"
                  />
                  <label className={styles.marketEnabledLabel}>
                    <input
                      type="checkbox"
                      checked={market.enabled}
                      onChange={(e) =>
                        handleUpdateMarket(idx, { enabled: e.target.checked })
                      }
                    />
                    {t("common.enabled")}
                  </label>
                </div>
                <div className={styles.marketRowActions}>
                  <Button
                    size="small"
                    onClick={() => {
                      void handleValidateMarket(idx);
                    }}
                  >
                    {t("skills.marketValidate")}
                  </Button>
                  <Button
                    size="small"
                    danger
                    onClick={() => handleRemoveMarket(idx)}
                  >
                    {t("skills.marketRemove")}
                  </Button>
                </div>
              </div>
            ))}
            {marketDrafts.length === 0 ? (
              <div className={styles.marketEmpty}>{t("skills.marketEmptyConfig")}</div>
            ) : null}
          </div>
        </div>

        {marketMeta ? (
          <div className={styles.marketMetaRow}>
            <span>{t("skills.marketMetaMarkets")}: {marketMeta.enabled_market_count}</span>
            <span>{t("skills.marketMetaHealthy")}: {marketMeta.success_market_count}</span>
            <span>{t("skills.marketMetaItems")}: {marketMeta.item_count}</span>
          </div>
        ) : null}

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
          {marketplace.slice(0, 12).map((item) => {
            const key = `${item.market_id}/${item.skill_id}`;
            return (
              <div key={key} className={styles.marketItemCard}>
                <div className={styles.marketItemMain}>
                  <div className={styles.marketItemName}>{item.name}</div>
                  <div className={styles.marketItemMeta}>
                    {item.market_id} / {item.skill_id}
                  </div>
                  {item.description ? (
                    <div className={styles.marketItemDesc}>{item.description}</div>
                  ) : null}
                </div>
                <Button
                  size="small"
                  loading={installingSkillKey === key}
                  onClick={() => {
                    void handleInstallMarketplaceSkill(
                      item.market_id,
                      item.skill_id,
                    );
                  }}
                >
                  {t("skills.marketInstall")}
                </Button>
              </div>
            );
          })}
          {marketplace.length === 0 && !marketplaceLoading ? (
            <div className={styles.marketEmpty}>{t("skills.marketEmptyItems")}</div>
          ) : null}
        </div>
      </div>

      {loading ? (
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
