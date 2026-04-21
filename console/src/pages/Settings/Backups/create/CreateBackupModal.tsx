/**
 * User-initiated backup modal: shows a form (name, description, scope) and,
 * once the user confirms, transitions to a progress view via useBackupRunner.
 * Does NOT handle the silent pre-restore case — see SilentBackupModal for that.
 */
import { useState } from "react";
import { Modal, Input, Alert, Space } from "antd";
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";
import type { AgentSummary } from "@/api/types/agents";
import { useBackupRunner } from "../shared/useBackupRunner";
import { buildScope, defaultCreateScope } from "../shared/scope";
import BackupProgress from "./BackupProgress";
import BackupScopeForm from "./BackupScopeForm";
import type { ScopeFormValue } from "./BackupScopeForm";
import styles from "./CreateBackupModal.module.less";

interface Props {
  open: boolean;
  agents: AgentSummary[];
  onClose: () => void;
  onSuccess: () => void;
}

export default function CreateBackupModal({
  open,
  agents,
  onClose,
  onSuccess,
}: Props) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [scope, setScope] = useState<ScopeFormValue>(
    defaultCreateScope(agents.map((a) => a.id)),
  );

  const runner = useBackupRunner({ onSuccess, onClose });

  /** Resets form and runner state each time the modal opens for a fresh session. */
  const handleAfterOpenChange = (visible: boolean) => {
    if (visible) {
      setName(`Backup ${dayjs().format("YYYY-MM-DD HH:mm")}`);
      setDescription("");
      setScope(defaultCreateScope(agents.map((a) => a.id)));
      runner.reset();
    }
  };

  /** Validates the name then hands off to useBackupRunner to start the stream. */
  const handleOk = () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    const { scope: backupScope, agents } = buildScope(
      scope.backupMode,
      scope.selectedAgents,
      scope.globalConfig,
      scope.includeSkillPool,
      scope.includeSecrets,
    );
    runner.start({
      name: trimmed,
      description: description.trim() || undefined,
      scope: backupScope,
      agents,
    });
  };

  return (
    <Modal
      title={t("backup.createTitle")}
      open={open}
      onCancel={runner.loading ? undefined : onClose}
      onOk={runner.loading ? undefined : handleOk}
      okButtonProps={
        runner.loading
          ? { style: { display: "none" } }
          : { disabled: !name.trim() }
      }
      cancelText={runner.loading ? t("common.cancel") : undefined}
      okText={t("common.confirm")}
      destroyOnHidden
      afterOpenChange={handleAfterOpenChange}
      centered
      closable={!runner.loading}
      maskClosable={!runner.loading}
    >
      {runner.loading ? (
        <BackupProgress
          progress={runner.progress}
          progressMsg={runner.progressMsg}
        />
      ) : (
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <div>
            <div className={styles.fieldLabel}>{t("backup.name")}</div>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("backup.namePlaceholder")}
            />
          </div>

          <div>
            <div className={styles.fieldLabel}>
              {t("backup.descriptionLabel")}
            </div>
            <Input.TextArea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t("backup.descriptionPlaceholder")}
              rows={2}
            />
          </div>

          <BackupScopeForm value={scope} onChange={setScope} agents={agents} />

          <Alert type="info" showIcon message={t("backup.localModelsNotice")} />
          <Alert type="warning" showIcon message={t("backup.securityNotice")} />
        </Space>
      )}
    </Modal>
  );
}
