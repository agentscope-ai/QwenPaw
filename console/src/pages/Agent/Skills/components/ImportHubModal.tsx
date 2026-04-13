import { useState } from "react";
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

function getSource(url: string): SkillMarket | undefined {
  return skillMarkets.find((market) =>
    url.toLowerCase().startsWith(market.urlPrefix.toLowerCase()),
  );
}

function validateUrl(
  url: string,
): { ok: true; source: string } | { ok: false; message: string } {
  if (!url.trim()) {
    return { ok: false, message: "" };
  }

  try {
    new URL(url);
  } catch {
    return { ok: false, message: "Invalid URL format" };
  }

  const source = getSource(url);
  if (!source) {
    return { ok: false, message: "Unsupported source" };
  }

  if (!isSupportedSkillUrl(url)) {
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
  const [urlError, setUrlError] = useState("");
  const [validSource, setValidSource] = useState("");
  const [activeMarket, setActiveMarket] = useState<string | null>(
    skillMarkets[0]?.key || null,
  );

  const handleClose = () => {
    if (importing) return;
    setImportUrl("");
    setUrlError("");
    setValidSource("");
    setActiveMarket(skillMarkets[0]?.key || null);
    onCancel();
  };

  const handleUrlChange = (value: string) => {
    setImportUrl(value);
    const result = validateUrl(value);
    if (result.ok) {
      setUrlError("");
      setValidSource(result.source);
    } else {
      setUrlError(result.message);
      setValidSource("");
    }
  };

  const handlePaste = async () => {
    try {
      const text = await navigator.clipboard.readText();
      handleUrlChange(text);
    } catch {}
  };

  const handleClear = () => {
    setImportUrl("");
    setUrlError("");
    setValidSource("");
  };

  const toggleMarket = (key: string) => {
    setActiveMarket((prev) => (prev === key ? null : key));
  };

  const handleConfirm = async () => {
    if (importing) return;
    const trimmed = importUrl.trim();
    if (!trimmed) return;
    const result = validateUrl(trimmed);
    if (!result.ok) return;
    await onConfirm(trimmed);
  };

  const canImport = !!validSource && !importing;

  const inputStateClass = urlError
    ? styles.invalid
    : validSource
    ? styles.valid
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
            onChange={(e) => handleUrlChange(e.target.value)}
            placeholder={t("skills.enterSkillUrl") || "https://..."}
            disabled={importing}
            aria-label={t("skills.enterSkillUrl") || "Skill URL"}
            type="text"
          />
          {importUrl && (
            <button
              className={styles.iconButton}
              onClick={handleClear}
              title="Clear"
              type="button"
              aria-label="Clear URL"
            >
              <CloseOutlined />
            </button>
          )}
          <button
            className={styles.iconButton}
            onClick={handlePaste}
            title="Paste from clipboard"
            type="button"
            aria-label="Paste from clipboard"
          >
            <CopyOutlined />
          </button>
        </div>

        <div className={styles.validationStatus}>
          {validSource ? (
            <span className={styles.valid}>
              <CheckCircleOutlined />
              {t("skills.urlValid", {
                defaultValue: "Valid URL from {{source}}",
                source: validSource,
              })}
            </span>
          ) : urlError ? (
            <span className={styles.invalid}>
              <CloseCircleOutlined />
              {urlError}
            </span>
          ) : importing ? (
            <span className={styles.validating}>
              <Spin size="small" />
              {t("common.loading")}
            </span>
          ) : null}
        </div>
      </div>

      <div className={styles.divider}>
        {t("skills.orChooseFromSources", {
          defaultValue: "or choose from supported Skill marketplaces",
        })}
      </div>

      <div className={styles.sourcesGrid}>
        {skillMarkets.map((market: SkillMarket) => (
          <div
            key={market.key}
            className={`${styles.sourceCard} ${
              activeMarket === market.key ? styles.active : ""
            } ${importing ? styles.disabled : ""}`}
            onClick={importing ? undefined : () => toggleMarket(market.key)}
            role="button"
            tabIndex={importing ? -1 : 0}
            onKeyDown={(e) => {
              if (!importing && e.key === "Enter") {
                toggleMarket(market.key);
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
            {t("skills.examplesFrom", {
              defaultValue: "Examples from {{source}}",
              source: activeMarketData.name,
            })}
          </div>
          <div className={styles.examplesList}>
            {activeMarketData.examples.map((example, idx) => (
              <button
                key={idx}
                className={styles.exampleItem}
                onClick={() => handleUrlChange(example.url)}
                title={t("skills.clickToFill", {
                  defaultValue: "Click to fill in URL",
                })}
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
