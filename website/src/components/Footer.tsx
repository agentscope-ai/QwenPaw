import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { QwenpawMascot } from "@/components/QwenpawMascot";
import { GitHubIcon, XIcon, DiscordIcon } from "./Icon";

const AGENTSCOPE_ORG = "https://github.com/agentscope-ai";
const AGENTSCOPE_REPO = "https://github.com/agentscope-ai/agentscope";
const AGENTSCOPE_RUNTIME =
  "https://github.com/agentscope-ai/agentscope-runtime";
const REME_REPO = "https://github.com/agentscope-ai/ReMe";

const X_URL = "https://x.com/agentscope_ai";
const DISCORD_URL = "https://discord.com/invite/eYMpfnkG8h";
const DINGTALK_URL =
  "https://qr.dingtalk.com/action/joingroup?code=v1,k1,1k7GcVwa5PzZWRaWyBA5OFImW0zNNx1Gj9RkjnuKVGY=&_dt_no_comment=1&origin=1";
const XIAOHONGSHU_URL =
  "https://www.xiaohongshu.com/user/profile/691c18db0000000037032be9";
export function Footer() {
  const { t } = useTranslation();
  const linkClass =
    "block text-sm text-[var(--text-muted)] transition-colors hover:!text-(--color-primary)";
  const sectionTitleClass = "text-sm font-semibold text-[var(--text)]";

  return (
    <footer className="mt-auto bg-white">
      <div className="mx-auto max-w-7xl px-6 py-10 md:py-12">
        <div className="flex flex-col gap-10 lg:flex-row lg:items-start lg:justify-between lg:gap-16">
          <section className="min-w-0 max-w-xl">
            <Link to="/" className="inline-flex items-center mb-4">
              <QwenpawMascot size={100} />
            </Link>
            <p className="mb-2 text-[15px] leading-7 text-(--text)">
              {t("whyQwenpaw.heroLine")}
              <br />
              {t("whyQwenpaw.secondPrefix")}
            </p>
            <div className="mt-5 flex items-center gap-4 text-[#f2a25b]">
              <a
                href={X_URL}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={t("footer.social.x")}
                className="inline-flex h-6 w-6 items-center justify-center leading-none"
              >
                <XIcon className="block" />
              </a>
              <a
                href="https://github.com/agentscope-ai/QwenPaw"
                target="_blank"
                rel="noopener noreferrer"
                aria-label={t("footer.social.github")}
                className="inline-flex h-6 w-6 items-center justify-center leading-none"
              >
                <GitHubIcon size={20} className="block text-orange-400" />
              </a>
              <a
                href={DISCORD_URL}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={t("footer.social.discord")}
                className="inline-flex h-6 w-6 items-center justify-center leading-none"
              >
                <DiscordIcon className="block" />
              </a>
              <a
                href={DINGTALK_URL}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={t("footer.social.dingtalk")}
                className="inline-flex h-6 w-6 items-center justify-center leading-none"
              >
                <img
                  height={20}
                  width={20}
                  src="https://img.alicdn.com/imgextra/i1/O1CN01w5mzV01tFtE37wkJI_!!6000000005873-2-tps-48-48.png"
                  className="block h-6 w-6"
                  style={{
                    filter:
                      "sepia(100%) hue-rotate(330deg) saturate(300%) brightness(90%)",
                  }}
                />
              </a>
              <a
                href={XIAOHONGSHU_URL}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={t("footer.social.xiaohongshu")}
                className="inline-flex h-6 w-6 items-center justify-center leading-none"
              >
                <span
                  aria-hidden
                  className="block text-[18px] leading-none text-orange-400"
                >
                  🍠
                </span>
              </a>
            </div>
          </section>

          <section className="shrink-0 lg:ml-auto lg:text-right">
            <div className="space-y-3">
              <h4 className={sectionTitleClass}>
                {t("footer.sections.builtBy")}
              </h4>
              <a
                href={AGENTSCOPE_ORG}
                target="_blank"
                rel="noopener noreferrer"
                className={linkClass}
              >
                {t("footer.poweredBy.team")}
              </a>
              <a
                href={AGENTSCOPE_REPO}
                target="_blank"
                rel="noopener noreferrer"
                className={linkClass}
              >
                {t("footer.poweredBy.agentscope")}
              </a>
              <a
                href={AGENTSCOPE_RUNTIME}
                target="_blank"
                rel="noopener noreferrer"
                className={linkClass}
              >
                {t("footer.poweredBy.runtime")}
              </a>
              <a
                href={REME_REPO}
                target="_blank"
                rel="noopener noreferrer"
                className={linkClass}
              >
                {t("footer.poweredBy.reme")}
              </a>
            </div>
          </section>
        </div>
      </div>
    </footer>
  );
}
