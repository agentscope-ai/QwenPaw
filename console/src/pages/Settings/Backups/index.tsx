/**
 * Backups page — thin assembly layer.
 * Owns the shared data (backup list + agent list) and composes the
 * sub-feature modules (list/, create/, restore/, import/) together.
 * All modal/flow logic lives in the dedicated hooks and components;
 * this file is intentionally kept short (~90 lines).
 */
import { useCallback, useEffect, useState } from "react";
import { Button, Spin } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import api, { agentsApi } from "@/api";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "@/hooks/useAppMessage";
import type { BackupMeta } from "@/api/types/backup";
import type { AgentSummary } from "@/api/types/agents";

import BackupTable from "./list/BackupTable";
import BackupToolbar from "./list/BackupToolbar";
import ImportButton from "./import/ImportButton";
import ImportConflictModal from "./import/ImportConflictModal";
import { useImportFlow } from "./import/useImportFlow";
import CreateBackupModal from "./create/CreateBackupModal";
import SilentBackupModal from "./create/SilentBackupModal";
import PreRestoreConfirmModal from "./restore/PreRestoreConfirmModal";
import RestoreBackupModal from "./restore/RestoreBackupModal";
import { useRestoreFlow } from "./restore/useRestoreFlow";
import styles from "./index.module.less";

export default function BackupsPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [loading, setLoading] = useState(true);
  const [backups, setBackups] = useState<BackupMeta[]>([]);
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [createOpen, setCreateOpen] = useState(false);

  /** Fetches backups and agents in parallel; both are needed before rendering the table. */
  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [backupRes, agentRes] = await Promise.all([
        api.listBackups(),
        agentsApi.listAgents(),
      ]);
      setBackups(backupRes);
      setAgents(agentRes.agents);
    } catch {
      message.error(t("backup.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [message, t]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const importFlow = useImportFlow({ onSuccess: fetchData });
  const restoreFlow = useRestoreFlow();

  if (loading) {
    return (
      <div className={styles.page}>
        <div className={styles.centerState}>
          <Spin />
        </div>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.settings")}
        current={t("backup.title")}
        extra={
          <div className={styles.headerRight}>
            <ImportButton onPick={importFlow.handleImport} />
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setCreateOpen(true)}
            >
              {t("backup.create")}
            </Button>
          </div>
        }
      />

      <div className={styles.content}>
        <BackupToolbar
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
        />
        <BackupTable
          backups={backups}
          searchQuery={searchQuery}
          onRestore={restoreFlow.handleRestore}
          onRefresh={fetchData}
        />
      </div>

      {/* Import flow */}
      <ImportConflictModal
        conflictMeta={importFlow.conflictMeta}
        onChoice={importFlow.handleConflictChoice}
        onCancel={importFlow.clearConflict}
      />

      {/* Create flow */}
      <CreateBackupModal
        open={createOpen}
        agents={agents}
        onClose={() => setCreateOpen(false)}
        onSuccess={fetchData}
      />

      {/* Restore flow */}
      <PreRestoreConfirmModal
        target={restoreFlow.preRestoreConfirmTarget}
        onCancel={restoreFlow.cancelPreRestore}
        onNoBackup={restoreFlow.confirmRestoreWithoutBackup}
        onYesBackup={restoreFlow.confirmRestoreWithBackup}
      />

      <SilentBackupModal
        target={restoreFlow.preRestoreBackupTarget}
        agentIds={agents.map((a) => a.id)}
        onClose={restoreFlow.onPreRestoreBackupClose}
        onSuccess={restoreFlow.onPreRestoreBackupSuccess}
      />

      {restoreFlow.restoreTarget && (
        <RestoreBackupModal
          backup={restoreFlow.restoreTarget}
          agents={agents}
          open={!!restoreFlow.restoreTarget}
          onClose={() => restoreFlow.setRestoreTarget(null)}
          onSuccess={fetchData}
        />
      )}
    </div>
  );
}
