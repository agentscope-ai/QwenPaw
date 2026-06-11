import { useState, useEffect } from "react";
import {
  Loader2,
  Copy,
  Check,
  Tag,
  Github,
  FileText,
  BookOpen,
  Play,
  HelpCircle,
  ChevronDown,
} from "lucide-react";
import LanguageSwitcher from "../components/LanguageSwitcher/index";
import ThemeToggleButton from "../components/ThemeToggleButton";
import CodingModeToggle from "../components/CodingModeToggle";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import api from "../api";
import { openExternalLink } from "../utils/openExternalLink";
import {
  GITHUB_URL,
  getDocsUrl,
  getFeatureDemosUrl,
  getFaqUrl,
  getReleaseNotesUrl,
  PYPI_URL,
  ONE_HOUR_MS,
  UPDATE_MD,
  isStableVersion,
  compareVersions,
} from "./constants";
import { useTheme } from "../contexts/ThemeContext";
import { Slot } from "../plugins/registry/Slot";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// ── Code block with copy button ───────────────────────────────────────────
function UpdateCodeBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };
  return (
    <div className="relative bg-muted border border-border rounded-md px-4 py-3 pr-10 overflow-x-auto my-2">
      <code className="font-mono text-[13px]">{code}</code>
      <button
        className={cn(
          "absolute top-2 right-2 p-1 rounded border-none bg-transparent cursor-pointer transition-colors hover:bg-accent",
          copied ? "text-green-500" : "text-muted-foreground",
        )}
        onClick={handleCopy}
        aria-label="Copy"
        title="Copy"
      >
        <span className="sr-only">Copy</span>
        {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
      </button>
    </div>
  );
}

