import { useState, useCallback } from "react";
import { Button, Modal, Spin } from "@agentscope-ai/design";
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

type ValidationStatus = "default" | "validating" | "valid" | "invalid";

interface ValidationState {
  status: ValidationStatus;
  message?: string;
  source?: string;
}

interface ImportHubModalProps {
  open: boolean;
  importing: boolean;
  onCancel: () => void;
  onConfirm: (url: string, targetName?: string) => Promise<void>;
  cancelImport?: () => void;
  hint?: string;
}

const MARKET_ICONS: Record<string, string> = {
  "skills.sh": "🛠️",
  clawhub: "🐾",
  skillsmp: "📦",
  lobehub: "🧠",
  github: "🐙",
  modelscope: "🔬",
};

function detectSource(url: string): SkillMarket | undefined {
  return skillMarkets.find((market) =>
    url.toLowerCase().startsWith(market.urlPrefix.toLowerCase()),
  );
}

async function validateSkillUrl(url: string): Promise<ValidationState> {
  if (!url.trim()) {
    return { status: "default" };
  }

  try {
    // eslint-disable-next-line no-new
    new URL(url);
  } catch {
    return {
      status: "invalid",
      message: "Invalid URL format",
    };
  }

  const source = detectSource(url);
  if (!source) {
    return {
      status: "invalid",
      message: "Unsupported source",
    };
  }

  if (!isSupportedSkillUrl(url)) {
    return {
      status: "invalid",
      message: "URL format not supported",
    };
  }

  return { status: "valid", source: source.name };
}

function ValidationStatus({ validation }: { validation: ValidationState }) {
  const { t } = useTranslation();

  if (validation.status === "default") {
    return <div className={styles.validationStatus} />;
  }

  if (validation.status === "validating") {
    return (
      <div
        className={`${styles.validationStatus} ${styles.validating}`}
        aria-live="polite"
      >
        <Spin size="small" />
        {t("skills.validatingUrl", { defaultValue: "Validating URL..." })}
      </div>
    );
  }

  if (validation.status === "valid") {
    return (
      <div className={`${styles.validationStatus} ${styles.valid}`}>
        <CheckCircleOutlined />
        {t("skills.urlValid", {
          defaultValue: "Valid URL from {{source}}",
          source: validation.source,
        })}
      </div>
    );
  }

  return (
    <div className={`${styles.validationStatus} ${styles.invalid}`}>
      <CloseCircleOutlined />
      {validation.message ||
        t("skills.invalidUrl", { defaultValue: "Invalid URL" })}
    </div>
  );
}

interface SourceCardProps {
  market: SkillMarket;
  isActive: boolean;
  onClick: () => void;
  disabled?: boolean;
}

function SourceCard({ market, isActive, onClick, disabled }: SourceCardProps) {
  const icon = MARKET_ICONS[market.key] || "📦";
  const exampleCount = market.examples.length;

  return (
    <div
      className={`${styles.sourceCard} ${isActive ? styles.active : ""} ${disabled ? styles.disabled : ""}`}
      onClick={disabled ? undefined : onClick}
      role="button"
      tabIndex={disabled ? -1 : 0}
      onKeyDown={(e) => {
        if (!disabled && e.key === "Enter") {
          onClick();
        }
      }}
      aria-expanded={isActive}
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
      <div className={styles.sourceCardIcon}>{icon}</div>
      <div className={styles.sourceCardName}>{market.name}</div>
      <div className={styles.sourceCardMeta}>
        {exampleCount > 0 && (
          <>
            {exampleCount} {"examples"}
            <DownOutlined className={styles.sourceCardArrow} />
          </>
        )}
      </div>
    </div>
  );
}

interface ExamplesPanelProps {
  market: SkillMarket;
  onSelect: (url: string) => void;
}

function ExamplesPanel({ market, onSelect }: ExamplesPanelProps) {
  const { t } = useTranslation();

  if (market.examples.length === 0) {
    return null;
  }

  return (
    <div className={styles.examplesPanel}>
      <div className={styles.examplesHeader}>
        <PaperClipOutlined />
        {t("skills.examplesFrom", {
          defaultValue: "Examples from {{source}}",
          source: market.name,
        })}
      </div>
      <div className={styles.examplesList}>
        {market.examples.map((example, idx) => (
          <button
            key={idx}
            className={styles.exampleItem}
            onClick={() => onSelect(example.url)}
            title={t("skills.clickToFill", {
              defaultValue: "Click to fill in URL",
            })}
            type="button"
          >
            <LinkOutlined className={styles.exampleItemIcon} />
            <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {example.url}
            </span>
            <span className={styles.exampleItemLabel}>{example.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
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
  const [validation, setValidation] = useState<ValidationState>({
    status: "default",
  });
  const [activeMarket, setActiveMarket] = useState<string | null>(null);

  const handleClose = useCallback(() => {
    if (importing) return;
    setImportUrl("");
    setValidation({ status: "default" });
    setActiveMarket(null);
    onCancel();
  }, [importing, onCancel]);

  const handleUrlChange = useCallback(async (value: string) => {
    setImportUrl(value);
    if (!value.trim()) {
      setValidation({ status: "default" });
      return;
    }
    setValidation({ status: "validating" });
    const result = await validateSkillUrl(value);
    setValidation(result);
  }, []);

  const handlePaste = useCallback(async () => {
    try {
      const text = await navigator.clipboard.readText();
      handleUrlChange(text);
    } catch {
    }
  }, [handleUrlChange]);

  const handleClear = useCallback(() => {
    setImportUrl("");
    setValidation({ status: "default" });
  }, []);

  const handleSelectExample = useCallback(
    (url: string) => {
      handleUrlChange(url);
    },
    [handleUrlChange],
  );

  const toggleMarket = useCallback((key: string) => {
    setActiveMarket((prev) => (prev === key ? null : key));
  }, []);

  const handleConfirm = useCallback(async () => {
    if (importing) return;
    const trimmed = importUrl.trim();
    if (!trimmed) return;
    if (validation.status !== "valid") return;
    await onConfirm(trimmed);
  }, [importUrl, importing, validation.status, onConfirm]);

  const canImport = validation.status === "valid" && !importing;

  const inputStateClass =
    validation.status === "default" ? "" : styles[validation.status];

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
            onClick={
              importing && cancelImport ? cancelImport : handleClose
            }
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
        <div
          className={`${styles.inputWrapper} ${inputStateClass}`}
          style={{ marginBottom: 0 }}
        >
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
        <ValidationStatus validation={validation} />
      </div>

      <div className={styles.divider}>
        {t("skills.orChooseFromSources", {
          defaultValue: "or choose from popular sources",
        })}
      </div>

      <div className={styles.sourcesGrid}>
        {skillMarkets.map((market: SkillMarket) => (
          <SourceCard
            key={market.key}
            market={market}
            isActive={activeMarket === market.key}
            onClick={() => toggleMarket(market.key)}
            disabled={importing}
          />
        ))}
      </div>

      {activeMarket && (
        <ExamplesPanel
          market={skillMarkets.find((m) => m.key === activeMarket)!}
          onSelect={handleSelectExample}
        />
      )}
    </Modal>
  );
}
