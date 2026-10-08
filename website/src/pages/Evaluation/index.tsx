import { useTranslation } from "react-i18next";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  ChevronUp,
  Download,
  ExternalLink,
  Search,
} from "lucide-react";
import Chart, { bestRows, frontier } from "./Chart";
import { demoHistory } from "./demo";
import {
  benchmarks,
  domains,
  logo,
  money as formatMoney,
  safeWorkflow,
  selectRows,
  type History,
  type Row,
} from "./types";
import "./style.css";

const visibility =
  import.meta.env.VITE_EVALUATION_VISIBILITY === "private"
    ? "private"
    : "public";
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
    formatMoney(value, i18n.language, t("unknown"));
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
  const [params, setParams] = useSearchParams();
  const { id } = useParams();
  const navigate = useNavigate();
  const demo = params.get("demo") === "1";
  const privateView =
    visibility === "private" || (demo && params.get("scope") === "private");
  const [data, setData] = useState<History>({
    schema_version: 1,
    visibility,
    runs: [],
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [metric, setMetric] = useState("index");
  const [search, setSearch] = useState("");
  const [showHistory, setShowHistory] = useState(true);
  const [showTable, setShowTable] = useState(true);
  const [onlyFrontier, setOnlyFrontier] = useState(false);
  const [protocol, setProtocol] = useState("");
  const [sort, setSort] = useState<{
    key: "score" | "cost" | "runtime" | "date";
    asc: boolean;
  }>({ key: "score", asc: false });
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${import.meta.env.BASE_URL}evaluation/data/index.json`, {
      signal: controller.signal,
    })
      .then((response) => {
        if (!response.ok) throw new Error("unavailable");
        return response.json();
      })
      .then((history: History) => {
        if (
          history.schema_version !== 1 ||
          history.visibility !== visibility ||
          !Array.isArray(history.runs) ||
          history.runs.some(
            (run) =>
              run.visibility !== visibility || !Array.isArray(run.records),
          )
        )
          throw new Error("invalidData");
        setData(history);
      })
      .catch((e: Error) => {
        if (e.name !== "AbortError")
          setError(e.message === "invalidData" ? "invalidData" : "unavailable");
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);
  const history = useMemo(
    () => (demo ? demoHistory(privateView) : data),
    [demo, privateView, data],
  );
  const versions = [...new Set(history.runs.map((run) => run.index_version))];
  const activeProtocol = versions.includes(protocol) ? protocol : versions[0];
  const rows = useMemo(
    () =>
      selectRows(
        history.runs.filter((run) => run.index_version === activeProtocol),
        metric,
      ).filter((row) =>
        `${row.model} ${row.sdk_version} ${row.harness}`
          .toLowerCase()
          .includes(search.toLowerCase()),
      ),
    [history, activeProtocol, metric, search],
  );
  const best = useMemo(() => bestRows(rows, privateView), [rows, privateView]);
  const pareto = useMemo(
    () =>
      new Set(
        frontier(rows.filter((row) => best.has(row.id))).map((row) => row.id),
      ),
    [rows, best],
  );
  const visible = useMemo(
    () => rows.filter((row) => !onlyFrontier || pareto.has(row.id)),
    [rows, onlyFrontier, pareto],
  );
  const ordered = [...visible].sort((a, b) => {
    const av = sort.key === "date" ? a.run.date : a[sort.key];
    const bv = sort.key === "date" ? b.run.date : b[sort.key];
    if (av === null) return bv === null ? 0 : 1;
    if (bv === null) return -1;
    return (av < bv ? -1 : av > bv ? 1 : 0) * (sort.asc ? 1 : -1);
  });
  const navigateRow = useCallback(
    (row: Row) =>
      navigate(
        `/evaluation/runs/${row.run.manifest_sha256}${
          demo ? `?demo=1${privateView ? "&scope=private" : ""}` : ""
        }`,
      ),
    [navigate, demo, privateView],
  );
  const detail = id
    ? history.runs.find((run) => run.manifest_sha256 === id)
    : undefined;
  const title =
    metric === "index"
      ? "Index"
      : metric.startsWith("domain:")
      ? t(`domains.${metric.slice(7)}`)
      : benchmarks[metric.slice(10)];
  const changeDemo = (enabled: boolean) => {
    const next = new URLSearchParams(params);
    if (enabled) next.set("demo", "1");
    else {
      next.delete("demo");
      next.delete("scope");
    }
    setParams(next);
  };
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
      <nav className="evaluation-nav" aria-label={t("evaluation")}>
        <Link to="/evaluation" className="selected">
          {t("evaluation")}
        </Link>
        <Link to="/evaluation/plan">{t("plan")}</Link>
        <span>{privateView ? t("private") : t("public")}</span>
      </nav>
      {id ? (
        <section className="evaluation-detail">
          <Link to={`/evaluation${demo ? "?demo=1" : ""}`}>{t("back")}</Link>
          <h1>{t("runTitle")}</h1>
          {loading && !demo ? (
            <p>{t("loading")}</p>
          ) : !detail ? (
            <p>{t("notFound")}</p>
          ) : (
            <>
              {demo && <p className="evaluation-notice">{t("demoRecord")}</p>}
              <dl>
                <dt>{t("date")}</dt>
                <dd>{date(detail.date)}</dd>
                <dt>{t("indexProtocol")}</dt>
                <dd>{detail.index_version}</dd>
                <dt>{t("sourceSha")}</dt>
                <dd>{detail.evaluation_sha}</dd>
                <dt>Manifest</dt>
                <dd>{detail.manifest_sha256}</dd>
                <dt>{t("priceSnapshot")}</dt>
                <dd>{detail.prices.version}</dd>
                <dt>{t("exchangeRate")}</dt>
                <dd>
                  {detail.prices.fx.cny_per_usd} CNY/USD ·{" "}
                  {detail.prices.fx.date}
                </dd>
              </dl>
              {safeWorkflow(detail.workflow_url) && (
                <a href={detail.workflow_url} target="_blank" rel="noreferrer">
                  {t("workflow")}
                  <ExternalLink size={14} />
                </a>
              )}
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
          <div className="evaluation-controls">
            <label>
              {t("board")}
              <select
                value={metric}
                onChange={(e) => setMetric(e.target.value)}
              >
                <option value="index">{t("main")}</option>
                <optgroup label={t("domainBoards")}>
                  {Object.keys(domains).map((key) => (
                    <option key={key} value={`domain:${key}`}>
                      {t(`domains.${key}`)}
                    </option>
                  ))}
                </optgroup>
                <optgroup label={t("benchmarkBoards")}>
                  {Object.entries(benchmarks).map(([key, label]) => (
                    <option key={key} value={`benchmark:${key}`}>
                      {label}
                    </option>
                  ))}
                </optgroup>
              </select>
            </label>
            {versions.length > 1 && (
              <label>
                {t("protocol")}
                <select
                  value={activeProtocol}
                  onChange={(e) => setProtocol(e.target.value)}
                >
                  {versions.map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
              </label>
            )}
            <label>
              <input
                type="checkbox"
                checked={showHistory}
                onChange={(e) => setShowHistory(e.target.checked)}
              />
              {t("historyPoints")}
            </label>
            <label>
              <input
                type="checkbox"
                checked={demo}
                onChange={(e) => changeDemo(e.target.checked)}
              />
              {t("demo")}
            </label>
            {demo && (
              <select
                aria-label={t("demoScope")}
                value={privateView ? "private" : "public"}
                onChange={(e) => {
                  const next = new URLSearchParams(params);
                  next.set("scope", e.target.value);
                  setParams(next);
                }}
              >
                <option value="public">{t("publicDemo")}</option>
                <option value="private">{t("privateDemo")}</option>
              </select>
            )}
          </div>
          <div className="evaluation-chart">
            <Chart
              rows={visible}
              title={title}
              privateView={privateView}
              history={showHistory}
              demo={demo}
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
            <span className="evaluation-right">
              {demo ? t("mock") : t("costNote")}
            </span>
          </div>
          <p className="evaluation-note">
            {t("chartNote")}
            {privateView && t("privateNote")}
          </p>
          {error && !demo && (
            <p role="alert" className="evaluation-notice">
              {t(error)}
            </p>
          )}
          {!demo && !data.runs.length && (
            <p className="evaluation-notice">
              {loading ? t("loading") : t("empty")}
            </p>
          )}
          <div className="evaluation-table-controls">
            <button onClick={() => setShowTable(!showTable)}>
              {showTable ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              {t("toggleTable")}
            </button>
            <label>
              <input
                type="checkbox"
                checked={onlyFrontier}
                onChange={(e) => setOnlyFrontier(e.target.checked)}
              />
              {t("onlyFrontier")}
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
            <button onClick={() => download(visible)}>
              <Download size={16} />
              JSON
            </button>
          </div>
          {showTable && (
            <div className="evaluation-table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>{t("model")}</th>
                    {privateView && <th>Harness</th>}
                    <th>{t("sdk")}</th>
                    <th>{sortButton("score", `${title} ${t("score")}`)}</th>
                    <th>{sortButton("cost", t("cost"))}</th>
                    <th>{sortButton("runtime", t("runtime"))}</th>
                    {Object.entries(benchmarks).map(([key, label]) => (
                      <th key={key}>
                        {label}
                        <small>{t("metrics")}</small>
                      </th>
                    ))}
                    <th>{sortButton("date", t("date"))}</th>
                    <th>{t("coverage")}</th>
                    <th>{t("evidence")}</th>
                  </tr>
                </thead>
                <tbody>
                  {ordered.map((row) => (
                    <tr key={row.id} className={best.has(row.id) ? "best" : ""}>
                      <td>
                        <div className="evaluation-model">
                          <img src={logo(row.model)} alt="" />
                          <div>
                            <strong>{row.model}</strong>
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
                      {privateView && (
                        <td>
                          <div className="evaluation-model">
                            <img
                              alt=""
                              src={`${
                                import.meta.env.BASE_URL
                              }evaluation/logos/${row.harness
                                .toLowerCase()
                                .replace(/[^a-z]/g, "")}.${
                                row.harness === "QwenPaw" ? "png" : "svg"
                              }`}
                            />
                            {row.harness}
                          </div>
                        </td>
                      )}
                      <td>
                        {row.sdk_version}
                        <small>{row.source_sha.slice(0, 8)}</small>
                      </td>
                      <td className="evaluation-score">
                        {(row.score === null ? undefined : number(row.score)) ??
                          t("incomplete")}
                      </td>
                      <td>
                        {money(row.cost)}
                        <small>
                          {row.upperBound
                            ? t("upperBound")
                            : row.cost === null
                            ? t("unknown")
                            : row.benchmarks.some(
                                (p) =>
                                  p.cost_sources.litellm_estimated ||
                                  p.cost_sources.snapshot_estimated,
                              )
                            ? t("estimated")
                            : t("reported")}
                        </small>
                      </td>
                      <td>
                        {row.runtime === null
                          ? t("unknown")
                          : t("seconds", {
                              value: new Intl.NumberFormat(
                                i18n.language,
                              ).format(Math.round(row.runtime)),
                            })}
                      </td>
                      {Object.keys(benchmarks).map((key) => {
                        const p = row.benchmarks.find(
                          (b) => b.benchmark === key,
                        );
                        return (
                          <td key={key}>
                            {(p?.score == null ? undefined : number(p.score)) ??
                              "—"}
                            <small>
                              {money(p?.mean_model_cost_usd ?? null)} /{" "}
                              {p?.mean_runtime_seconds === null || !p
                                ? t("unknown")
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
                      <td>{date(row.run.date)}</td>
                      <td>
                        {row.coverage}
                        {row.run.latest_attempts?.some(
                          (attempt) => !attempt.complete,
                        ) && (
                          <small className="evaluation-rerun-status">
                            {t("latestIncomplete")}
                          </small>
                        )}
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
          )}
          <p className="evaluation-note">{t("weightNote")}</p>
        </>
      )}
    </main>
  );
}
