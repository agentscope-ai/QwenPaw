import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatCompact } from "../../../../utils/formatNumber";
import styles from "../index.module.less";

interface ByModelData {
  key: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  call_count: number;
}

interface ByDateData {
  key: string;
  date: string;
  prompt_tokens: number;
  completion_tokens: number;
  call_count: number;
}

interface DataTablesProps {
  byModelData: ByModelData[];
  byDateData: ByDateData[];
}

type SortDir = "asc" | "desc" | null;

function SortIcon({ dir }: { dir: SortDir }) {
  if (dir === "asc") return <ArrowUp size={12} className="inline ml-1" />;
  if (dir === "desc") return <ArrowDown size={12} className="inline ml-1" />;
  return <ArrowUpDown size={12} className="inline ml-1 opacity-40" />;
}

function useSortState<T>(initial: T[], getKey: (r: T) => string) {
  const [sortCol, setSortCol] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>(null);

  const handleSort = (col: string) => {
    if (sortCol !== col) {
      setSortCol(col);
      setSortDir("desc");
    } else if (sortDir === "desc") {
      setSortDir("asc");
    } else {
      setSortCol(null);
      setSortDir(null);
    }
  };

  const sorted = [...initial].sort((a, b) => {
    if (!sortCol || !sortDir) return 0;
    const av = (a as Record<string, unknown>)[sortCol];
    const bv = (b as Record<string, unknown>)[sortCol];
    const n =
      typeof av === "number" && typeof bv === "number"
        ? av - bv
        : String(av).localeCompare(String(bv));
    return sortDir === "asc" ? n : -n;
  });

  return { sorted, sortCol, sortDir, handleSort, getKey };
}

export function DataTables({ byModelData, byDateData }: DataTablesProps) {
  const { t } = useTranslation();

  const modelSort = useSortState(byModelData, (r) => r.key);
  const dateSort = useSortState(byDateData, (r) => r.key);

  const SH = ({
    col,
    state,
    children,
  }: {
    col: string;
    state: ReturnType<typeof useSortState<ByModelData | ByDateData>>;
    children: React.ReactNode;
  }) => (
    <TableHead
      className="cursor-pointer select-none"
      onClick={() => state.handleSort(col)}
    >
      {children}
      <SortIcon dir={state.sortCol === col ? state.sortDir : null} />
    </TableHead>
  );

  return (
    <>
      {byModelData.length > 0 && (
        <div className={`${styles.tableCard} border rounded-lg p-4`}>
          <div className="text-sm font-semibold mb-3">
            {t("tokenUsage.byModel")}
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <SH
                  col="model"
                  state={
                    modelSort as ReturnType<
                      typeof useSortState<ByModelData | ByDateData>
                    >
                  }
                >
                  {t("tokenUsage.model")}
                </SH>
                <SH
                  col="prompt_tokens"
                  state={
                    modelSort as ReturnType<
                      typeof useSortState<ByModelData | ByDateData>
                    >
                  }
                >
                  {t("tokenUsage.promptTokens")}
                </SH>
                <SH
                  col="completion_tokens"
                  state={
                    modelSort as ReturnType<
                      typeof useSortState<ByModelData | ByDateData>
                    >
                  }
                >
                  {t("tokenUsage.completionTokens")}
                </SH>
                <TableHead>{t("tokenUsage.totalTokens")}</TableHead>
                <SH
                  col="call_count"
                  state={
                    modelSort as ReturnType<
                      typeof useSortState<ByModelData | ByDateData>
                    >
                  }
                >
                  {t("tokenUsage.totalCalls")}
                </SH>
              </TableRow>
            </TableHeader>
            <TableBody>
              {modelSort.sorted.map((row) => (
                <TableRow key={row.key}>
                  <TableCell className="text-sm">{row.model}</TableCell>
                  <TableCell className="text-sm">
                    {formatCompact(row.prompt_tokens)}
                  </TableCell>
                  <TableCell className="text-sm">
                    {formatCompact(row.completion_tokens)}
                  </TableCell>
                  <TableCell className="text-sm">
                    {formatCompact(row.prompt_tokens + row.completion_tokens)}
                  </TableCell>
                  <TableCell className="text-sm">
                    {formatCompact(row.call_count)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {byDateData.length > 0 && (
        <div className={`${styles.tableCard} border rounded-lg p-4`}>
          <div className="text-sm font-semibold mb-3">
            {t("tokenUsage.byDate")}
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <SH
                  col="date"
                  state={
                    dateSort as ReturnType<
                      typeof useSortState<ByModelData | ByDateData>
                    >
                  }
                >
                  {t("tokenUsage.date")}
                </SH>
                <SH
                  col="prompt_tokens"
                  state={
                    dateSort as ReturnType<
                      typeof useSortState<ByModelData | ByDateData>
                    >
                  }
                >
                  {t("tokenUsage.promptTokens")}
                </SH>
                <SH
                  col="completion_tokens"
                  state={
                    dateSort as ReturnType<
                      typeof useSortState<ByModelData | ByDateData>
                    >
                  }
                >
                  {t("tokenUsage.completionTokens")}
                </SH>
                <TableHead>{t("tokenUsage.totalTokens")}</TableHead>
                <SH
                  col="call_count"
                  state={
                    dateSort as ReturnType<
                      typeof useSortState<ByModelData | ByDateData>
                    >
                  }
                >
                  {t("tokenUsage.totalCalls")}
                </SH>
              </TableRow>
            </TableHeader>
            <TableBody>
              {dateSort.sorted.map((row) => (
                <TableRow key={row.key}>
                  <TableCell className="text-sm">{row.date}</TableCell>
                  <TableCell className="text-sm">
                    {formatCompact(row.prompt_tokens)}
                  </TableCell>
                  <TableCell className="text-sm">
                    {formatCompact(row.completion_tokens)}
                  </TableCell>
                  <TableCell className="text-sm">
                    {formatCompact(row.prompt_tokens + row.completion_tokens)}
                  </TableCell>
                  <TableCell className="text-sm">
                    {formatCompact(row.call_count)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </>
  );
}
