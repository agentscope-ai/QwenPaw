/**
 * User-initiated backup modal: shows a form (name, description, scope) and,
 * once the user confirms, transitions to a progress view via useBackupRunner.
 * Does NOT handle the silent pre-restore case — see SilentBackupModal for that.
 */
import { useLayoutEffect, useState } from "react";
import { Modal, Input, Alert, Button, Space } from "antd";
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";
import type { AgentSummary } from "@/api/types/agents";
import type { BackupJobSnapshot } from "@/api/types/backup";
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
  resumeJob?: BackupJobSnapshot | null;
}

export default function CreateBackupModal({
  open,
  agents,
  onClose,
  onSuccess,
  resumeJob,
}: Props) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [scope, setScope] = useState<ScopeFormValue>(
    defaultCreateScope(agents.map((a) => a.id)),
  );

  const runner = useBackupRunner({ onSuccess, onClose });

  // Initialize before interaction; the entrance animation must not reset edits.
  useLayoutEffect(() => {
    if (!open) return;
    if (resumeJob) {
      runner.resume(resumeJob);
      return;
    }
    setName(`Backup ${dayjs().format("YYYY-MM-DD HH:mm")}`);
    setDescription("");
    setScope(defaultCreateScope(agents.map((a) => a.id)));
    runner.reset();
    // Take a fresh snapshot on opening, not on later form/runner renders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  /** Validates the name then hands off to useBackupRunner to start the stream. */
  const handleOk = () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    const { scope: backupScope, agents: selectedAgentIds } = buildScope(
      scope.backupMode,
      scope.backupMode === "full"
        ? agents.map((agent) => agent.id)
        : scope.selectedAgents,
      scope.globalConfig,
      scope.includeSkillPool,
      scope.includeSecrets,
    );
    runner.start({
      name: trimmed,
      description: description.trim() || undefined,
      scope: backupScope,
      agents: selectedAgentIds,
    });
  };

  return (
    <Modal
      title={t("backup.createTitle")}
      width={640}
      styles={{
        body: {
          maxHeight: "min(68dvh, 640px)",
          overflowY: "auto",
          paddingInline: 2,
        },
      }}
      open={open}
      onCancel={runner.loading ? undefined : onClose}
      onOk={runner.loading ? undefined : handleOk}
      okButtonProps={
        runner.loading
          ? { style: { display: "none" } }
          : { disabled: !name.trim() }
      }
      cancelText={t("common.cancel")}
      okText={t("common.confirm")}
      footer={
        runner.loading ? (
          <Button danger onClick={runner.cancel}>
            {t("common.cancel")}
          </Button>
        ) : undefined
      }
      destroyOnHidden
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
