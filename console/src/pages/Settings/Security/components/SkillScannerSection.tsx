import { useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import { Trash2, ShieldCheck, Eye, Package } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useSkillScanner } from "../useSkillScanner";
import type {
  BlockedSkillRecord,
  BlockedSkillFinding,
  SkillScannerWhitelistEntry,
  SkillScannerMode,
} from "../../../../api/modules/security";
import { skillApi } from "../../../../api/modules/skill";
import styles from "../index.module.less";

function FindingsModal({
  findings,
  skillName,
  open,
  onClose,
}: {
  findings: BlockedSkillFinding[];
  skillName: string;
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) onClose();
      }}
    >
      <DialogContent className="max-w-[700px]">
        <DialogHeader>
          <DialogTitle>
            {t("security.skillScanner.scanAlerts.viewFindings")} - {skillName}
          </DialogTitle>
        </DialogHeader>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead style={{ width: 200 }}>Title</TableHead>
              <TableHead style={{ width: 160 }}>File</TableHead>
              <TableHead>Description</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {findings.map((f, idx) => (
              <TableRow key={idx}>
                <TableCell>{f.title}</TableCell>
                <TableCell>
                  {f.line_number
                    ? `${f.file_path}:${f.line_number}`
                    : f.file_path}
                </TableCell>
                <TableCell className="max-w-[200px] truncate">
                  {f.description}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </DialogContent>
    </Dialog>
  );
}

export function SkillScannerSection() {
  const { t } = useTranslation();
  const {
    config,
    blockedHistory,
    whitelist,
    loading,
    updateConfig,
    addToWhitelist,
    removeFromWhitelist,
    removeBlockedEntry,
    clearBlockedHistory,
  } = useSkillScanner();

  const { message } = useAppMessage();
  const [saving, setSaving] = useState(false);
  const [findingsModal, setFindingsModal] = useState<{
    open: boolean;
    findings: BlockedSkillFinding[];
    skillName: string;
  }>({ open: false, findings: [], skillName: "" });

  const [removeWhitelistDialog, setRemoveWhitelistDialog] = useState<
    string | null
  >(null);
  const [clearHistoryDialog, setClearHistoryDialog] = useState(false);

  const [pendingTimeout, setPendingTimeout] = useState<number | null>(null);

  const handleModeChange = useCallback(
    async (mode: SkillScannerMode) => {
      setSaving(true);
      const ok = await updateConfig({ mode });
      if (ok) message.success(t("security.skillScanner.saveSuccess"));
      else message.error(t("security.skillScanner.saveFailed"));
      setSaving(false);
    },
    [updateConfig, t],
  );

  const handleTimeoutBlur = useCallback(async () => {
    const value = pendingTimeout;
    if (value === null || value < 5 || value > 300) {
      setPendingTimeout(null);
      return;
    }
    setSaving(true);
    const ok = await updateConfig({ timeout: value });
    if (ok) message.success(t("security.skillScanner.saveSuccess"));
    else message.error(t("security.skillScanner.saveFailed"));
    setPendingTimeout(null);
    setSaving(false);
  }, [pendingTimeout, updateConfig, t]);

  const handleAllowSkill = useCallback(
    async (record: BlockedSkillRecord, index: number) => {
      const ok = await addToWhitelist(record.skill_name, record.content_hash);
      if (ok) {
        message.success(t("security.skillScanner.whitelist.addSuccess"));
        await removeBlockedEntry(index);
      } else {
        message.error(t("security.skillScanner.whitelist.addFailed"));
      }
    },
    [addToWhitelist, removeBlockedEntry, t],
  );

  const handleRemoveWhitelistConfirm = useCallback(
    async (skillName: string) => {
      const ok = await removeFromWhitelist(skillName);
      if (!ok) {
        message.error(t("security.skillScanner.whitelist.removeFailed"));
        return;
      }
      try {
        await skillApi.disableSkill(skillName);
        message.success(t("security.skillScanner.whitelist.removeAndDisabled"));
      } catch {
        message.success(t("security.skillScanner.whitelist.removeSuccess"));
      }
      setRemoveWhitelistDialog(null);
    },
    [removeFromWhitelist, t],
  );

  const handleClearHistoryConfirm = useCallback(async () => {
    await clearBlockedHistory();
    setClearHistoryDialog(false);
  }, [clearBlockedHistory]);

  if (loading || !config) return null;

  const enabled = config.mode !== "off";

  return (
    <>
      <div className={`${styles.formCard} border rounded-lg p-4`}>
        <div className={styles.skillScannerConfig}>
          <div className={styles.skillScannerConfigItem}>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className={`${styles.skillScannerLabel} cursor-default`}>
                  {t("security.skillScanner.mode")}
                </span>
              </TooltipTrigger>
              <TooltipContent>
                {t("security.skillScanner.modeTooltip")}
              </TooltipContent>
            </Tooltip>
            <Select
              value={config.mode}
              onValueChange={(v) => handleModeChange(v as SkillScannerMode)}
              disabled={saving}
            >
              <SelectTrigger style={{ width: 140 }}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="block">
                  {t("security.skillScanner.modeBlock")}
                </SelectItem>
                <SelectItem value="warn">
                  {t("security.skillScanner.modeWarn")}
                </SelectItem>
                <SelectItem value="off">
                  {t("security.skillScanner.modeOff")}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className={styles.skillScannerConfigItem}>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className={`${styles.skillScannerLabel} cursor-default`}>
                  {t("security.skillScanner.timeout")}
                </span>
              </TooltipTrigger>
              <TooltipContent>
                {t("security.skillScanner.timeoutTooltip")}
              </TooltipContent>
            </Tooltip>
            <Input
              type="number"
              min={5}
              max={300}
              value={pendingTimeout ?? config.timeout}
              onChange={(e) => setPendingTimeout(parseInt(e.target.value, 10))}
              onBlur={handleTimeoutBlur}
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleTimeoutBlur();
              }}
              disabled={!enabled}
              style={{ width: 100 }}
            />
          </div>
        </div>
      </div>

      <Tabs defaultValue="scanAlerts" className={styles.innerTabs}>
        <TabsList>
          <TabsTrigger value="scanAlerts">
            {t("security.skillScanner.scanAlerts.title")}
            {blockedHistory.length > 0 && (
              <span className={styles.tabBadge}>{blockedHistory.length}</span>
            )}
          </TabsTrigger>
          <TabsTrigger value="whitelist">
            {t("security.skillScanner.whitelist.title")}
            {whitelist.length > 0 && (
              <span className={styles.tabBadge}>{whitelist.length}</span>
            )}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="scanAlerts">
          <div className={styles.tabPanelContent}>
            {blockedHistory.length > 0 && (
              <div className={styles.tabPanelHeader}>
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={() => setClearHistoryDialog(true)}
                >
                  {t("security.skillScanner.scanAlerts.clearAll")}
                </Button>
              </div>
            )}
            <div className={`${styles.tableCard} border rounded-lg`}>
              {blockedHistory.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 gap-2 text-muted-foreground">
                  <Package size={48} strokeWidth={1} />
                  <span className={styles.emptyText}>
                    {t("security.skillScanner.scanAlerts.empty")}
                  </span>
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead style={{ width: 180 }}>
                        {t("security.skillScanner.scanAlerts.skillName")}
                      </TableHead>
                      <TableHead style={{ width: 100 }}>
                        {t("security.skillScanner.scanAlerts.action")}
                      </TableHead>
                      <TableHead style={{ width: 180 }}>
                        {t("security.skillScanner.scanAlerts.time")}
                      </TableHead>
                      <TableHead style={{ width: 200 }}>
                        {t("security.skillScanner.scanAlerts.actions")}
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {blockedHistory.map((record, index) => (
                      <TableRow key={index}>
                        <TableCell>{record.skill_name}</TableCell>
                        <TableCell>
                          <Badge
                            variant="outline"
                            className={`text-xs ${
                              record.action === "blocked"
                                ? "border-red-400 text-red-600"
                                : "border-orange-400 text-orange-600"
                            }`}
                          >
                            {record.action === "blocked"
                              ? t(
                                  "security.skillScanner.scanAlerts.actionBlocked",
                                )
                              : t(
                                  "security.skillScanner.scanAlerts.actionWarned",
                                )}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          {(() => {
                            try {
                              return new Date(
                                record.blocked_at,
                              ).toLocaleString();
                            } catch {
                              return record.blocked_at;
                            }
                          })()}
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1">
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-7 w-7 p-0"
                                  onClick={() =>
                                    setFindingsModal({
                                      open: true,
                                      findings: record.findings,
                                      skillName: record.skill_name,
                                    })
                                  }
                                >
                                  <Eye size={14} />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>
                                {t(
                                  "security.skillScanner.scanAlerts.viewFindings",
                                )}
                              </TooltipContent>
                            </Tooltip>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-7 w-7 p-0"
                                  onClick={() =>
                                    void handleAllowSkill(record, index)
                                  }
                                >
                                  <ShieldCheck size={14} />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>
                                {t(
                                  "security.skillScanner.scanAlerts.allowSkill",
                                )}
                              </TooltipContent>
                            </Tooltip>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                                  onClick={() => void removeBlockedEntry(index)}
                                >
                                  <Trash2 size={14} />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>
                                {t("security.skillScanner.scanAlerts.remove")}
                              </TooltipContent>
                            </Tooltip>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </div>
          </div>
        </TabsContent>

        <TabsContent value="whitelist">
          <div className={styles.tabPanelContent}>
            <div className={`${styles.tableCard} border rounded-lg`}>
              {whitelist.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 gap-2 text-muted-foreground">
                  <Package size={48} strokeWidth={1} />
                  <span className={styles.emptyText}>
                    {t("security.skillScanner.whitelist.empty")}
                  </span>
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead style={{ width: 200 }}>
                        {t("security.skillScanner.whitelist.skillName")}
                      </TableHead>
                      <TableHead style={{ width: 200 }}>
                        {t("security.skillScanner.whitelist.contentHash")}
                      </TableHead>
                      <TableHead style={{ width: 180 }}>
                        {t("security.skillScanner.whitelist.addedAt")}
                      </TableHead>
                      <TableHead style={{ width: 100 }}>
                        {t("security.skillScanner.whitelist.actions")}
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {whitelist.map((entry: SkillScannerWhitelistEntry) => (
                      <TableRow key={entry.skill_name}>
                        <TableCell>{entry.skill_name}</TableCell>
                        <TableCell>
                          {entry.content_hash ? (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <code className={styles.codeHash}>
                                  {entry.content_hash.substring(0, 16)}...
                                </code>
                              </TooltipTrigger>
                              <TooltipContent>
                                {entry.content_hash}
                              </TooltipContent>
                            </Tooltip>
                          ) : (
                            <span className="text-muted-foreground">any</span>
                          )}
                        </TableCell>
                        <TableCell>
                          {(() => {
                            try {
                              return new Date(entry.added_at).toLocaleString();
                            } catch {
                              return entry.added_at;
                            }
                          })()}
                        </TableCell>
                        <TableCell>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                                onClick={() =>
                                  setRemoveWhitelistDialog(entry.skill_name)
                                }
                              >
                                <Trash2 size={14} />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>
                              {t("security.skillScanner.whitelist.remove")}
                            </TooltipContent>
                          </Tooltip>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </div>
          </div>
        </TabsContent>
      </Tabs>

      <FindingsModal
        findings={findingsModal.findings}
        skillName={findingsModal.skillName}
        open={findingsModal.open}
        onClose={() =>
          setFindingsModal({ open: false, findings: [], skillName: "" })
        }
      />

      <AlertDialog
        open={!!removeWhitelistDialog}
        onOpenChange={(v) => {
          if (!v) setRemoveWhitelistDialog(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("security.skillScanner.whitelist.removeConfirm")}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t("security.skillScanner.whitelist.removeWillDisable")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() =>
                removeWhitelistDialog &&
                void handleRemoveWhitelistConfirm(removeWhitelistDialog)
              }
            >
              {t("common.delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={clearHistoryDialog}
        onOpenChange={(v) => {
          if (!v) setClearHistoryDialog(false);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("security.skillScanner.scanAlerts.clearConfirm")}
            </AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => void handleClearHistoryConfirm()}
            >
              {t("common.confirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
