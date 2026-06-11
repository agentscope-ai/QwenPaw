import { useState, useEffect, useCallback } from "react";
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
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import { Shield, Plus, Trash2, AlertTriangle } from "lucide-react";
import { useTranslation } from "react-i18next";
import api from "../../../../api";
import styles from "../index.module.less";

interface AllowNoAuthHostsTabProps {
  onSave?: (handlers: {
    save: () => Promise<void>;
    reset: () => void;
    saving: boolean;
  }) => void;
}

export function AllowNoAuthHostsTab({ onSave }: AllowNoAuthHostsTabProps = {}) {
  const { t } = useTranslation();
  const [hosts, setHosts] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [newHost, setNewHost] = useState("");
  const [removeConfirm, setRemoveConfirm] = useState<string | null>(null);
  const { message } = useAppMessage();

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const data = await api.getAllowNoAuthHosts();
      setHosts(data?.hosts ?? ["127.0.0.1", "::1"]);
    } catch {
      message.error(t("security.allowNoAuthHosts.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t, message]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const isValidIP = (ip: string): boolean => {
    const ipv4Regex =
      /^(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$/;
    const ipv6Regex =
      /^(([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,7}:|([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,5}(:[0-9a-fA-F]{1,4}){1,2}|([0-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3}|([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}|([0-9a-fA-F]{1,4}:){1,2}(:[0-9a-fA-F]{1,4}){1,5}|[0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6})|:((:[0-9a-fA-F]{1,4}){1,7}|:)|fe80:(:[0-9a-fA-F]{0,4}){0,4}%[0-9a-zA-Z]+|::(ffff(:0{1,4})?:)?((25[0-5]|(2[0-4]|1?[0-9])?[0-9])\.){3}(25[0-5]|(2[0-4]|1?[0-9])?[0-9])|([0-9a-fA-F]{1,4}:){1,4}:((25[0-5]|(2[0-4]|1?[0-9])?[0-9])\.){3}(25[0-5]|(2[0-4]|1?[0-9])?[0-9]))$/;
    return ipv4Regex.test(ip) || ipv6Regex.test(ip);
  };

  const handleAdd = useCallback(() => {
    const trimmed = newHost.trim();
    if (!trimmed) return;
    if (!isValidIP(trimmed)) {
      message.error(t("security.allowNoAuthHosts.invalidIP"));
      return;
    }
    if (hosts.includes(trimmed)) {
      message.warning(t("security.allowNoAuthHosts.duplicate"));
      return;
    }
    setHosts((prev) => [...prev, trimmed]);
    setNewHost("");
  }, [newHost, hosts, t, message]);

  const handleRemove = useCallback((host: string) => {
    setHosts((prev) => prev.filter((h) => h !== host));
    setRemoveConfirm(null);
  }, []);

  const handleSave = useCallback(async () => {
    try {
      setSaving(true);
      await api.updateAllowNoAuthHosts({ hosts });
      message.success(t("security.allowNoAuthHosts.saveSuccess"));
    } catch {
      message.error(t("security.allowNoAuthHosts.saveFailed"));
    } finally {
      setSaving(false);
    }
  }, [hosts, t, message]);

  const handleReset = useCallback(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    onSave?.({ save: handleSave, reset: handleReset, saving });
  }, [handleSave, handleReset, saving, onSave]);

  const isDefaultHost = (host: string) =>
    host === "127.0.0.1" || host === "::1";

  return (
    <div className={styles.tabContent}>
      <div className="flex items-start gap-2 rounded-md border border-yellow-200 bg-yellow-50 px-3 py-2 text-sm text-yellow-800 dark-mode:border-yellow-800 dark-mode:bg-yellow-950 dark-mode:text-yellow-200 mb-4">
        <AlertTriangle size={16} className="mt-0.5 shrink-0" />
        <div>
          <p className="font-medium">
            {t("security.allowNoAuthHosts.warningTitle")}
          </p>
          <p className="text-xs mt-0.5">
            {t("security.allowNoAuthHosts.warningDescription")}
          </p>
        </div>
      </div>

      <div className={`${styles.formCard} border rounded-lg p-4`}>
        <div className="flex gap-2">
          <Input
            value={newHost}
            onChange={(e) => setNewHost(e.target.value)}
            placeholder={t("security.allowNoAuthHosts.inputPlaceholder")}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleAdd();
            }}
            className="flex-1"
          />
          <Button onClick={handleAdd} disabled={!newHost.trim()}>
            <Plus size={16} className="mr-2" />
            {t("security.allowNoAuthHosts.add")}
          </Button>
        </div>
      </div>

      <div className={`${styles.tableCard} border rounded-lg mt-2`}>
        <div className={loading ? "opacity-60 pointer-events-none" : ""}>
          {hosts.length === 0 && !loading ? (
            <div className="p-6 text-center text-sm text-muted-foreground">
              {t("security.allowNoAuthHosts.empty")}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>
                    {t("security.allowNoAuthHosts.ipAddress")}
                  </TableHead>
                  <TableHead style={{ width: 80 }}>
                    {t("security.allowNoAuthHosts.actions")}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {hosts.map((host) => (
                  <TableRow key={host}>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Shield size={16} className="text-green-500" />
                        <code className="text-sm">{host}</code>
                        {isDefaultHost(host) && (
                          <Badge
                            variant="outline"
                            className="text-xs border-blue-300 text-blue-600"
                          >
                            {t("security.allowNoAuthHosts.default")}
                          </Badge>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                        onClick={() => setRemoveConfirm(host)}
                      >
                        <Trash2 size={14} />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
      </div>

      <AlertDialog
        open={!!removeConfirm}
        onOpenChange={(v) => {
          if (!v) setRemoveConfirm(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("security.allowNoAuthHosts.removeConfirm")}
            </AlertDialogTitle>
            <AlertDialogDescription>{removeConfirm}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => removeConfirm && handleRemove(removeConfirm)}
            >
              {t("common.delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
