import { useState } from "react";
import { Button, Modal } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { ExportOutlined } from "@ant-design/icons";
import { isSupportedSkillUrl, skillMarkets, type SkillMarket } from "./index";
import styles from "../index.module.less";

interface ImportHubModalProps {
  open: boolean;
  importing: boolean;
  onCancel: () => void;
  onConfirm: (url: string, targetName?: string) => Promise<void>;
  cancelImport?: () => void;
  hint?: string;
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
  const [importUrlError, setImportUrlError] = useState("");

  const handleClose = () => {
    if (importing) return;
    setImportUrl("");
    setImportUrlError("");
    onCancel();
  };

  const handleUrlChange = (value: string) => {
    setImportUrl(value);
    const trimmed = value.trim();
    if (trimmed && !isSupportedSkillUrl(trimmed)) {
      setImportUrlError(t("skills.invalidSkillUrlSource"));
      return;
    }
    setImportUrlError("");
  };

  const handleConfirm = async () => {
    if (importing) return;
    const trimmed = importUrl.trim();
    if (!trimmed) return;
    if (!isSupportedSkillUrl(trimmed)) {
      setImportUrlError(t("skills.invalidSkillUrlSource"));
      return;
    }
    await onConfirm(trimmed);
  };

  return (
    <Modal
      className={styles.importHubModal}
      title={t("skills.importHub")}
      open={open}
      onCancel={handleClose}
      keyboard={!importing}
      closable={!importing}
      maskClosable={!importing}
      footer={
        <div style={{ textAlign: "right" }}>
          <Button
            onClick={importing && cancelImport ? cancelImport : handleClose}
            style={{ marginRight: 8 }}
          >
            {t(
              importing && cancelImport
                ? "skills.cancelImport"
                : "common.cancel",
            )}
          </Button>
          <Button
            type="primary"
            onClick={handleConfirm}
            loading={importing}
            disabled={importing || !importUrl.trim() || !!importUrlError}
          >
            {t("skills.importHub")}
          </Button>
        </div>
      }
      width={760}
    >
      <div className={styles.importMarketsSection}>
        {hint && <p className={styles.importSectionTitle}>{hint}</p>}
        <p className={styles.importSectionTitle}>
          {t("skills.supportedSkillUrlSources")}
        </p>
        <div className={styles.importMarketsGrid}>
          {skillMarkets.map((market: SkillMarket) => (
            <div key={market.key} className={styles.marketCard}>
              <div className={styles.marketCardHeader}>
                <a
                  href={market.homepage}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={styles.marketName}
                  onClick={(e) => e.stopPropagation()}
                  title={market.homepage}
                >
                  {market.name}
                </a>
                <a
                  href={market.homepage}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={styles.marketArrow}
                  onClick={(e) => e.stopPropagation()}
                  title={market.homepage}
                >
                  <ExportOutlined />
                </a>
              </div>
              {market.examples.length > 0 && (
                <div className={styles.marketExamples}>
                  <span className={styles.examplesLabel}>
                    {t("skills.examples")}
                  </span>
                  <div className={styles.exampleTags}>
                    {market.examples.map((example, idx) => (
                      <button
                        key={idx}
                        className={styles.exampleTag}
                        onClick={() => handleUrlChange(example.url)}
                        title={example.url}
                      >
                        {example.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      <input
        className={styles.importUrlInput}
        value={importUrl}
        onChange={(e) => handleUrlChange(e.target.value)}
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
  );
}
