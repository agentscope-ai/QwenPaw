import { useEffect, useRef, useState } from "react";
import { Button, Form, Modal, message } from "@agentscope-ai/design";
import {
  AppstoreOutlined,
  DownloadOutlined,
  PlusOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import type { SkillSpec, SkillsMarketSpec } from "../../../api/types";
import { SkillCard, SkillDrawer, MarketplaceDrawer } from "./components";
import { useSkills } from "./useSkills";
import { useTranslation } from "react-i18next";
import { createDefaultSkillsMarketTemplates } from "../../../constants/skillsMarket";
import styles from "./index.module.less";

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
    uploading,
    marketplaceLoading,
    installingSkillKey,
    importing,
    cancelImport,
    validateMarket,
    fetchMarketplace,
    saveMarkets,
    installMarketplaceSkill,
    createSkill,
    uploadSkill,
    importFromHub,
    toggleEnabled,
    deleteSkill,
    deleteSkillDirect,
    fetchSkills,
  } = useSkills();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [marketplaceDrawerOpen, setMarketplaceDrawerOpen] = useState(false);
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
  const fileInputRef = useRef<HTMLInputElement>(null);

  const MAX_UPLOAD_SIZE_MB = 100;

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Reset input so the same file can be re-selected
    e.target.value = "";

    if (!file.name.toLowerCase().endsWith(".zip")) {
      message.warning(t("skills.zipOnly"));
      return;
    }

    const sizeMB = file.size / (1024 * 1024);
    if (sizeMB > MAX_UPLOAD_SIZE_MB) {
      message.warning(
        t("skills.fileSizeExceeded", { size: sizeMB.toFixed(1) }),
      );
      return;
    }

    await uploadSkill(file);
  };

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
    return await installMarketplaceSkill(marketId, skillId, {
      enable: true,
      overwrite: false,
    });
  };

  const handleAddMarket = () => {
    const next: SkillsMarketSpec = {
      id: "",
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
      return u.hostname.split(".").filter(Boolean)[0] || "";
    } catch {
      const noProto = text.replace(/^https?:\/\//, "");
      if (noProto.includes("/")) {
        return parseOwnerRepo(noProto);
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
      const parsed = parseOwnerRepo(text.replace(/^https?:\/\//, ""));
      if (parsed) return `${parsed.owner}-${parsed.repo}`;
    } catch {
      const parsed = parseOwnerRepo(text.replace(/^https?:\/\//, ""));
      if (parsed) return `${parsed.owner}-${parsed.repo}`;
    }

    return "";
  };

  const handleValidateMarket = async (
    idx: number,
    marketOverride?: SkillsMarketSpec,
  ) => {
    const current = marketOverride ?? marketDrafts[idx];
    if (!current) return;

    let next = current;
    if (!next.id?.trim()) {
      const inferredId = inferMarketIdFromUrl(next.url);
      if (inferredId) {
        next = { ...next, id: inferredId };
        handleUpdateMarket(idx, { id: inferredId });
      }
    }
    if (!next.name?.trim()) {
      const inferredName = inferMarketNameFromUrl(next.url);
      if (inferredName) {
        next = { ...next, name: inferredName };
        handleUpdateMarket(idx, { name: inferredName });
      }
    }

    const result = await validateMarket(next);
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
    setMarketDrafts(createDefaultSkillsMarketTemplates());
  };

  const getSkillsFromMarket = (marketId: string) => {
    const marketUrls = new Set(
      marketplace
        .filter((item) => item.market_id === marketId)
        .flatMap((item) => [item.source_url, item.install_url].filter(Boolean)),
    );
    return skills.filter((s) => s.source && marketUrls.has(s.source));
  };

  const handleRunBulkAction = async (params: {
    type: "enable" | "disable" | "delete";
    marketId: string;
    shouldStop: () => boolean;
    onProgress?: (skillKey: string | null) => void;
  }) => {
    const { type, marketId, shouldStop, onProgress } = params;
    const marketItems = marketplace.filter((item) => item.market_id === marketId);
    const itemBySource = new Map<string, { key: string }>();
    for (const item of marketItems) {
      const key = `${item.market_id}/${item.skill_id}`;
      if (item.source_url) itemBySource.set(item.source_url, { key });
      if (item.install_url) itemBySource.set(item.install_url, { key });
    }

    let total = 0;
    let affected = 0;
    let failed = 0;
    let enabled = 0;
    let installed = 0;
    let disabled = 0;
    let deleted = 0;

    try {
      if (type === "enable") {
        const installedSkills = getSkillsFromMarket(marketId);
        const targetToggle = installedSkills.filter((s) => !s.enabled);
        const installedSources = new Set(skills.map((s) => s.source).filter(Boolean));
        const targetInstall = marketItems.filter(
          (item) =>
            !installedSources.has(item.source_url) &&
            !installedSources.has(item.install_url),
        );
        total = targetToggle.length + targetInstall.length;

        for (const skill of targetToggle) {
          if (shouldStop()) break;
          const key = itemBySource.get(skill.source || "")?.key ?? null;
          onProgress?.(key);
          const ok = await toggleEnabled(skill);
          if (ok) {
            affected += 1;
            enabled += 1;
          } else {
            failed += 1;
          }
        }

        for (const item of targetInstall) {
          if (shouldStop()) break;
          const key = `${item.market_id}/${item.skill_id}`;
          onProgress?.(key);
          const ok = await handleInstallMarketplaceSkill(item.market_id, item.skill_id);
          if (ok) {
            affected += 1;
            installed += 1;
          } else {
            failed += 1;
          }
        }

        const processed = affected + failed;
        return {
          type,
          total,
          affected,
          failed: Math.max(failed, total - processed),
          enabled,
          installed,
          stopped: shouldStop() && processed < total,
        };
      }

      if (type === "disable") {
        const targetSkills = getSkillsFromMarket(marketId).filter((s) => s.enabled);
        total = targetSkills.length;
        for (const skill of targetSkills) {
          if (shouldStop()) break;
          const key = itemBySource.get(skill.source || "")?.key ?? null;
          onProgress?.(key);
          const ok = await toggleEnabled(skill);
          if (ok) {
            affected += 1;
            disabled += 1;
          } else {
            failed += 1;
          }
        }

        const processed = affected + failed;
        return {
          type,
          total,
          affected,
          failed: Math.max(failed, total - processed),
          disabled,
          stopped: shouldStop() && processed < total,
        };
      }

      const toDelete = getSkillsFromMarket(marketId);
      total = toDelete.length;
      for (const skill of toDelete) {
        if (shouldStop()) break;
        const key = itemBySource.get(skill.source || "")?.key ?? null;
        onProgress?.(key);
        const ok = await deleteSkillDirect(skill);
        if (ok) {
          affected += 1;
          deleted += 1;
        } else {
          failed += 1;
        }
      }

      if (deleted > 0) {
        await fetchSkills();
      }

      const processed = affected + failed;
      return {
        type,
        total,
        affected,
        failed: Math.max(failed, total - processed),
        deleted,
        stopped: shouldStop() && processed < total,
      };
    } finally {
      onProgress?.(null);
    }
  };

  return (
    <div className={styles.skillsPage}>
      <div className={styles.header}>
        <div className={styles.headerInfo}>
          <h1 className={styles.title}>{t("skills.title")}</h1>
          <p className={styles.description}>{t("skills.description")}</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            type="file"
            accept=".zip"
            ref={fileInputRef}
            onChange={handleFileChange}
            style={{ display: "none" }}
          />
          <Button
            type="primary"
            onClick={handleUploadClick}
            icon={<UploadOutlined />}
            loading={uploading}
            disabled={uploading}
          >
            {t("skills.uploadSkill")}
          </Button>
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
          <Button
            onClick={() => setMarketplaceDrawerOpen(true)}
            icon={<AppstoreOutlined />}
          >
            {t("skills.marketplaceButton")}
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

      <MarketplaceDrawer
        open={marketplaceDrawerOpen}
        onClose={() => setMarketplaceDrawerOpen(false)}
        marketDrafts={marketDrafts}
        marketCacheTtl={marketCacheTtl}
        marketOverwriteDefault={marketOverwriteDefault}
        savingMarkets={savingMarkets}
        onAddMarket={handleAddMarket}
        onRemoveMarket={handleRemoveMarket}
        onUpdateMarket={handleUpdateMarket}
        onValidateMarket={handleValidateMarket}
        onSaveMarkets={handleSaveMarkets}
        onResetMarketTemplates={handleResetMarketTemplates}
        onCacheTtlChange={setMarketCacheTtl}
        onOverwriteDefaultChange={setMarketOverwriteDefault}
        marketplace={marketplace}
        marketErrors={marketErrors}
        marketMeta={marketMeta}
        marketplaceLoading={marketplaceLoading}
        onRefreshMarketplace={() => {
          void fetchMarketplace(true);
        }}
        installingSkillKey={installingSkillKey}
        onInstallSkill={handleInstallMarketplaceSkill}
        onRunBulkAction={handleRunBulkAction}
      />

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
