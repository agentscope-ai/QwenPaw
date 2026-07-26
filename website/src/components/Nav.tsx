import { useState, useRef, useEffect } from "react";
import { Link } from "react-router-dom";
import { Menu, X, BookOpen, Globe, Download, Ellipsis } from "lucide-react";
import { QwenpawMascot } from "./QwenpawMascot";
import { useTranslation } from "react-i18next";
import { useSiteLanguage } from "@/i18n/SiteLanguageContext";
import { useSiteConfig } from "@/config-context";
import { GitHubIcon, BlogIcon, NoteIcon, AgentScopePlatformIcon } from "./Icon";
import {
  CommunityBenefitsMobileList,
  CommunityBenefitsPanel,
  CommunityBenefitsTriggerLabel,
} from "./NavCommunityBenefits";

const AGENTSCOPE_PLATFORM_URL = "https://platform.agentscope.io/";

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

const navLinkBaseClass =
  "inline-flex shrink-0 items-center gap-2 whitespace-nowrap rounded-md px-1 py-1.5 text-sm font-medium text-neutral-800 no-underline transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2";

const navLinkOrangeClass = `${navLinkBaseClass} hover:!text-orange-400 focus-visible:outline-orange-400`;
const navLinkBlueClass = `${navLinkBaseClass} hover:!text-[#0064FD] focus-visible:outline-[#0064FD]`;

const navDownloadBtnClass = (isZh: boolean) =>
  `inline-flex shrink-0 items-center justify-center gap-1 whitespace-nowrap rounded-md ${
    isZh ? "px-3" : "px-1.5"
  } py-1.5 text-sm font-medium text-neutral-800 no-underline transition-colors cursor-pointer border border-[#F3F1F0] bg-(--color-card-fill) hover:bg-(--color-secondary)`;

const navIconStroke = 1.5;
const moreMenuItemClass = `${navLinkOrangeClass} w-full justify-start px-3 py-2`;

