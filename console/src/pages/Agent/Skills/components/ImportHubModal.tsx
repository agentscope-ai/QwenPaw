import { useState, useMemo } from "react";
import { Button, Modal } from "@agentscope-ai/design";
import { Spin } from "antd";
import { useTranslation } from "react-i18next";
import {
  ExportOutlined,
  LinkOutlined,
  CopyOutlined,
  CloseOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  DownOutlined,
  PaperClipOutlined,
} from "@ant-design/icons";
import { isSupportedSkillUrl, skillMarkets, type SkillMarket } from "./index";
import styles from "./ImportHubModal.module.less";

interface ImportHubModalProps {
  open: boolean;
  importing: boolean;
  onCancel: () => void;
  onConfirm: (url: string, targetName?: string) => Promise<void>;
  cancelImport?: () => void;
  hint?: string;
}

function validateUrl(
  url: string,
): { ok: true; source: string } | { ok: false; message: string } {
  const trimmed = url.trim();
  if (!trimmed) {
    return { ok: false, message: "" };
  }

  try {
    new URL(trimmed);
  } catch {
    return { ok: false, message: "Invalid URL format" };
  }

  const source = skillMarkets.find((m) =>
    trimmed.toLowerCase().startsWith(m.urlPrefix.toLowerCase()),
  );
  if (!source) {
    return { ok: false, message: "Unsupported source" };
  }

  if (!isSupportedSkillUrl(trimmed)) {
    return { ok: false, message: "URL format not supported" };
  }

  return { ok: true, source: source.name };
}

export function ImportHubModal({
  open,
  importing,
  onCancel,
  onConfirm,
  cancelImport,
  hint,
}: ImportHubModalProps) {
  const { t } = useTranslation();
  const [importUrl, setImportUrl] = useState("");
  const [activeMarket, setActiveMarket] = useState<string | null>(
    skillMarkets[0]?.key || null,
  );

  const validation = useMemo(() => validateUrl(importUrl), [importUrl]);
  const canImport = validation.ok && !importing;

  const handleClose = () => {
    if (importing) return;
    setImportUrl("");
    setActiveMarket(skillMarkets[0]?.key || null);
    onCancel();
  };

  const handleConfirm = async () => {
    if (importing || !validation.ok) return;
    await onConfirm(importUrl.trim());
  };

  const inputStateClass = validation.ok
    ? styles.valid
    : validation.message
    ? styles.invalid
    : "";

  const activeMarketData = skillMarkets.find((m) => m.key === activeMarket);

  return (
    <Modal
      className={styles.importHubModal}
      title={t("skills.importHub")}
      open={open}
      onCancel={handleClose}
      keyboard={!importing}
      closable={!importing}
      maskClosable={!importing}
      width={680}
      footer={
        <div className={styles.modalFooter}>
          <Button
            className={styles.cancelButton}
            onClick={importing && cancelImport ? cancelImport : handleClose}
          >
            {t(
              importing && cancelImport
                ? "skills.cancelImport"
                : "common.cancel",
            )}
          </Button>
          <Button
            className={styles.importButton}
            type="primary"
            onClick={handleConfirm}
            loading={importing}
            disabled={!canImport}
          >
            {t("skills.importHub")}
          </Button>
        </div>
      }
    >
      {hint && (
        <p style={{ margin: "0 0 12px", fontSize: 13, color: "#666" }}>
          {hint}
        </p>
      )}

      <div className={styles.urlInputSection}>
        <div className={`${styles.inputWrapper} ${inputStateClass}`}>
          <LinkOutlined className={styles.urlInputIcon} />
          <input
            className={styles.urlInput}
            value={importUrl}
            onChange={(e) => setImportUrl(e.target.value)}
            placeholder={t("skills.enterSkillUrl")}
            disabled={importing}
            aria-label={t("skills.enterSkillUrl")}
            type="text"
          />
          {importUrl && (
            <button
              className={styles.iconButton}
              onClick={() => setImportUrl("")}
              title={t("common.clear")}
              type="button"
              aria-label={t("common.clear")}
            >
              <CloseOutlined />
            </button>
          )}
          <button
            className={styles.iconButton}
            onClick={async () => {
              try {
                const text = await navigator.clipboard.readText();
                setImportUrl(text);
              } catch {}
            }}
            title={t("common.paste")}
            type="button"
            aria-label={t("common.paste")}
          >
            <CopyOutlined />
          </button>
        </div>

        <div className={styles.validationStatus}>
          {validation.ok ? (
            <span className={styles.valid}>
              <CheckCircleOutlined />
              {t("skills.urlValid", { source: validation.source })}
            </span>
          ) : validation.message ? (
            <span className={styles.invalid}>
              <CloseCircleOutlined />
              {validation.message}
            </span>
          ) : importing ? (
            <span className={styles.validating}>
              <Spin size="small" />
              {t("common.loading")}
            </span>
          ) : null}
        </div>
      </div>

      <div className={styles.divider}>{t("skills.orChooseFromSources")}</div>

      <div className={styles.sourcesGrid}>
        {skillMarkets.map((market: SkillMarket) => (
          <div
            key={market.key}
            className={`${styles.sourceCard} ${
              activeMarket === market.key ? styles.active : ""
            } ${importing ? styles.disabled : ""}`}
            onClick={
              importing
                ? undefined
                : () =>
                    setActiveMarket((prev) =>
                      prev === market.key ? null : market.key,
                    )
            }
            role="button"
            tabIndex={importing ? -1 : 0}
            onKeyDown={(e) => {
              if (!importing && e.key === "Enter") {
                setActiveMarket((prev) =>
                  prev === market.key ? null : market.key,
                );
              }
            }}
            aria-expanded={activeMarket === market.key}
            aria-label={market.name}
          >
            <a
              href={market.homepage}
              target="_blank"
              rel="noopener noreferrer"
              className={styles.externalLink}
              onClick={(e) => e.stopPropagation()}
              title={market.homepage}
              aria-label={`${market.name} homepage`}
            >
              <ExportOutlined />
            </a>
            <div className={styles.sourceCardName}>{market.name}</div>
            <div className={styles.sourceCardMeta}>
              {market.examples.length > 0 && (
                <>
                  {market.examples.length} examples
                  <DownOutlined
                    className={`${styles.sourceCardArrow} ${
                      activeMarket === market.key ? styles.active : ""
                    }`}
                  />
                </>
              )}
            </div>
          </div>
        ))}
      </div>

      {activeMarketData && activeMarketData.examples.length > 0 && (
        <div className={styles.examplesPanel}>
          <div className={styles.examplesHeader}>
            <PaperClipOutlined />
            {t("skills.examplesFrom", { source: activeMarketData.name })}
          </div>
          <div className={styles.examplesList}>
            {activeMarketData.examples.map((example, idx) => (
              <button
                key={idx}
                className={styles.exampleItem}
                onClick={() => setImportUrl(example.url)}
                title={t("skills.clickToFill")}
                type="button"
              >
                <LinkOutlined className={styles.exampleItemIcon} />
                <span className={styles.exampleUrl}>{example.url}</span>
                <span className={styles.exampleItemLabel}>{example.label}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </Modal>
  );
}
