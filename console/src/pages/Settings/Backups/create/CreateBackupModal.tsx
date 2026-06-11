/**
 * User-initiated backup modal: shows a form (name, description, scope) and,
 * once the user confirms, transitions to a progress view via useBackupRunner.
 * Does NOT handle the silent pre-restore case — see SilentBackupModal for that.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";
import type { AgentSummary } from "@/api/types/agents";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
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

  const handleOpenChange = (visible: boolean) => {
    if (visible) {
      setName(`Backup ${dayjs().format("YYYY-MM-DD HH:mm")}`);
      setDescription("");
      setScope(defaultCreateScope(agents.map((a) => a.id)));
      runner.reset();
    } else if (!runner.loading) {
      onClose();
    }
  };

  /** Validates the name then hands off to useBackupRunner to start the stream. */
  const handleOk = () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    const { scope: backupScope, agents: scopeAgents } = buildScope(
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
      agents: scopeAgents,
    });
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("backup.createTitle")}</DialogTitle>
          <DialogDescription className="sr-only">
            {t("backup.createTitle")}
          </DialogDescription>
        </DialogHeader>

        {runner.loading ? (
          <BackupProgress
            progress={runner.progress}
            progressMsg={runner.progressMsg}
          />
        ) : (
          <div className="flex flex-col gap-4">
            <div>
              <Label className={styles.fieldLabel}>{t("backup.name")}</Label>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t("backup.namePlaceholder")}
              />
            </div>

            <div>
              <Label className={styles.fieldLabel}>
                {t("backup.descriptionLabel")}
              </Label>
              <Textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder={t("backup.descriptionPlaceholder")}
                rows={2}
              />
            </div>

            <BackupScopeForm
              value={scope}
              onChange={setScope}
              agents={agents}
            />

            <div className="flex items-start gap-2 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800 dark-mode:border-blue-800 dark-mode:bg-blue-950 dark-mode:text-blue-200">
              <span>ℹ</span>
              {t("backup.localModelsNotice")}
            </div>
            <div className="flex items-start gap-2 rounded-md border border-yellow-200 bg-yellow-50 px-3 py-2 text-sm text-yellow-800 dark-mode:border-yellow-800 dark-mode:bg-yellow-950 dark-mode:text-yellow-200">
              <span>⚠</span>
              {t("backup.securityNotice")}
            </div>
          </div>
        )}

        {!runner.loading && (
          <DialogFooter>
            <Button variant="outline" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button onClick={handleOk} disabled={!name.trim()}>
              {t("common.confirm")}
            </Button>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}
