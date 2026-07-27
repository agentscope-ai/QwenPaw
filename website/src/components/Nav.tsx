import { useState, useRef, useEffect } from "react";
import { Link } from "react-router-dom";
import { Menu, X, BookOpen, Globe, Download, ChevronDown } from "lucide-react";
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

const navTextClass = "font-inter text-[14px] font-medium leading-5";

const navLinkBaseClass = `inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md px-1 py-1.5 ${navTextClass} text-neutral-800 no-underline transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2`;

const navLinkOrangeClass = `${navLinkBaseClass} hover:!text-orange-400 focus-visible:outline-orange-400`;
const navLinkBlueClass = `${navLinkBaseClass} hover:!text-[#0064FD] focus-visible:outline-[#0064FD]`;

const navDownloadBtnClass = `inline-flex min-w-[6.75rem] shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-md px-2.5 py-1.5 ${navTextClass} text-neutral-800 no-underline transition-colors cursor-pointer border border-[#F3F1F0] bg-(--color-card-fill) hover:bg-(--color-secondary)`;

const navIconStroke = 1.5;
const exploreMenuItemClass = `${navLinkOrangeClass} w-full justify-start px-3 py-2`;

export function Nav() {
  const { projectName, docsPath } = useSiteConfig();
  const { toggleLang } = useSiteLanguage();
  const { t, i18n } = useTranslation();
  const isZh = i18n.resolvedLanguage === "zh";
  const [open, setOpen] = useState(false);
  const [benefitsOpen, setBenefitsOpen] = useState(false);
  const [exploreOpen, setExploreOpen] = useState(false);
  const [mobileBenefitsOpen, setMobileBenefitsOpen] = useState(false);
  const benefitsRef = useRef<HTMLDivElement>(null);
  const exploreRef = useRef<HTMLDivElement>(null);
  const closeBenefitsTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const closeExploreTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const docsBase = docsPath.replace(/\/$/, "") || "/docs";

  const clearBenefitsTimer = () => {
    if (closeBenefitsTimerRef.current) {
      clearTimeout(closeBenefitsTimerRef.current);
      closeBenefitsTimerRef.current = null;
    }
  };

  const clearExploreTimer = () => {
    if (closeExploreTimerRef.current) {
      clearTimeout(closeExploreTimerRef.current);
      closeExploreTimerRef.current = null;
    }
  };

  const openBenefits = () => {
    clearBenefitsTimer();
    setExploreOpen(false);
    setBenefitsOpen(true);
  };

  const scheduleCloseBenefits = () => {
    clearBenefitsTimer();
    closeBenefitsTimerRef.current = setTimeout(() => {
      setBenefitsOpen(false);
      closeBenefitsTimerRef.current = null;
    }, 120);
  };

  const openExplore = () => {
    clearExploreTimer();
    setBenefitsOpen(false);
    setExploreOpen(true);
  };

  const scheduleCloseExplore = () => {
    clearExploreTimer();
    closeExploreTimerRef.current = setTimeout(() => {
      setExploreOpen(false);
      closeExploreTimerRef.current = null;
    }, 120);
  };

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as Node;
      if (benefitsRef.current && !benefitsRef.current.contains(target)) {
        setBenefitsOpen(false);
      }
      if (exploreRef.current && !exploreRef.current.contains(target)) {
        setExploreOpen(false);
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setBenefitsOpen(false);
      setExploreOpen(false);
    };
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, []);

  useEffect(() => {
    return () => {
      clearBenefitsTimer();
      clearExploreTimer();
    };
  }, []);

  return (
    <header className="sticky top-0 z-99 border-b border-border bg-white">
      <nav className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-2 px-4 sm:px-6 md:px-6 lg:gap-3">
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
          <div
            ref={benefitsRef}
            className="relative"
            onMouseEnter={openBenefits}
            onMouseLeave={scheduleCloseBenefits}
          >
            <span
              role="button"
              tabIndex={0}
              className={`${navLinkOrangeClass} cursor-pointer pt-2`}
              aria-expanded={benefitsOpen}
              aria-haspopup="true"
              onClick={() => {
                setExploreOpen(false);
                setBenefitsOpen((v) => !v);
              }}
              onKeyDown={(e) => {
                if (e.key !== "Enter" && e.key !== " ") return;
                e.preventDefault();
                setExploreOpen(false);
                setBenefitsOpen((v) => !v);
              }}
            >
              <CommunityBenefitsTriggerLabel open={benefitsOpen} />
            </span>
            {benefitsOpen && (
              <div
                className="absolute left-1/2 top-full z-100 mt-2 -translate-x-1/2 rounded-lg border border-neutral-100 bg-white shadow-[0_12px_40px_rgba(0,0,0,0.12)]"
                role="menu"
                onMouseEnter={openBenefits}
                onMouseLeave={scheduleCloseBenefits}
              >
                <CommunityBenefitsPanel
                  onNavigate={() => setBenefitsOpen(false)}
                />
              </div>
            )}
          </div>

          <div
            ref={exploreRef}
            className="relative"
            onMouseEnter={openExplore}
            onMouseLeave={scheduleCloseExplore}
          >
            <span
              role="button"
              tabIndex={0}
              className={`${navLinkOrangeClass} cursor-pointer`}
              aria-expanded={exploreOpen}
              aria-haspopup="true"
              onClick={() => {
                setBenefitsOpen(false);
                setExploreOpen((v) => !v);
              }}
              onKeyDown={(e) => {
                if (e.key !== "Enter" && e.key !== " ") return;
                e.preventDefault();
                setBenefitsOpen(false);
                setExploreOpen((v) => !v);
              }}
            >
              <span>{t("nav.explore")}</span>
              <ChevronDown
                size={16}
                strokeWidth={navIconStroke}
                className={`transition-transform ${
                  exploreOpen ? "rotate-180" : ""
                }`}
                aria-hidden
              />
            </span>
            {exploreOpen && (
              <div
                className="absolute left-1/2 top-full z-100 mt-2 min-w-44 -translate-x-1/2 rounded-lg border border-neutral-100 bg-white py-2 shadow-[0_12px_40px_rgba(0,0,0,0.12)]"
                role="menu"
                onMouseEnter={openExplore}
                onMouseLeave={scheduleCloseExplore}
              >
                <div className="flex flex-col gap-0.5 px-1">
                  <a
                    href={AGENTSCOPE_PLATFORM_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={exploreMenuItemClass}
                    title={t("nav.platformTitle")}
                    aria-label={t("nav.platformTitle")}
                    onClick={() => setExploreOpen(false)}
                  >
                    <AgentScopePlatformIcon size={18} />
                    <span>{t("nav.platform")}</span>
                  </a>
                  <Link
                    to="/blog"
                    className={exploreMenuItemClass}
                    onClick={() => setExploreOpen(false)}
                  >
                    <BlogIcon size={18} aria-hidden />
                    <span>{t("nav.blog")}</span>
                  </Link>
                  <a
                    href="https://github.com/agentscope-ai/QwenPaw"
                    target="_blank"
                    rel="noopener noreferrer"
                    className={exploreMenuItemClass}
                    title="QwenPaw on GitHub"
                    onClick={() => setExploreOpen(false)}
                  >
                    <GitHubIcon />
                    <span>{t("nav.github")}</span>
                  </a>
                  <Link
                    to="/release-notes"
                    className={exploreMenuItemClass}
                    onClick={() => setExploreOpen(false)}
                  >
                    <NoteIcon />
                    <span>{t("nav.releaseNotes")}</span>
                  </Link>
                </div>
              </div>
            )}
          </div>
          <Link to={docsBase} className={navLinkOrangeClass}>
            <BookOpen size={18} strokeWidth={navIconStroke} aria-hidden />
            <span>{t("nav.docs")}</span>
          </Link>

          <span
            role="button"
            tabIndex={0}
            onClick={toggleLang}
            onKeyDown={(e) => {
              if (e.key !== "Enter" && e.key !== " ") return;
              e.preventDefault();
              toggleLang();
            }}
            className={`${navLinkOrangeClass} cursor-pointer`}
            aria-label={t("nav.lang")}
          >
            <Globe size={18} strokeWidth={navIconStroke} aria-hidden />
            <span>{t("nav.lang")}</span>
          </span>
          <Link to="/downloads" className={navDownloadBtnClass}>
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
          <span
            role="button"
            tabIndex={0}
            className={`${navLinkOrangeClass} w-full cursor-pointer text-left`}
            aria-expanded={mobileBenefitsOpen}
            onClick={() => setMobileBenefitsOpen((v) => !v)}
            onKeyDown={(e) => {
              if (e.key !== "Enter" && e.key !== " ") return;
              e.preventDefault();
              setMobileBenefitsOpen((v) => !v);
            }}
          >
            <CommunityBenefitsTriggerLabel
              open={mobileBenefitsOpen}
              badgeAfter
            />
          </span>
          {mobileBenefitsOpen && (
            <CommunityBenefitsMobileList
              onNavigate={() => {
                setMobileBenefitsOpen(false);
                setOpen(false);
              }}
            />
          )}
        </div>

        <span
          role="button"
          tabIndex={0}
          className={`${navLinkOrangeClass} w-full cursor-pointer text-left`}
          onClick={() => {
            toggleLang();
            setOpen(false);
          }}
          onKeyDown={(e) => {
            if (e.key !== "Enter" && e.key !== " ") return;
            e.preventDefault();
            toggleLang();
            setOpen(false);
          }}
        >
          <Globe size={18} strokeWidth={navIconStroke} /> {t("nav.lang")}
        </span>
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