export function Nav() {
  const { projectName, docsPath } = useSiteConfig();
  const { toggleLang } = useSiteLanguage();
  const { t, i18n } = useTranslation();
  const isZh = i18n.resolvedLanguage === "zh";
  const [open, setOpen] = useState(false);
  const [benefitsOpen, setBenefitsOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [moreBenefitsOpen, setMoreBenefitsOpen] = useState(false);
  const [mobileBenefitsOpen, setMobileBenefitsOpen] = useState(false);
  const benefitsRef = useRef<HTMLDivElement>(null);
  const moreRef = useRef<HTMLDivElement>(null);
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const docsBase = docsPath.replace(/\/$/, "") || "/docs";

  const clearCloseTimer = () => {
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
  };

  const openBenefits = () => {
    clearCloseTimer();
    setBenefitsOpen(true);
  };

  const scheduleCloseBenefits = () => {
    clearCloseTimer();
    closeTimerRef.current = setTimeout(() => {
      setBenefitsOpen(false);
      closeTimerRef.current = null;
    }, 120);
  };

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as Node;
      if (benefitsRef.current && !benefitsRef.current.contains(target)) {
        setBenefitsOpen(false);
      }
      if (moreRef.current && !moreRef.current.contains(target)) {
        setMoreOpen(false);
        setMoreBenefitsOpen(false);
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setBenefitsOpen(false);
      setMoreOpen(false);
      setMoreBenefitsOpen(false);
    };
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, []);

  useEffect(() => {
    return () => clearCloseTimer();
  }, []);

  const platformLink = (
    <a
      href={AGENTSCOPE_PLATFORM_URL}
      target="_blank"
      rel="noopener noreferrer"
      className={navLinkOrangeClass}
      title={t("nav.platformTitle")}
      aria-label={t("nav.platformTitle")}
    >
      <AgentScopePlatformIcon size={18} />
      <span>{t("nav.platform")}</span>
    </a>
  );

  const agentscopeLink = (
    <a
      href="https://agentscope.io/"
      target="_blank"
      rel="noopener noreferrer"
      className={`${navLinkBlueClass} whitespace-nowrap`}
      title={isZh ? "基于 AgentScope 打造" : "Built on AgentScope"}
      aria-label={t("nav.agentscopeTeam")}
    >
      <AgentScopeLogo />
      <span>{t("nav.agentscopeTeam")}</span>
    </a>
  );

  const releaseNotesLink = (className: string) => (
    <Link to="/release-notes" className={className}>
      <NoteIcon />
      <span>{t("nav.releaseNotes")}</span>
    </Link>
  );

  const desktopBenefits = (
    <div
      ref={benefitsRef}
      className="relative hidden xl:block"
      onMouseEnter={openBenefits}
      onMouseLeave={scheduleCloseBenefits}
    >
      <button
        type="button"
        className={`${navLinkOrangeClass} cursor-pointer border-0 bg-transparent pt-2`}
        aria-expanded={benefitsOpen}
        aria-haspopup="true"
        onClick={() => setBenefitsOpen((v) => !v)}
      >
        <CommunityBenefitsTriggerLabel open={benefitsOpen} />
      </button>
      {benefitsOpen && (
        <div
          className="absolute left-1/2 top-full z-100 mt-2 -translate-x-1/2 rounded-xl border border-neutral-100 bg-white shadow-[0_12px_40px_rgba(0,0,0,0.12)]"
          role="menu"
          onMouseEnter={openBenefits}
          onMouseLeave={scheduleCloseBenefits}
        >
          <CommunityBenefitsPanel onNavigate={() => setBenefitsOpen(false)} />
        </div>
      )}
    </div>
  );

  return (
    <header className="sticky top-0 z-99 border-b border-border bg-white">
      <nav className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-2 px-4 md:px-0 lg:gap-3">
        <Link
          to="/"
          className="nav-brand-link flex shrink-0 items-center gap-2 text-lg font-semibold text-neutral-900 no-underline"
          aria-label={projectName}
        >
          <span className="nav-brand-logo -mt-1 flex">
            <QwenpawMascot size={120} />
          </span>
        </Link>
        <div className="nav-links hidden min-[641px]:flex min-[641px]:min-w-0 min-[641px]:flex-1 min-[641px]:items-center min-[641px]:justify-end min-[641px]:gap-3 lg:gap-5 xl:gap-6">
          <Link to={docsBase} className={navLinkOrangeClass}>
            <BookOpen size={18} strokeWidth={navIconStroke} aria-hidden />
            <span>{t("nav.docs")}</span>
          </Link>
          <Link to="/blog" className={navLinkOrangeClass}>
            <BlogIcon size={18} aria-hidden />
            <span>{t("nav.blog")}</span>
          </Link>
          <a
            href="https://github.com/agentscope-ai/QwenPaw"
            target="_blank"
            rel="noopener noreferrer"
            className={navLinkOrangeClass}
            title="QwenPaw on GitHub"
          >
            <GitHubIcon />
            <span>{t("nav.github")}</span>
          </a>

          {/* lg+: show Platform / AgentScope inline; below lg they move into More */}
          <span className="hidden lg:contents">
            {platformLink}
            {agentscopeLink}
          </span>

          {/* xl+: community benefits + release notes inline */}
          {desktopBenefits}
          <span className="hidden xl:contents">
            {releaseNotesLink(navLinkOrangeClass)}
          </span>

          {/* Overflow More: tablet / iPad */}
          <div ref={moreRef} className="relative xl:hidden">
            <button
              type="button"
              className={`${navLinkOrangeClass} cursor-pointer border-0 bg-transparent`}
              aria-expanded={moreOpen}
              aria-haspopup="true"
              aria-label={t("nav.more")}
              onClick={() => {
                setMoreOpen((v) => !v);
                setMoreBenefitsOpen(false);
              }}
            >
              <Ellipsis size={18} strokeWidth={navIconStroke} aria-hidden />
              <span className="sr-only">{t("nav.more")}</span>
            </button>
            {moreOpen && (
              <div
                className="absolute right-0 top-full z-100 mt-2 min-w-56 rounded-xl border border-neutral-100 bg-white py-2 shadow-[0_12px_40px_rgba(0,0,0,0.12)]"
                role="menu"
              >
                <div className="flex flex-col gap-0.5 px-1 lg:hidden">
                  <a
                    href={AGENTSCOPE_PLATFORM_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={moreMenuItemClass}
                    onClick={() => setMoreOpen(false)}
                  >
                    <AgentScopePlatformIcon size={18} />
                    <span>{t("nav.platform")}</span>
                  </a>
                  <a
                    href="https://agentscope.io/"
                    target="_blank"
                    rel="noopener noreferrer"
                    className={`${moreMenuItemClass} !text-[#0064FD]`}
                    onClick={() => setMoreOpen(false)}
                  >
                    <AgentScopeLogo />
                    <span>{t("nav.agentscopeTeam")}</span>
                  </a>
                </div>

                <div className="px-1">
                  <button
                    type="button"
                    className={`${moreMenuItemClass} cursor-pointer border-0 bg-transparent pt-2 text-left`}
                    aria-expanded={moreBenefitsOpen}
                    onClick={() => setMoreBenefitsOpen((v) => !v)}
                  >
                    <CommunityBenefitsTriggerLabel open={moreBenefitsOpen} />
                  </button>
                  {moreBenefitsOpen && (
                    <CommunityBenefitsMobileList
                      onNavigate={() => {
                        setMoreBenefitsOpen(false);
                        setMoreOpen(false);
                      }}
                    />
                  )}
                </div>

                <div className="px-1 pt-0.5">
                  {releaseNotesLink(moreMenuItemClass)}
                </div>
              </div>
            )}
          </div>

          <button
            type="button"
            onClick={toggleLang}
            className={`${navLinkOrangeClass} cursor-pointer border-0 bg-transparent`}
            aria-label={t("nav.lang")}
          >
            <Globe size={18} strokeWidth={navIconStroke} aria-hidden />
            <span>{t("nav.lang")}</span>
          </button>
          <Link to="/downloads" className={navDownloadBtnClass(isZh)}>
            <Download size={18} strokeWidth={navIconStroke} aria-hidden />
            <span>{t("nav.download")}</span>
          </Link>
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
        className={`nav-mobile flex min-[641px]:hidden flex-col gap-2 border-t border-neutral-100 bg-white px-4 py-3 sm:px-8 ${
          open ? "" : "hidden"
        }`}
      >
        <Link
          to={docsBase}
          className={navLinkOrangeClass}
          onClick={() => setOpen(false)}
        >
          <BookOpen size={18} strokeWidth={navIconStroke} /> {t("nav.docs")}
        </Link>
        <Link
          to="/blog"
          className={navLinkOrangeClass}
          onClick={() => setOpen(false)}
        >
          <BlogIcon size={18} aria-hidden /> {t("nav.blog")}
        </Link>
        <a
          href="https://github.com/agentscope-ai/QwenPaw"
          target="_blank"
          rel="noopener noreferrer"
          className={navLinkOrangeClass}
          onClick={() => setOpen(false)}
          title="QwenPaw on GitHub"
        >
          <GitHubIcon /> {t("nav.github")}
        </a>
        <a
          href={AGENTSCOPE_PLATFORM_URL}
          target="_blank"
          rel="noopener noreferrer"
          className={navLinkOrangeClass}
          onClick={() => setOpen(false)}
          title={t("nav.platformTitle")}
          aria-label={t("nav.platformTitle")}
        >
          <AgentScopePlatformIcon size={18} />
          <span>{t("nav.platform")}</span>
        </a>
        <a
          href="https://agentscope.io/"
          target="_blank"
          rel="noopener noreferrer"
          className={`${navLinkBlueClass} inline-flex items-center gap-2`}
          onClick={() => setOpen(false)}
          title={isZh ? "基于 AgentScope 打造" : "Built on AgentScope"}
          aria-label={t("nav.agentscopeTeam")}
        >
          <AgentScopeLogo />
          <span>{t("nav.agentscopeTeam")}</span>
        </a>

        <div>
          <button
            type="button"
            className={`${navLinkOrangeClass} w-full cursor-pointer border-0 bg-transparent pt-2 text-left`}
            aria-expanded={mobileBenefitsOpen}
            onClick={() => setMobileBenefitsOpen((v) => !v)}
          >
            <CommunityBenefitsTriggerLabel open={mobileBenefitsOpen} />
          </button>
          {mobileBenefitsOpen && (
            <CommunityBenefitsMobileList
              onNavigate={() => {
                setMobileBenefitsOpen(false);
                setOpen(false);
              }}
            />
          )}
        </div>

        <button
          type="button"
          className={`${navLinkOrangeClass} w-full cursor-pointer border-0 bg-transparent text-left`}
          onClick={() => {
            toggleLang();
            setOpen(false);
          }}
        >
          <Globe size={18} strokeWidth={navIconStroke} /> {t("nav.lang")}
        </button>
        <Link
          to="/release-notes"
          className={navLinkOrangeClass}
          onClick={() => setOpen(false)}
        >
          <NoteIcon />
          {t("nav.releaseNotes")}
        </Link>
        <Link
          to="/downloads"
          className={navLinkOrangeClass}
          onClick={() => setOpen(false)}
        >
          <Download size={18} strokeWidth={navIconStroke} />
          {t("nav.download")}
        </Link>
      </div>
    </header>
  );
}