export default function Header() {
  const { t, i18n } = useTranslation();
  const { isDark } = useTheme();
  const [version, setVersion] = useState<string>("");
  const [latestVersion, setLatestVersion] = useState<string>("");
  const [updateModalOpen, setUpdateModalOpen] = useState(false);
  const [updateMarkdown, setUpdateMarkdown] = useState<string>("");

  useEffect(() => {
    api
      .getVersion()
      .then((res) => setVersion(res?.version ?? ""))
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetch(PYPI_URL)
      .then((res) => res.json())
      .then((data) => {
        const releases = data?.releases ?? {};

        const versionsWithTime = Object.entries(releases)
          .filter(([v]) => isStableVersion(v))
          .map(([v, files]) => {
            const fileList = files as Array<{ upload_time_iso_8601?: string }>;
            const latestUpload = fileList
              .map((f) => f.upload_time_iso_8601)
              .filter(Boolean)
              .sort()
              .pop();
            return { version: v, uploadTime: latestUpload || "" };
          });

        versionsWithTime.sort((a, b) => {
          const timeDiff =
            new Date(b.uploadTime).getTime() - new Date(a.uploadTime).getTime();
          return timeDiff !== 0
            ? timeDiff
            : compareVersions(b.version, a.version);
        });

        const versions = versionsWithTime.map((v) => v.version);
        const latest = versions[0] ?? data?.info?.version ?? "";

        const releaseTime = versionsWithTime.find((v) => v.version === latest)
          ?.uploadTime;
        const isOldEnough =
          !!releaseTime &&
          new Date(releaseTime) <= new Date(Date.now() - ONE_HOUR_MS);

        if (isOldEnough) {
          setLatestVersion(latest);
        } else {
          setLatestVersion("");
        }
      })
      .catch(() => {});
  }, []);

  const hasUpdate =
    !!version && !!latestVersion && compareVersions(latestVersion, version) > 0;

  const handleOpenUpdateModal = () => {
    setUpdateMarkdown("");
    setUpdateModalOpen(true);
    const lang = i18n.language?.startsWith("zh")
      ? "zh"
      : i18n.language?.startsWith("ru")
      ? "ru"
      : "en";
    const faqLang = lang === "zh" ? "zh" : "en";
    const url = `https://qwenpaw.agentscope.io/docs/faq.${faqLang}.md`;
    fetch(url, { cache: "no-cache" })
      .then((res) => (res.ok ? res.text() : Promise.reject()))
      .then((text) => {
        const zhPattern = /###\s*QwenPaw如何更新[\s\S]*?(?=\n###|$)/;
        const enPattern = /###\s*How to update QwenPaw[\s\S]*?(?=\n###|$)/;
        const match = text.match(faqLang === "zh" ? zhPattern : enPattern);
        setUpdateMarkdown(
          match && lang !== "ru"
            ? match[0].trim()
            : UPDATE_MD[lang] ?? UPDATE_MD.en,
        );
      })
      .catch(() => {
        setUpdateMarkdown(UPDATE_MD[lang] ?? UPDATE_MD.en);
      });
  };

  const handleNavClick = (url: string) => {
    openExternalLink(url);
  };

  return (
    <>
      <header className="h-14 px-7 flex items-center justify-between shrink-0 bg-card border-b border-border">
        {/* Logo area */}
        <div className="flex items-center">
          <Slot name="header.logo" kind="replace">
            <img
              src={isDark ? "/logo-dark.svg" : "/logo-light.svg"}
              alt="QwenPaw"
              className="h-4 w-auto"
            />
          </Slot>
          <div className="w-px h-4 bg-border mx-2 rotate-0" />
          {version && (
            <span className="relative">
              {hasUpdate && (
                <span className="absolute -top-0.5 -right-1 w-1.5 h-1.5 rounded-full bg-primary z-10" />
              )}
              <span
                className={cn(
                  "text-xs font-semibold text-muted-foreground leading-none relative top-[3px]",
                  hasUpdate
                    ? "cursor-pointer hover:text-foreground"
                    : "cursor-default",
                )}
                onClick={() => hasUpdate && handleOpenUpdateModal()}
              >
                v{version}
              </span>
            </span>
          )}
        </div>

        <Slot name="header.left" kind="fill" />

        {/* Right side controls */}
        <div className="flex items-center gap-3">
          <Slot name="header.right" kind="fill" />

          {/* Resources dropdown */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="gap-1 text-sm">
                {t("header.resources")}
                <ChevronDown className="h-3.5 w-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                onClick={() => handleNavClick(getDocsUrl(i18n.language))}
              >
                <BookOpen className="h-4 w-4" />
                {t("header.tutorial")}
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() =>
                  handleNavClick(getFeatureDemosUrl(i18n.language))
                }
              >
                <Play className="h-4 w-4" />
                {t("header.featureDemos")}
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() =>
                  handleNavClick(getReleaseNotesUrl(i18n.language))
                }
              >
                <FileText className="h-4 w-4" />
                {t("header.changelog")}
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => handleNavClick(getFaqUrl(i18n.language))}
              >
                <HelpCircle className="h-4 w-4" />
                {t("header.faq")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          {/* GitHub button */}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className="gap-1.5 text-sm"
                onClick={() => handleNavClick(GITHUB_URL)}
              >
                <Github className="h-4 w-4" />
                {t("header.github")}
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("header.github")}</TooltipContent>
          </Tooltip>

          <div className="w-px h-4 bg-border" />
          <CodingModeToggle />
          <div className="w-px h-4 bg-border" />
          <LanguageSwitcher />
          <ThemeToggleButton />
        </div>
      </header>

      {/* Update modal */}
      <Dialog open={updateModalOpen} onOpenChange={setUpdateModalOpen}>
        <DialogContent className="max-w-[960px] p-0 overflow-hidden rounded-xl border-none shadow-none">
          <DialogHeader className="sr-only">
            <DialogTitle>
              {t("sidebar.updateModal.title", {
                version: latestVersion || version,
              })}
            </DialogTitle>
            <DialogDescription>
              {t(
                "sidebar.updateModal.description",
                "Release notes and update instructions.",
              )}
            </DialogDescription>
          </DialogHeader>
          {/* Banner area */}
          <div
            className="px-7 pt-12 pb-0 flex items-start justify-between min-h-[100px] relative -translate-y-12"
            style={{
              background: "url('/qwenpawBack.png') no-repeat center top",
              backgroundSize: "contain",
            }}
          >
            <div className="flex flex-col gap-2.5">
              <span className="inline-flex items-center gap-1.5 bg-card border border-border rounded-full px-3 py-0.5 text-xs font-medium text-muted-foreground">
                <Tag className="h-3 w-3" />
                Version {latestVersion || version}
              </span>
              <div className="text-[32px] font-medium text-foreground leading-[64px]">
                {t("sidebar.updateModal.title", {
                  version: latestVersion || version,
                })}
              </div>
            </div>
          </div>

          {/* Markdown content */}
          <div className="max-h-[400px] overflow-y-auto px-6 pb-2 min-h-[120px] -mt-10">
            {updateMarkdown ? (
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  a({ href, children, ...props }: React.ComponentProps<"a">) {
                    return (
                      <a
                        {...props}
                        href={href}
                        onClick={(e) => {
                          e.preventDefault();
                          if (href) handleNavClick(href);
                        }}
                        className="cursor-pointer text-primary hover:underline"
                      >
                        {children}
                      </a>
                    );
                  },
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  code({ node, className, children, ...props }: any) {
                    const match = /language-(\w+)/.exec(className || "");
                    const isBlock =
                      node?.position?.start?.line !==
                        node?.position?.end?.line || match;
                    return isBlock ? (
                      <UpdateCodeBlock
                        code={String(children).replace(/\n$/, "")}
                      />
                    ) : (
                      <code
                        className="bg-muted rounded px-1 py-0.5 font-mono text-[13px]"
                        {...props}
                      >
                        {children}
                      </code>
                    );
                  },
                }}
              >
                {updateMarkdown}
              </ReactMarkdown>
            ) : (
              <div className="flex justify-center items-center h-[120px]">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            )}
          </div>

          <DialogFooter className="px-6 py-3">
            <Button variant="outline" onClick={() => setUpdateModalOpen(false)}>
              {t("common.close")}
            </Button>
            <Button
              className="bg-primary text-primary-foreground hover:bg-primary/90"
              onClick={() => handleNavClick(getReleaseNotesUrl(i18n.language))}
            >
              {t("sidebar.updateModal.viewReleases")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
