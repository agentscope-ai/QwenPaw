/**
 * Expandable agent selection table used inside RestoreBackupModal.
 */
import { useState, useMemo } from "react";
import { Search, ChevronRight, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Checkbox } from "@/components/ui/checkbox";
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
import styles from "./RestoreAgentTable.module.less";

export interface AgentRow {
  key: string;
  aid: string;
  name: string;
  isExisting: boolean;
  currentWorkspaceDir: string;
}

interface Props {
  allAgentRows: AgentRow[];
  selectedAgents: string[];
  onSelectionChange: (ids: string[]) => void;
  detailLoading: boolean;
  defaultWorkspaceDir: string;
  includeAgents: boolean;
  onIncludeAgentsChange: (checked: boolean) => void;
  summaryText: string | null;
}

export default function RestoreAgentTable({
  allAgentRows,
  selectedAgents,
  onSelectionChange,
  detailLoading,
  defaultWorkspaceDir,
  includeAgents,
  onIncludeAgentsChange,
  summaryText,
}: Props) {
  const { t } = useTranslation();
  const [agentSearch, setAgentSearch] = useState("");
  const [agentsExpanded, setAgentsExpanded] = useState(true);
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 10;

  const filteredAgentRows = useMemo(() => {
    const q = agentSearch.trim().toLowerCase();
    if (!q) return allAgentRows;
    return allAgentRows.filter(
      (r) =>
        r.name.toLowerCase().includes(q) || r.aid.toLowerCase().includes(q),
    );
  }, [allAgentRows, agentSearch]);

  const allAgentIds = useMemo(
    () => allAgentRows.map((r) => r.aid),
    [allAgentRows],
  );

  const allSelected =
    allAgentIds.length > 0 &&
    allAgentIds.every((id) => selectedAgents.includes(id));
  const someSelected = selectedAgents.length > 0 && !allSelected;

  const handleSelectAll = (checked: boolean | string) => {
    onSelectionChange(checked ? [...allAgentIds] : []);
  };

  const handleRowToggle = (aid: string, checked: boolean) => {
    const filteredIds = new Set(filteredAgentRows.map((r) => r.aid));
    const kept = selectedAgents.filter((id) => !filteredIds.has(id));
    if (checked) {
      onSelectionChange([
        ...kept,
        ...filteredAgentRows
          .filter((r) => selectedAgents.includes(r.aid) || r.aid === aid)
          .map((r) => r.aid),
      ]);
    } else {
      onSelectionChange(kept.filter((id) => id !== aid));
    }
  };

  const getNewAgentDestPath = (aid: string): string => {
    const base = defaultWorkspaceDir.trim();
    if (base) return `${base.replace(/[/\\]+$/, "")}/${aid}`;
    return t("backup.defaultWorkspaceDirDefault", { aid });
  };

  const totalPages = Math.ceil(filteredAgentRows.length / PAGE_SIZE);
  const pageRows = filteredAgentRows.slice(
    (page - 1) * PAGE_SIZE,
    page * PAGE_SIZE,
  );

  return (
    <div>
      <div className={styles.agentsRowHeader}>
        <div className="flex items-center gap-2">
          <Checkbox
            id="include-agents"
            checked={includeAgents}
            onCheckedChange={(checked) => {
              onIncludeAgentsChange(!!checked);
              setAgentsExpanded(!!checked);
            }}
          />
          <label
            htmlFor="include-agents"
            className="cursor-pointer text-sm font-medium"
          >
            {t("backup.scopeAgents")}
            {includeAgents && detailLoading && (
              <Loader2 size={12} className="ml-2 inline animate-spin" />
            )}
            {includeAgents && !detailLoading && summaryText && (
              <span className="ml-1 text-muted-foreground text-xs">
                — {summaryText}
              </span>
            )}
          </label>
        </div>
        {includeAgents && (
          <button
            type="button"
            onClick={() => setAgentsExpanded(!agentsExpanded)}
            className={styles.expandToggle}
          >
            <ChevronRight
              size={14}
              className={`transition-transform ${
                agentsExpanded ? "rotate-90" : ""
              }`}
            />
          </button>
        )}
      </div>

      {includeAgents && agentsExpanded && (
        <div className={styles.agentsContent}>
          {detailLoading ? (
            <div className={styles.agentsLoading}>
              <Loader2 className="animate-spin" />
              <div className={styles.agentsLoadingText}>
                {t("backup.loadingAgents")}
              </div>
            </div>
          ) : (
            <>
              <div className={styles.agentSearchToolbar}>
                <div className="relative flex-1">
                  <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-muted-foreground" />
                  <Input
                    className={`${styles.agentSearchInput} pl-7 h-7 text-sm`}
                    placeholder={t("backup.agentSearchPlaceholder")}
                    value={agentSearch}
                    onChange={(e) => setAgentSearch(e.target.value)}
                  />
                </div>
                <span
                  className={`${styles.selectAllCount} text-muted-foreground text-xs`}
                >
                  ({selectedAgents.length}/{allAgentIds.length})
                </span>
              </div>

              <Table className={styles.agentTable}>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-8">
                      <Checkbox
                        checked={allSelected}
                        onCheckedChange={handleSelectAll}
                        data-state={someSelected ? "indeterminate" : undefined}
                      />
                    </TableHead>
                    <TableHead>{t("backup.agentColumnName")}</TableHead>
                    <TableHead>{t("backup.agentColumnWorkspace")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pageRows.length === 0 ? (
                    <TableRow>
                      <TableCell
                        colSpan={3}
                        className="text-center text-muted-foreground py-4"
                      >
                        {t("backup.noAgentsInBackup")}
                      </TableCell>
                    </TableRow>
                  ) : (
                    pageRows.map((row) => (
                      <TableRow key={row.aid}>
                        <TableCell className="w-8">
                          <Checkbox
                            checked={selectedAgents.includes(row.aid)}
                            onCheckedChange={(checked) =>
                              handleRowToggle(row.aid, !!checked)
                            }
                          />
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-wrap items-center gap-1">
                            <span
                              className={`${styles.agentName} font-medium text-sm`}
                            >
                              {row.name}
                            </span>
                            {row.name !== row.aid && (
                              <span
                                className={`${styles.agentId} text-xs text-muted-foreground`}
                              >
                                ({row.aid})
                              </span>
                            )}
                            <Badge
                              variant="secondary"
                              className={
                                row.isExisting
                                  ? "bg-blue-100 text-blue-700"
                                  : "bg-green-100 text-green-700"
                              }
                            >
                              {row.isExisting
                                ? t("backup.agentActionReplace")
                                : t("backup.agentActionAdd")}
                            </Badge>
                          </div>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground max-w-[200px] truncate">
                          {row.isExisting
                            ? row.currentWorkspaceDir || row.aid
                            : getNewAgentDestPath(row.aid)}
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>

              {totalPages > 1 && (
                <div className="flex items-center justify-between px-2 py-1 text-xs text-muted-foreground">
                  <span>
                    {agentSearch
                      ? t("backup.agentSearchTotal", {
                          count: filteredAgentRows.length,
                          total: allAgentIds.length,
                        })
                      : t("backup.agentTotal", {
                          count: filteredAgentRows.length,
                        })}
                  </span>
                  <div className="flex gap-1">
                    <button
                      type="button"
                      disabled={page === 1}
                      onClick={() => setPage((p) => p - 1)}
                      className="px-1 disabled:opacity-40"
                    >
                      &lt;
                    </button>
                    <span>
                      {page}/{totalPages}
                    </span>
                    <button
                      type="button"
                      disabled={page === totalPages}
                      onClick={() => setPage((p) => p + 1)}
                      className="px-1 disabled:opacity-40"
                    >
                      &gt;
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
