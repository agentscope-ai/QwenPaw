import { useTranslation } from "react-i18next";
import dayjs from "dayjs";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { useDebugLogs } from "./useDebugLogs";
import type { BackendLevelFilter } from "./useDebugLogs";
import { LogViewer } from "./components";
import styles from "./index.module.less";

const LEVEL_OPTIONS: {
  value: BackendLevelFilter;
  label: string;
  color: string;
}[] = [
  { value: "all", label: "All", color: "" },
  { value: "error", label: "ERROR", color: "text-red-600" },
  { value: "warning", label: "WARNING", color: "text-yellow-600" },
  { value: "info", label: "INFO", color: "text-blue-600" },
  { value: "debug", label: "DEBUG", color: "text-indigo-600" },
];

export default function DebugPage() {
  const { t } = useTranslation();
  const {
    backendLogs,
    initialLoading,
    backendError,
    autoRefresh,
    setAutoRefresh,
    backendNewestFirst,
    setBackendNewestFirst,
    backendLevel,
    setBackendLevel,
    backendQuery,
    setBackendQuery,
    filteredBackendLines,
    loadBackendLogs,
    handleCopyBackend,
  } = useDebugLogs();

  return (
    <div className={styles.debugPage}>
      <PageHeader
        parent={t("nav.settings")}
        current={t("debug.title", "Debug")}
      />

      <div className={styles.content}>
        <div className="flex items-start gap-2 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800 dark-mode:border-blue-800 dark-mode:bg-blue-950 dark-mode:text-blue-200 mb-4">
          <span>ℹ</span>
          {t(
            "debug.desc",
            "View backend daemon log file to help diagnose issues. Logs refresh automatically while this page is open.",
          )}
        </div>
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">
                {t("debug.backend.title", "Backend logs")}
              </CardTitle>
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-2">
                  <Label
                    htmlFor="newest-first"
                    className="text-xs text-muted-foreground cursor-pointer"
                  >
                    {t("debug.backend.newestFirst", "Newest first")}
                  </Label>
                  <Switch
                    id="newest-first"
                    checked={backendNewestFirst}
                    onCheckedChange={setBackendNewestFirst}
                  />
                </div>
                <div className="flex items-center gap-2">
                  <Label
                    htmlFor="auto-refresh"
                    className="text-xs text-muted-foreground cursor-pointer"
                  >
                    {t("debug.backend.autoRefresh", "Auto refresh")}
                  </Label>
                  <Switch
                    id="auto-refresh"
                    checked={autoRefresh}
                    onCheckedChange={setAutoRefresh}
                  />
                </div>
              </div>
            </div>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div className={styles.toolbar}>
              <div
                className={`${styles.toolbarLeft} flex flex-wrap items-center gap-2`}
              >
                <Select
                  value={backendLevel}
                  onValueChange={(v) =>
                    setBackendLevel(v as BackendLevelFilter)
                  }
                >
                  <SelectTrigger className="w-[140px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {LEVEL_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        <span className={opt.color}>{opt.label}</span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Input
                  className="w-[280px]"
                  value={backendQuery}
                  onChange={(e) => setBackendQuery(e.target.value)}
                  placeholder={t(
                    "debug.backend.searchPlaceholder",
                    "Search backend logs...",
                  )}
                />
                {backendLogs?.updated_at && (
                  <span className="text-xs text-muted-foreground">
                    {t("debug.backend.updatedAt", "Updated at")}:{" "}
                    {dayjs(backendLogs.updated_at * 1000).format(
                      "YYYY-MM-DD HH:mm:ss",
                    )}
                  </span>
                )}
              </div>
              <div className={`${styles.toolbarRight} flex gap-2`}>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void loadBackendLogs({ successToast: true })}
                >
                  {t("debug.actions.refreshBackend", "Refresh backend logs")}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void handleCopyBackend()}
                >
                  {t("debug.actions.copyBackend", "Copy backend logs")}
                </Button>
              </div>
            </div>

            {backendLogs?.path && (
              <div className={styles.logPath}>
                <span
                  className={`${styles.logPathLabel} text-xs text-muted-foreground`}
                >
                  {t("debug.backend.path", "Log file")}
                </span>
                <code className={`${styles.logPathValue} font-mono text-xs`}>
                  {backendLogs.path}
                </code>
              </div>
            )}

            {backendError ? (
              <div className="flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark-mode:border-red-800 dark-mode:bg-red-950 dark-mode:text-red-200">
                <span>✕</span>
                {backendError}
              </div>
            ) : !backendLogs?.exists ? (
              <div className="flex items-center gap-2 rounded-md border border-yellow-200 bg-yellow-50 px-3 py-2 text-sm text-yellow-800 dark-mode:border-yellow-800 dark-mode:bg-yellow-950 dark-mode:text-yellow-200">
                <span>⚠</span>
                {t(
                  "debug.backend.notFound",
                  "Backend log file was not found yet.",
                )}
              </div>
            ) : null}

            <LogViewer
              lines={filteredBackendLines}
              query={backendQuery}
              loading={initialLoading}
            />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
