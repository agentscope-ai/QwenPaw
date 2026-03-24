import { useState, useRef, useEffect } from "react";
import { Link } from "react-router-dom";
import {
  Menu,
  X,
  BookOpen,
  Github,
  Globe,
  FileText,
  Download,
  ChevronDown,
} from "lucide-react";
import { CopawMascot } from "@/components/CopawMascot";
import { useTranslation } from "react-i18next";
import { useSiteLanguage } from "@/i18n/SiteLanguageContext";
import { useSiteConfig } from "@/config-context";

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

const navLinkClass =
  "inline-flex items-center gap-2 rounded-md px-1 py-1.5 text-sm font-medium text-neutral-800 no-underline transition-colors hover:!text-orange-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-400";

const navIconStroke = 1.5;

export function Nav() {
  const { projectName, docsPath } = useSiteConfig();
  const { toggleLang } = useSiteLanguage();
  const { t, i18n } = useTranslation();
  const isZh = i18n.resolvedLanguage === "zh";
  const [open, setOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const moreRef = useRef<HTMLDivElement>(null);
  const docsBase = docsPath.replace(/\/$/, "") || "/docs";

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (moreRef.current && !moreRef.current.contains(event.target as Node)) {
        setMoreOpen(false);
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && moreOpen) {
        setMoreOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [moreOpen]);

  return (
    <header className="sticky top-0 z-99 border-b border-neutral-100 bg-white">
      <nav className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-3 px-4 md:px-0">
        <Link
          to="/"
          className="nav-brand-link flex shrink-0 items-center gap-2 text-lg font-semibold text-neutral-900 no-underline"
          aria-label={projectName}
        >
          <span className="nav-brand-logo -mt-1 flex">
            <CopawMascot size={100} />
          </span>
        </Link>
        <div className="nav-links hidden min-[641px]:flex min-[641px]:items-center min-[641px]:gap-6 lg:gap-8">
          <div ref={moreRef} className="relative">
            <button
              type="button"
              onClick={() => setMoreOpen((o) => !o)}
              className={`${navLinkClass} cursor-pointer border-0 bg-transparent`}
              aria-expanded={moreOpen}
              aria-haspopup="true"
              aria-label={t("nav.more")}
            >
              <ChevronDown size={18} strokeWidth={navIconStroke} aria-hidden />
              <span>{t("nav.more")}</span>
            </button>
            {moreOpen && (
              <div
                role="menu"
                className="absolute right-0 top-[calc(100%+0.5rem)] z-50 min-w-[10rem] overflow-hidden rounded-xl border border-neutral-100 bg-white py-1 shadow-lg"
              >
                <Link
                  to="/release-notes"
                  role="menuitem"
                  className="flex items-center gap-2 whitespace-nowrap px-4 py-2.5 text-sm font-medium text-neutral-600 no-underline transition-colors hover:bg-neutral-50 hover:text-neutral-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-orange-400"
                  onClick={() => setMoreOpen(false)}
                >
                  <FileText size={16} strokeWidth={navIconStroke} aria-hidden />
                  <span>{t("nav.releaseNotes")}</span>
                </Link>
                <Link
                  to={`${docsBase}/quickstart`}
                  role="menuitem"
                  className="flex items-center gap-2 whitespace-nowrap px-4 py-2.5 text-sm font-medium text-neutral-600 no-underline transition-colors hover:bg-neutral-50 hover:text-neutral-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-orange-400"
                  onClick={() => setMoreOpen(false)}
                >
                  <Download size={16} strokeWidth={navIconStroke} aria-hidden />
                  <span>{t("nav.download")}</span>
                </Link>
              </div>
            )}
          </div>
          <Link to={docsBase} className={navLinkClass}>
            <BookOpen size={18} strokeWidth={navIconStroke} aria-hidden />
            <span>{t("nav.docs")}</span>
          </Link>
          <button
            type="button"
            onClick={toggleLang}
            className={`${navLinkClass} cursor-pointer border-0 bg-transparent`}
            aria-label={t("nav.lang")}
          >
            <Globe size={18} strokeWidth={navIconStroke} aria-hidden />
            <span>{t("nav.lang")}</span>
          </button>
          <a
            href="https://github.com/agentscope-ai/CoPaw"
            target="_blank"
            rel="noopener noreferrer"
            className={navLinkClass}
            title="CoPaw on GitHub"
          >
            <Github size={18} strokeWidth={navIconStroke} aria-hidden />
            <span>{t("nav.github")}</span>
          </a>
          <a
            href="https://agentscope.io/"
            target="_blank"
            rel="noopener noreferrer"
            className={`${navLinkClass} whitespace-nowrap`}
            title={isZh ? "基于 AgentScope 打造" : "Built on AgentScope"}
            aria-label={t("nav.agentscopeTeam")}
          >
            <AgentScopeLogo />
            <span>{t("nav.agentscopeTeam")}</span>
          </a>
        </div>

        <button
          type="button"
          className="nav-mobile-toggle flex min-[641px]:hidden items-center justify-center rounded-md border-0 bg-transparent p-2 text-neutral-900"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-label={open ? "Close menu" : "Open menu"}
        >
          {open ? <X size={24} /> : <Menu size={24} />}
        </button>
      </nav>

      {/* 移动端菜单 */}
      <div
        className={`nav-mobile flex min-[641px]:hidden flex-col gap-2 border-t border-neutral-100 bg-white px-4 py-3 sm:px-8 ${open ? "" : "hidden"}`}
      >
        <Link
          to="/release-notes"
          className={navLinkClass}
          onClick={() => setOpen(false)}
        >
          <FileText size={18} strokeWidth={navIconStroke} />
          {t("nav.releaseNotes")}
        </Link>
        <Link
          to={`${docsBase}/quickstart`}
          className={navLinkClass}
          onClick={() => setOpen(false)}
        >
          <Download size={18} strokeWidth={navIconStroke} />
          {t("nav.download")}
        </Link>
        <Link
          to={docsBase}
          className={navLinkClass}
          onClick={() => setOpen(false)}
        >
          <BookOpen size={18} strokeWidth={navIconStroke} /> {t("nav.docs")}
        </Link>
        <button
          type="button"
          className={`${navLinkClass} w-full cursor-pointer border-0 bg-transparent text-left`}
          onClick={() => {
            toggleLang();
            setOpen(false);
          }}
        >
          <Globe size={18} strokeWidth={navIconStroke} /> {t("nav.lang")}
        </button>
        <a
          href="https://github.com/agentscope-ai/CoPaw"
          target="_blank"
          rel="noopener noreferrer"
          className={navLinkClass}
          onClick={() => setOpen(false)}
          title="CoPaw on GitHub"
        >
          <Github size={18} strokeWidth={navIconStroke} /> {t("nav.github")}
        </a>
        <a
          href="https://agentscope.io/"
          target="_blank"
          rel="noopener noreferrer"
          className={`${navLinkClass} inline-flex items-center gap-2`}
          onClick={() => setOpen(false)}
          title={isZh ? "基于 AgentScope 打造" : "Built on AgentScope"}
          aria-label={t("nav.agentscopeTeam")}
        >
          <AgentScopeLogo />
          <span>{t("nav.agentscopeTeam")}</span>
        </a>
      </div>
    </header>
  );
}
