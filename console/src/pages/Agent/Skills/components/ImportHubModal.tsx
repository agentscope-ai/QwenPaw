import { useState } from "react";
import { Button, Modal } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import {
  isSupportedSkillUrl,
  SUPPORTED_SKILL_URL_PREFIXES,
} from "@/constants/skill";
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
      <div className={styles.importHintBlock}>
        {hint && <p className={styles.importHintTitle}>{hint}</p>}
        <p className={styles.importHintTitle}>
          {t("skills.supportedSkillUrlSources")}
        </p>
        <ul className={styles.importHintList}>
          {SUPPORTED_SKILL_URL_PREFIXES.map((url) => (
            <li key={url}>{url}</li>
          ))}
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
