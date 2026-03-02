import { useState } from "react";
import { Link } from "react-router-dom";
import { Menu, X, BookOpen, Github, Globe } from "lucide-react";
import { CopawMascot } from "./CopawMascot";
import { t, type Lang } from "../i18n";

const AGENTSCOPE_LOGO_SIZE = 22;

const agentscopeLogoStyle: React.CSSProperties = {
  display: "block",
  flexShrink: 0,
  width: AGENTSCOPE_LOGO_SIZE,
  height: AGENTSCOPE_LOGO_SIZE,
  objectFit: "contain",
  verticalAlign: "middle",
  marginTop: -2,
};

function AgentScopeLogo() {
  return (
    <img
      src="/agentscope.svg"
      alt=""
      width={AGENTSCOPE_LOGO_SIZE}
      height={AGENTSCOPE_LOGO_SIZE}
      style={agentscopeLogoStyle}
      aria-hidden
    />
  );
}

interface NavProps {
  projectName: string;
  lang: Lang;
  onLangClick: () => void;
  docsPath: string;
  repoUrl: string;
}

export function Nav({
  projectName,
  lang,
  onLangClick,
  docsPath,
  repoUrl: _repoUrl,
}: NavProps) {
  const [open, setOpen] = useState(false);
  const linkClass =
    "nav-item text-[var(--text-muted)] hover:text-[var(--text)] transition-colors";
  return (
    <header
      style={{
        position: "sticky",
        top: 0,
        zIndex: 10,
        background: "var(--surface)",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <nav
        style={{
          margin: "0 auto",
          maxWidth: "var(--container)",
          padding: "var(--space-2) var(--space-4)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "var(--space-3)",
        }}
      >
        <Link
          to="/"
          className="nav-brand-link"
          style={{
            display: "flex",
            alignItems: "center",
            gap: "var(--space-2)",
            fontWeight: 600,
            fontSize: "1.125rem",
            color: "var(--text)",
          }}
          aria-label={projectName}
        >
          <span
            className="nav-brand-logo"
            style={{ marginTop: -5, display: "flex" }}
          >
            <CopawMascot size={60} />
          </span>
        </Link>
        <div
          className="nav-links"
          style={{
            display: "flex",
            alignItems: "center",
            gap: "var(--space-4)",
          }}
        >
          <button
            type="button"
            onClick={onLangClick}
            className={linkClass}
            style={{
              background: "none",
              border: "none",
              padding: "var(--space-1) var(--space-2)",
            }}
            aria-label={t(lang, "nav.lang")}
          >
            <Globe size={18} strokeWidth={1.5} aria-hidden />
            <span>{t(lang, "nav.lang")}</span>
          </button>
          <Link
            to={docsPath.replace(/\/$/, "") || "/docs"}
            className={linkClass}
          >
            <BookOpen size={18} strokeWidth={1.5} aria-hidden />
            <span>{t(lang, "nav.docs")}</span>
          </Link>
          <a
            href="https://github.com/agentscope-ai/CoPaw"
            target="_blank"
            rel="noopener noreferrer"
            className={linkClass}
            title="CoPaw on GitHub"
          >
            <Github size={18} strokeWidth={1.5} aria-hidden />
            <span>{t(lang, "nav.github")}</span>
          </a>
          <a
            href="https://agentscope.io/"
            target="_blank"
            rel="noopener noreferrer"
            className={linkClass}
            title={
              lang === "zh" ? "基于 AgentScope 打造" : "Built on AgentScope"
            }
            aria-label={t(lang, "nav.agentscopeTeam")}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "var(--space-1)",
              whiteSpace: "nowrap",
              fontSize: "inherit",
              fontWeight: "inherit",
            }}
          >
            <AgentScopeLogo />
            <span style={{ fontSize: "inherit" }}>
              {t(lang, "nav.agentscopeTeam")}
            </span>
          </a>
        </div>
        <button
          type="button"
          className="nav-mobile-toggle"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-label={open ? "Close menu" : "Open menu"}
          style={{
            display: "none",
            background: "none",
            border: "none",
            padding: "var(--space-2)",
            color: "var(--text)",
          }}
        >
          {open ? <X size={24} /> : <Menu size={24} />}
        </button>
      </nav>
      <div
        className="nav-mobile"
        style={{
          display: open ? "flex" : "none",
          padding: "var(--space-2) var(--space-4)",
          borderTop: "1px solid var(--border)",
          background: "var(--surface)",
          flexDirection: "column",
          gap: "var(--space-2)",
        }}
      >
        <button
          type="button"
          className={linkClass}
          onClick={() => {
            onLangClick();
            setOpen(false);
          }}
          style={{ background: "none", border: "none", textAlign: "left" }}
        >
          <Globe size={18} /> {t(lang, "nav.lang")}
        </button>
        <Link
          to={docsPath.replace(/\/$/, "") || "/docs"}
          className={linkClass}
          onClick={() => setOpen(false)}
        >
          <BookOpen size={18} /> {t(lang, "nav.docs")}
        </Link>
        <a
          href="https://github.com/agentscope-ai/CoPaw"
          target="_blank"
          rel="noopener noreferrer"
          className={linkClass}
          onClick={() => setOpen(false)}
          title="CoPaw on GitHub"
        >
          <Github size={18} /> {t(lang, "nav.github")}
        </a>
        <a
          href="https://agentscope.io/"
          target="_blank"
          rel="noopener noreferrer"
          className={linkClass}
          onClick={() => setOpen(false)}
          title={lang === "zh" ? "基于 AgentScope 打造" : "Built on AgentScope"}
          aria-label={t(lang, "nav.agentscopeTeam")}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "var(--space-1)",
            fontSize: "inherit",
            fontWeight: "inherit",
          }}
        >
          <AgentScopeLogo />
          <span style={{ fontSize: "inherit" }}>
            {t(lang, "nav.agentscopeTeam")}
          </span>
        </a>
      </div>
      <style>{`
        @media (max-width: 640px) {
          .nav-links { display: none !important; }
          .nav-mobile-toggle { display: flex !important; }
        }
        @media (min-width: 641px) {
          .nav-mobile { display: none !important; }
        }
      `}</style>
    </header>
  );
}
