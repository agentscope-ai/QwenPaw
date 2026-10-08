import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ExternalLink } from "lucide-react";
import "./style.css";

export default function EvaluationPlan() {
  const { t } = useTranslation("evaluation");
  const sections = t("planSections", { returnObjects: true }) as {
    title: string;
    paragraphs: string[];
  }[];
  return (
    <main className="evaluation-page evaluation-plan">
      <nav className="evaluation-nav" aria-label={t("evaluation")}>
        <Link to="/evaluation">{t("evaluation")}</Link>
        <Link to="/evaluation/plan" className="selected">
          {t("plan")}
        </Link>
      </nav>
      <h1>{t("planTitle")}</h1>
      {sections.map((section, i) => (
        <section
          key={section.title}
          className={i === 0 ? "evaluation-tldr" : undefined}
        >
          <h2>{section.title}</h2>
          {section.paragraphs.map((paragraph) => (
            <p key={paragraph}>{paragraph}</p>
          ))}
        </section>
      ))}
      <section>
        <a
          href="https://docs.github.com/en/actions/reference/limits"
          target="_blank"
          rel="noreferrer"
        >
          {t("limits")} <ExternalLink size={14} />
        </a>
      </section>
    </main>
  );
}
