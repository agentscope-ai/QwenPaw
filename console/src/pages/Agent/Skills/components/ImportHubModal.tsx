import { useState, useMemo } from "react";
import { Button, Modal } from "@agentscope-ai/design";
import { Spin } from "antd";
import { useTranslation } from "react-i18next";
import {
  LinkOutlined,
  CloseOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
} from "@ant-design/icons";
import { skillMarkets, type SkillMarket } from "./index";
import styles from "./ImportHubModal.module.less";

interface ImportHubModalProps {
  open: boolean;
  importing: boolean;
  onCancel: () => void;
  onConfirm: (url: string, targetName?: string) => Promise<void>;
  cancelImport?: () => void;
  hint?: string;
}

type ValidationResult =
  | { ok: true; source: string }
  | { ok: false; messageKey: string };

function normalizeHost(host: string): string {
  return host.toLowerCase().replace(/^www\./, "");
}

function validateUrl(url: string): ValidationResult {
  const trimmed = url.trim();
  if (!trimmed) {
    return { ok: false, messageKey: "" };
  }

  let parsedInput: URL;
  try {
    parsedInput = new URL(trimmed);
  } catch {
    return { ok: false, messageKey: "skills.invalidUrl" };
  }

  const inputHost = normalizeHost(parsedInput.host);
  const inputPath = parsedInput.pathname.toLowerCase();

  const source = skillMarkets.find((m) => {
    let parsedPrefix: URL;
    try {
      parsedPrefix = new URL(m.urlPrefix);
    } catch {
      return false;
    }
    return (
      inputHost === normalizeHost(parsedPrefix.host) &&
      inputPath.startsWith(parsedPrefix.pathname.toLowerCase())
    );
  });
  if (!source) {
    return { ok: false, messageKey: "skills.invalidSkillUrlSource" };
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

  const validation = useMemo(() => validateUrl(importUrl), [importUrl]);
  const canImport = validation.ok && !importing;

  const handleClose = () => {
    if (importing) return;
    setImportUrl("");
    onCancel();
  };

  const handleConfirm = async () => {
    if (importing || !validation.ok) return;
    await onConfirm(importUrl.trim());
  };

  const inputStateClass = validation.ok
    ? styles.valid
    : validation.messageKey
    ? styles.invalid
    : "";

  return (
    <Modal
      className={styles.importHubModal}
      title={t("skills.importHub")}
      open={open}
      onCancel={handleClose}
      keyboard={!importing}
      closable={!importing}
      maskClosable={!importing}
      width={560}
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
            {t("common.confirm")}
          </Button>
        </div>
      }
    >
      {hint && <p className={styles.hintText}>{hint}</p>}

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
        </div>

        <div className={styles.validationStatus}>
          {validation.ok ? (
            <span className={styles.valid}>
              <CheckCircleOutlined />
              {t("skills.urlValid", { source: validation.source })}
            </span>
          ) : validation.messageKey ? (
            <span className={styles.invalid}>
              <CloseCircleOutlined />
              {t(validation.messageKey)}
            </span>
          ) : importing ? (
            <span className={styles.validating}>
              <Spin size="small" />
              {t("common.loading")}
            </span>
          ) : null}
        </div>
      </div>

      <div className={styles.sourcesSection}>
        <div className={styles.sourcesHeader}>
          {t("skills.supportedSources")}
        </div>
        <div className={styles.sourcesList}>
          {skillMarkets.map((market: SkillMarket) => {
            const example = market.examples[0]?.url;
            return (
              <div
                key={market.key}
                className={`${styles.sourceRow} ${
                  importing ? styles.disabled : ""
                }`}
                role="button"
                tabIndex={importing || !example ? -1 : 0}
                title={example ? t("skills.clickToFill") : undefined}
                onClick={
                  importing || !example
                    ? undefined
                    : () => setImportUrl(example)
                }
                onKeyDown={(e) => {
                  if (!importing && example && e.key === "Enter") {
                    setImportUrl(example);
                  }
                }}
              >
                <a
                  href={market.homepage}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={styles.sourceName}
                  onClick={(e) => e.stopPropagation()}
                >
                  {market.name}
                </a>
                <span className={styles.sourceExample}>{example}</span>
              </div>
            );
          })}
        </div>
      </div>
    </Modal>
  );
}
