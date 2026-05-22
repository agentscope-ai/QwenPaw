import { useMemo, useState } from "react";
import { Button, Modal, Input } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import {
  mcpTemplates,
  MCP_CATEGORIES,
  type MCPMarketTemplate,
  type MCPCategory,
} from "../market/mcpTemplates";
import type { MCPClientCreatePayload } from "../market/installTemplate";
import { MCPTemplateCard } from "./MCPTemplateCard";
import { MCPInstallWizard } from "./MCPInstallWizard";
import { MCPMarketTitle } from "./MCPMarketIcon";
import styles from "./MCPMarketplaceModal.module.less";

interface MCPMarketplaceModalProps {
  open: boolean;
  existingKeys: string[];
  installing: boolean;
  onCancel: () => void;
  onInstall: (
    clientKey: string,
    payload: MCPClientCreatePayload,
  ) => Promise<boolean>;
}

export function MCPMarketplaceModal({
  open,
  existingKeys,
  installing,
  onCancel,
  onInstall,
}: MCPMarketplaceModalProps) {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<MCPCategory | "all">("all");
  const [selectedTemplate, setSelectedTemplate] =
    useState<MCPMarketTemplate | null>(null);

  const filteredTemplates = useMemo(() => {
    const q = search.trim().toLowerCase();
    return mcpTemplates.filter((tpl) => {
      if (category !== "all" && tpl.category !== category) return false;
      if (!q) return true;
      const name = t(tpl.nameKey).toLowerCase();
      const desc = t(tpl.descriptionKey).toLowerCase();
      return (
        name.includes(q) || desc.includes(q) || tpl.id.toLowerCase().includes(q)
      );
    });
  }, [search, category, t]);

  const handleClose = () => {
    if (installing) return;
    setSearch("");
    setCategory("all");
    setSelectedTemplate(null);
    onCancel();
  };

  const handleInstall = async (
    clientKey: string,
    payload: MCPClientCreatePayload,
  ) => {
    const ok = await onInstall(clientKey, payload);
    if (ok) {
      setSelectedTemplate(null);
      setSearch("");
      setCategory("all");
    }
    return ok;
  };

  return (
    <Modal
      className={styles.marketplaceModal}
      title={<MCPMarketTitle title={t("mcp.market.title")} />}
      open={open}
      onCancel={handleClose}
      width={720}
      footer={null}
      keyboard={!installing}
      closable={!installing}
      maskClosable={!installing}
    >
      {selectedTemplate ? (
        <MCPInstallWizard
          template={selectedTemplate}
          existingKeys={existingKeys}
          installing={installing}
          onBack={() => setSelectedTemplate(null)}
          onInstall={handleInstall}
        />
      ) : (
        <>
          <div className={styles.toolbar}>
            <Input
              className={styles.searchInput}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t("mcp.market.searchPlaceholder")}
              allowClear
            />
          </div>

          <div className={styles.categoryTabs}>
            <button
              type="button"
              className={`${styles.categoryTab} ${
                category === "all" ? styles.active : ""
              }`}
              onClick={() => setCategory("all")}
            >
              {t("mcp.market.categoryAll")}
            </button>
            {MCP_CATEGORIES.map((cat) => (
              <button
                key={cat}
                type="button"
                className={`${styles.categoryTab} ${
                  category === cat ? styles.active : ""
                }`}
                onClick={() => setCategory(cat)}
              >
                {t(`mcp.market.categories.${cat}`)}
              </button>
            ))}
          </div>

          {filteredTemplates.length === 0 ? (
            <div className={styles.emptyTemplates}>
              {t("mcp.market.noResults")}
            </div>
          ) : (
            <div className={styles.templatesGrid}>
              {filteredTemplates.map((tpl) => (
                <MCPTemplateCard
                  key={tpl.id}
                  template={tpl}
                  selected={false}
                  onSelect={() => setSelectedTemplate(tpl)}
                />
              ))}
            </div>
          )}

          <div className={styles.modalFooter} style={{ marginTop: 16 }}>
            <Button onClick={handleClose}>{t("common.cancel")}</Button>
          </div>
        </>
      )}
    </Modal>
  );
}
