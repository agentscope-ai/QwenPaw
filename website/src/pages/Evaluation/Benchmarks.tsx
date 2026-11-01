import { Link } from "react-router-dom";
import {
  ArrowLeft,
  ArrowUpRight,
  Code2,
  FileSpreadsheet,
  Search,
  Workflow,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import "./style.css";

const benchmarks = [
  {
    id: "gaia",
    name: "GAIA",
    domain: "research",
    count: 165,
    Icon: Search,
    url: "https://huggingface.co/datasets/gaia-benchmark/GAIA",
  },
  {
    id: "spreadsheetbench-verified",
    name: "SpreadsheetBench Verified",
    domain: "office",
    count: 400,
    Icon: FileSpreadsheet,
    url: "https://spreadsheetbench.github.io/",
  },
  {
    id: "swebench-verified",
    name: "SWE-bench Verified",
    domain: "coding",
    count: 500,
    Icon: Code2,
    url: "https://openai.com/index/introducing-swe-bench-verified/",
  },
  {
    id: "pawbench",
    name: "PawBench",
    domain: "general",
    count: 150,
    Icon: Workflow,
    url: "https://agentscope-ai.github.io/PawBench/",
  },
];

export default function Benchmarks() {
  const { t } = useTranslation("evaluation");
  return (
    <main className="evaluation-page evaluation-guide">
      <Link to="/evaluation" className="evaluation-back">
        <ArrowLeft size={16} />
        {t("back")}
      </Link>
      <header className="evaluation-guide-header">
        <h1>{t("guideTitle")}</h1>
        <p>{t("guideIntro")}</p>
      </header>
      <div className="evaluation-benchmark-grid">
        {benchmarks.map(({ id, name, domain, count, Icon, url }) => (
          <article key={id} id={id} className="evaluation-benchmark-card">
            <header>
              <Icon size={24} strokeWidth={1.75} />
              <span>{t(`domains.${domain}`)}</span>
            </header>
            <h2>{name}</h2>
            <div className="evaluation-benchmark-scale">
              <strong>{count}</strong>
              {t("tasks")}
            </div>
            <p>{t(`guideBenchmarks.${id}.purpose`)}</p>
            <dl>
              <dt>{t("guideScope")}</dt>
              <dd>{t(`guideBenchmarks.${id}.scope`)}</dd>
              <dt>{t("guideScoring")}</dt>
              <dd>{t(`guideBenchmarks.${id}.scoring`)}</dd>
            </dl>
            <a href={url} target="_blank" rel="noopener noreferrer">
              {t("officialSource")}
              <ArrowUpRight size={16} />
            </a>
          </article>
        ))}
      </div>
      <section className="evaluation-guide-method">
        <h2>{t("guideCompareTitle")}</h2>
        <div>
          <p>{t("guideCompare")}</p>
          <p>{t("guideMetrics")}</p>
        </div>
      </section>
      <section className="evaluation-guide-method evaluation-guide-future">
        <h2>{t("guideFutureTitle")}</h2>
        <div>
          <p>{t("guideFuture")}</p>
          <a
            href="https://platform.agentscope.io/community"
            target="_blank"
            rel="noopener noreferrer"
          >
            {t("guideCommunity")}
            <ArrowUpRight size={16} />
          </a>
        </div>
      </section>
      <Link to="/evaluation" className="evaluation-back">
        <ArrowLeft size={16} />
        {t("back")}
      </Link>
    </main>
  );
}
