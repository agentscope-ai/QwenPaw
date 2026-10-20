import { useTranslation } from "react-i18next";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Tooltip as TooltipPrimitive } from "radix-ui";
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  ChevronUp,
  Download,
  ExternalLink,
  Search,
  CircleHelp,
} from "lucide-react";
import Chart from "./Chart";
import EvaluationSelect from "./Select";
import { bestRows, frontier } from "./metrics";
import {
  harnessLogo,
  logo,
  money as formatMoney,
  safeWorkflow,
  selectRows,
  type History,
  type Row,
} from "./types";
import "./style.css";

function download(data: unknown) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
  );
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "qwenpaw-evaluation.json";
  anchor.click();
  URL.revokeObjectURL(url);
}
export default function Evaluation() {
  const { t, i18n } = useTranslation("evaluation");
  const money = (value: number | null) =>
    formatMoney(value, i18n.language, t("notRecorded"));
  const number = (value: number) =>
    new Intl.NumberFormat(i18n.language, {
      maximumFractionDigits: 3,
      minimumFractionDigits: 3,
    }).format(value);
  const date = (value: string) =>
    new Intl.DateTimeFormat(i18n.language, {
      dateStyle: "medium",
      timeZone: "UTC",
    }).format(new Date(value));
  const { id } = useParams();
  const navigate = useNavigate();
  const tableRef = useRef<HTMLDivElement>(null);
  const listPosition = useRef<{ top: number; left: number } | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [data, setData] = useState<History>({
    schema_version: 3,
    runs: [],
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [metric, setMetric] = useState("index");
  const [search, setSearch] = useState("");
  const [showHistory, setShowHistory] = useState(true);
  const [showTable, setShowTable] = useState(true);
  const [showBreakdown, setShowBreakdown] = useState(false);
  const [onlyFrontier, setOnlyFrontier] = useState(false);
  const [methodologyOpen, setMethodologyOpen] = useState(false);
  const kind = "official";
  const [boardId, setBoardId] = useState("");
  const [protocol, setProtocol] = useState("");
  const [sort, setSort] = useState<{
    key: "score" | "cost" | "runtime" | "date";
    asc: boolean;
  }>({ key: "score", asc: false });
  useEffect(() => {
    if (id || !listPosition.current) return;
    const position = listPosition.current;
    const frame = requestAnimationFrame(() => {
      window.scrollTo(0, position.top);
      tableRef.current?.scrollTo({ left: position.left });
    });
    return () => cancelAnimationFrame(frame);
  }, [id]);
  useEffect(() => {
    setLoading(true);
    setError("");
    const controller = new AbortController();
    let timedOut = false;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, 30000);
    fetch(`${import.meta.env.BASE_URL}evaluation/data/index.json`, {
      signal: controller.signal,
    })
      .then((response) => {
        if (!response.ok) throw new Error("unavailable");
        return response.json();
      })
      .then((history: History) => {
        if (cancelled) return;
        if (
          history.schema_version !== 3 ||
          !Array.isArray(history.runs) ||
          history.runs.some(
            (run) =>
              !run.board?.id ||
              !Array.isArray(run.records) ||
              !["testing", "official"].includes(run.kind),
          )
        )
          throw new Error("invalidData");
        setData(history);
      })
      .catch((e: Error) => {
        if (!cancelled && (timedOut || e.name !== "AbortError"))
          setError(e.message === "invalidData" ? "invalidData" : "unavailable");
      })
      .finally(() => {
        window.clearTimeout(timer);
        if (!cancelled) setLoading(false);
      });
    return () => {
      window.clearTimeout(timer);
      cancelled = true;
      controller.abort();
    };
  }, [loadAttempt]);
  const history = data;
  const scopedRuns = history.runs.filter((run) => run.kind === kind);
  const boards = [
    ...new Map(scopedRuns.map((run) => [run.board.id, run.board])).values(),
  ];
  const activeBoard = boards.find((board) => board.id === boardId) ?? boards[0];
  const boardRuns = scopedRuns.filter(
    (run) => run.board.id === activeBoard?.id,
  );
  const compareHarnesses = activeBoard?.group_by === "model_harness";
  const versions = [...new Set(boardRuns.map((run) => run.index_version))];
  const versionName = (version: string) =>
    [
      ...new Set(
        boardRuns
          .filter((run) => run.index_version === version)
          .flatMap((run) =>
            run.records.flatMap((record) =>
              record.benchmarks.map((part) => part.name),
            ),
          ),
      ),
    ].join(" + ") + ` · ${version}`;
  const activeProtocol = versions.includes(protocol) ? protocol : versions[0];
  const activeRuns = boardRuns.filter(
    (run) => run.index_version === activeProtocol,
  );
  const parts = activeRuns.flatMap((run) =>
    run.records.flatMap((record) => record.benchmarks),
  );
  const benchmarks = Object.fromEntries(
    parts.map((part) => [part.benchmark, part.name]),
  );
  const domainIds = [...new Set(parts.flatMap((part) => part.domains))];
  const rows = useMemo(
    () =>
      selectRows(
        history.runs.filter(
          (run) =>
            run.kind === kind &&
            run.board.id === activeBoard?.id &&
            run.index_version === activeProtocol,
        ),
        metric,
      ),
    [history, kind, activeBoard?.id, activeProtocol, metric],
  );
  const best = useMemo(
    () => bestRows(rows, compareHarnesses),
    [rows, compareHarnesses],
  );
  const pareto = useMemo(
    () =>
      new Set(
        frontier(rows.filter((row) => best.has(row.id))).map((row) => row.id),
      ),
    [rows, best],
  );
  const tableRows = useMemo(
    () =>
      rows.filter(
        (row) =>
          (!onlyFrontier || pareto.has(row.id)) &&
          `${row.model} ${row.sdk_version} ${row.harness}`
            .toLowerCase()
            .includes(search.toLowerCase()),
      ),
    [rows, onlyFrontier, pareto, search],
  );
  const ordered = [...tableRows].sort((a, b) => {
    const av = sort.key === "date" ? a.run.date : a[sort.key];
    const bv = sort.key === "date" ? b.run.date : b[sort.key];
    if (av === null) return bv === null ? 0 : 1;
    if (bv === null) return -1;
    return (av < bv ? -1 : av > bv ? 1 : 0) * (sort.asc ? 1 : -1);
  });
  const navigateRow = useCallback(
    (row: Row) => {
      listPosition.current = {
        top: window.scrollY,
        left: tableRef.current?.scrollLeft ?? 0,
      };
      navigate(`/evaluation/runs/${row.run.id}`);
    },
    [navigate],
  );
  const detail = id ? history.runs.find((run) => run.id === id) : undefined;
  const title =
    metric === "index"
      ? "Index"
      : metric.startsWith("domain:")
      ? t(`domains.${metric.slice(7)}`, {
          defaultValue:
            activeRuns[0]?.index_definition.directions[metric.slice(7)]?.name ??
            metric.slice(7),
        })
      : benchmarks[metric.slice(10)];
  const noteBenchmarks = (
    metric.startsWith("benchmark:")
      ? [metric.slice(10)]
      : metric.startsWith("domain:")
      ? Object.keys(
          activeRuns[0]?.index_definition.directions[metric.slice(7)]
            ?.benchmarks ?? {},
        )
      : []
  ).filter((benchmark) =>
    i18n.exists(`benchmarkNotes.${benchmark}`, {
      ns: "evaluation",
    }),
  );
  const sortButton = (key: typeof sort.key, label: string) => (
    <button
      onClick={() =>
        setSort({ key, asc: sort.key === key ? !sort.asc : key !== "score" })
      }
    >
      {label}
      {sort.key === key &&
        (sort.asc ? <ArrowUp size={12} /> : <ArrowDown size={12} />)}
    </button>
  );
  return (
    <main className="evaluation-page">
      <header className="evaluation-header">
        <div className="evaluation-brand">
          <img
            src={`${import.meta.env.BASE_URL}evaluation/logos/qwenpaw.png`}
            alt=""
          />
          <div>
            <h1>{t("headline")}</h1>
          </div>
        </div>
      </header>
      {id ? (
        <section className="evaluation-detail">
          <Link to="/evaluation">{t("back")}</Link>
          <h1>{t("runTitle")}</h1>
          {loading ? (
            <p>{t("loading")}</p>
          ) : error ? (
            <p role="alert">{t(error)}</p>
          ) : !detail ? (
            <p>{t("notFound")}</p>
          ) : (
            <>
              <dl>
                <dt>{t("date")}</dt>
                <dd>{date(detail.date)}</dd>
                <dt>{t("benchmarkSet")}</dt>
                <dd>{versionName(detail.index_version)}</dd>
                <dt>{t("sourceSha")}</dt>
                <dd>{detail.evaluation_sha ?? t("unknown")}</dd>
                <dt>{t("artifactSha")}</dt>
                <dd>{detail.artifact_sha256}</dd>
                <dt>{t("exchangeRate")}</dt>
                <dd>1 USD = {detail.exchange_rate.cny_per_usd} CNY</dd>
                <dt>{t("sourceResults")}</dt>
                <dd>
                  {detail.source_results.map((source) => (
                    <div key={source.id}>
                      {source.benchmark} · {date(source.date)} · {source.id}
                      <div>
                        {t("runBudget", {
                          contextTokens:
                            source.parameters.max_context_length ??
                            t("unknown"),
                          output:
                            source.parameters.max_response_length ??
                            t("unknown"),
                        })}
                      </div>
                    </div>
                  ))}
                </dd>
                <dt>ID</dt>
                <dd>{detail.id}</dd>
              </dl>
              {safeWorkflow(detail.workflow_url) && (
                <a href={detail.workflow_url} target="_blank" rel="noreferrer">
                  {t("workflow")}
                  <ExternalLink size={14} />
                </a>
              )}
              {detail.records
                .filter((r) => r.trajectory_url)
                .map((r) => (
                  <a
                    key={`${r.provider}/${r.model}/${r.harness}`}
                    href={r.trajectory_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {t("trajectory")} · {r.model}
                    <ExternalLink size={14} />
                  </a>
                ))}
              <button
                className="evaluation-button"
                onClick={() => download(detail)}
              >
                <Download size={15} />
                {t("downloadRecord")}
              </button>
              <pre>{JSON.stringify(detail.records, null, 2)}</pre>
            </>
          )}
        </section>
      ) : (
        <>
          <section className="evaluation-chart-surface">
            <div className="evaluation-controls">
              <div className="evaluation-board-controls">
                <EvaluationSelect
                  className="evaluation-board-select"
                  label={t("board")}
                  value={metric}
                  onValueChange={setMetric}
                  groups={[
                    { options: [{ value: "index", label: t("main") }] },
                    {
                      label: t("domainBoards"),
                      options: domainIds.map((key) => ({
                        value: `domain:${key}`,
                        label: t(`domains.${key}`, {
                          defaultValue:
                            activeRuns[0]?.index_definition.directions[key]
                              ?.name ?? key,
                        }),
                      })),
                    },
                    {
                      label: t("benchmarkBoards"),
                      options: Object.entries(benchmarks).map(
                        ([key, name]) => ({
                          value: `benchmark:${key}`,
                          label: name,
                        }),
                      ),
                    },
                  ]}
                />
                {boards.length > 1 && (
                  <EvaluationSelect
                    label={t("collection")}
                    value={activeBoard?.id ?? ""}
                    onValueChange={(value) => {
                      setBoardId(value);
                      setProtocol("");
                      setMetric("index");
                    }}
                    groups={[
                      {
                        options: boards.map((board) => ({
                          value: board.id,
                          label: board.name,
                        })),
                      },
                    ]}
                  />
                )}
                {versions.length > 1 && (
                  <EvaluationSelect
                    label={t("benchmarkSet")}
                    value={activeProtocol ?? ""}
                    onValueChange={(value) => {
                      setProtocol(value);
                      setMetric("index");
                    }}
                    groups={[
                      {
                        options: versions.map((version) => ({
                          value: version,
                          label: versionName(version),
                        })),
                      },
                    ]}
                  />
                )}
              </div>
              <div className="evaluation-display-controls">
                <label>
                  <input
                    type="checkbox"
                    checked={showHistory}
                    onChange={(e) => setShowHistory(e.target.checked)}
                  />
                  {t("historyPoints")}
                </label>
              </div>
            </div>
            {noteBenchmarks.length > 0 && (
              <aside
                className="evaluation-benchmark-notes"
                aria-label={t("benchmarkSetting")}
              >
                <h2>{t("benchmarkSetting")}</h2>
                {noteBenchmarks.map((benchmark) => (
                  <p key={benchmark}>{t(`benchmarkNotes.${benchmark}`)}</p>
                ))}
              </aside>
            )}
            <div className="evaluation-chart">
              <Chart
                rows={rows}
                title={title}
                compareHarnesses={compareHarnesses}
                history={showHistory}
                onSelect={navigateRow}
              />
            </div>
            <div className="evaluation-legend">
              <span>
                <i />
                {t("best")}
              </span>
              <span>
                <i className="faded" />
                {t("history")}
              </span>
              <span>
                <i className="line" />
                {t("pareto")}
              </span>
              <div className="evaluation-methodology">
                <TooltipPrimitive.Provider delayDuration={0}>
                  <TooltipPrimitive.Root
                    open={methodologyOpen}
                    onOpenChange={setMethodologyOpen}
                  >
                    <TooltipPrimitive.Trigger asChild>
                      <button
                        type="button"
                        aria-label={t("methodology")}
                        onKeyDown={(event) => {
                          if (event.key === "Escape") {
                            event.preventDefault();
                            setMethodologyOpen(false);
                          }
                        }}
                        onClick={(event) => {
                          event.preventDefault();
                          setMethodologyOpen(true);
                        }}
                      >
                        <CircleHelp size={14} aria-hidden="true" />
                        {t("methodology")}
                      </button>
                    </TooltipPrimitive.Trigger>
                    <TooltipPrimitive.Portal>
                      <TooltipPrimitive.Content
                        id="evaluation-methodology-tip"
                        className="evaluation-methodology-tooltip"
                        side="top"
                        align="end"
                        sideOffset={8}
                        collisionPadding={16}
                      >
                        {t("partialCostNote")}
                      </TooltipPrimitive.Content>
                    </TooltipPrimitive.Portal>
                  </TooltipPrimitive.Root>
                </TooltipPrimitive.Provider>
              </div>
            </div>
          </section>
          {error && (
            <p role="alert" className="evaluation-notice">
              {t(error)}
              <button onClick={() => setLoadAttempt((value) => value + 1)}>
                {t("retry")}
              </button>
            </p>
          )}
          {!error && !scopedRuns.length && (
            <p className="evaluation-notice">
              {loading ? t("loading") : t("empty")}
            </p>
          )}
          <section className="evaluation-results">
            <div className="evaluation-results-heading">
              <h2>
                <button
                  id="evaluation-results-toggle"
                  type="button"
                  aria-expanded={showTable}
                  aria-controls="evaluation-results-content"
                  onClick={() => setShowTable((value) => !value)}
                >
                  {showTable ? (
                    <ChevronUp size={18} aria-hidden="true" />
                  ) : (
                    <ChevronDown size={18} aria-hidden="true" />
                  )}
                  {t("tableTitle")}
                </button>
              </h2>
              <span>{t("recordsCount", { count: ordered.length })}</span>
            </div>
            <div
              id="evaluation-results-content"
              role="region"
              aria-labelledby="evaluation-results-toggle"
              hidden={!showTable}
            >
              <div className="evaluation-table-controls">
                <label>
                  <input
                    type="checkbox"
                    checked={onlyFrontier}
                    onChange={(e) => setOnlyFrontier(e.target.checked)}
                  />
                  {t("onlyFrontier")}
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={showBreakdown}
                    onChange={(e) => setShowBreakdown(e.target.checked)}
                  />
                  {t("breakdown")}
                </label>
                <label className="evaluation-search">
                  <Search size={15} />
                  <input
                    aria-label={t("search")}
                    placeholder={t("search")}
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                </label>
                <button onClick={() => download(tableRows)}>
                  <Download size={16} />
                  JSON
                </button>
              </div>
              <div className="evaluation-table-wrap" ref={tableRef}>
                <table className={showBreakdown ? "with-breakdown" : undefined}>
                  <thead>
                    <tr>
                      <th>{t("model")}</th>
                      {compareHarnesses && <th>Harness</th>}
                      <th>{t("sdk")}</th>
                      <th
                        className="evaluation-numeric"
                        aria-sort={
                          sort.key === "score"
                            ? sort.asc
                              ? "ascending"
                              : "descending"
                            : "none"
                        }
                      >
                        {sortButton("score", t("score"))}
                      </th>
                      <th
                        className="evaluation-numeric"
                        aria-sort={
                          sort.key === "cost"
                            ? sort.asc
                              ? "ascending"
                              : "descending"
                            : "none"
                        }
                      >
                        {sortButton("cost", t("cost"))}
                      </th>
                      <th
                        className="evaluation-numeric"
                        aria-sort={
                          sort.key === "runtime"
                            ? sort.asc
                              ? "ascending"
                              : "descending"
                            : "none"
                        }
                      >
                        {sortButton("runtime", t("runtime"))}
                      </th>
                      {showBreakdown &&
                        Object.entries(benchmarks).map(([key, label]) => (
                          <th key={key}>
                            {label}
                            <small>{t("metrics")}</small>
                          </th>
                        ))}
                      <th
                        className="evaluation-numeric"
                        aria-sort={
                          sort.key === "date"
                            ? sort.asc
                              ? "ascending"
                              : "descending"
                            : "none"
                        }
                      >
                        {sortButton("date", t("date"))}
                      </th>
                      <th>{t("coverage")}</th>
                      <th>{t("failureRate")}</th>
                      <th>{t("evidence")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ordered.map((row) => (
                      <tr
                        key={row.id}
                        className={best.has(row.id) ? "best" : ""}
                      >
                        <td>
                          <div className="evaluation-model">
                            {logo(row.model) ? (
                              <img src={logo(row.model)} alt="" />
                            ) : (
                              <CircleHelp size={22} aria-hidden="true" />
                            )}
                            <div>
                              <strong>{row.model}</strong>
                              {row.provider && <small>{row.provider}</small>}
                              {best.has(row.id) && (
                                <small>{t("bestShort")}</small>
                              )}
                              {pareto.has(row.id) && (
                                <small className="frontier">
                                  {t("onFrontier")}
                                </small>
                              )}
                            </div>
                          </div>
                        </td>
                        {compareHarnesses && (
                          <td>
                            <div className="evaluation-model">
                              {harnessLogo(row.harness) && (
                                <img alt="" src={harnessLogo(row.harness)} />
                              )}
                              {row.harness === "qwenpaw"
                                ? t("qwenpawDefault")
                                : row.harness}
                            </div>
                          </td>
                        )}
                        <td>
                          {row.sdk_version}
                          <small>
                            {row.source_sha?.slice(0, 8) ?? t("unknown")}
                          </small>
                        </td>
                        <td className="evaluation-score evaluation-numeric">
                          {(row.score === null
                            ? undefined
                            : number(row.score)) ?? t("incomplete")}
                          {row.score !== null && (
                            <span
                              className="evaluation-score-track"
                              aria-hidden="true"
                            >
                              <span
                                style={{
                                  width: `${Math.max(
                                    0,
                                    Math.min(100, row.score),
                                  )}%`,
                                }}
                              />
                            </span>
                          )}
                        </td>
                        <td>
                          {money(row.cost)}
                          <small>
                            {row.upperBound
                              ? t("upperBound")
                              : row.cost === null
                              ? ""
                              : row.benchmarks.some(
                                  (p) =>
                                    p.cost_sources.litellm_estimated ||
                                    p.cost_sources.snapshot_estimated,
                                )
                              ? t("estimated")
                              : t("reported")}
                          </small>
                          {row.cost !== null && row.partialCost && (
                            <small>
                              {t("costCoverage", {
                                known: row.costKnown,
                                total: row.costTotal,
                              })}
                            </small>
                          )}
                        </td>
                        <td>
                          {row.runtime === null
                            ? t("notRecorded")
                            : t("seconds", {
                                value: new Intl.NumberFormat(
                                  i18n.language,
                                ).format(Math.round(row.runtime)),
                              })}
                        </td>
                        {showBreakdown &&
                          Object.keys(benchmarks).map((key) => {
                            const p = row.benchmarks.find(
                              (b) => b.benchmark === key,
                            );
                            return (
                              <td key={key}>
                                {(p?.score == null
                                  ? undefined
                                  : number(p.score)) ?? "—"}
                                <small>
                                  {money(p?.mean_model_cost_usd ?? null)} /{" "}
                                  {p?.mean_runtime_seconds === null || !p
                                    ? t("notRecorded")
                                    : t("seconds", {
                                        value: new Intl.NumberFormat(
                                          i18n.language,
                                        ).format(
                                          Math.round(p.mean_runtime_seconds),
                                        ),
                                      })}
                                </small>
                              </td>
                            );
                          })}
                        <td className="evaluation-numeric">
                          {date(row.run.date)}
                        </td>
                        <td>{row.coverage}</td>
                        <td>
                          {row.failureRate === null
                            ? "—"
                            : `${(row.failureRate * 100).toFixed(1)}%`}
                        </td>
                        <td>
                          <button onClick={() => navigateRow(row)}>
                            {t("record")}
                            <ExternalLink size={13} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!ordered.length && (
                  <p className="evaluation-empty">{t("noMatch")}</p>
                )}
              </div>
            </div>
          </section>
        </>
      )}
    </main>
  );
}
