import { Github, MessageCircle, Twitter, Youtube } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { CopawMascot } from "@/components/CopawMascot";

const AGENTSCOPE_ORG = "https://github.com/agentscope-ai";
const AGENTSCOPE_REPO = "https://github.com/agentscope-ai/agentscope";
const AGENTSCOPE_RUNTIME =
  "https://github.com/agentscope-ai/agentscope-runtime";
const REME_REPO = "https://github.com/agentscope-ai/ReMe";
const ANTHROPIC_SKILLS_URL =
  "https://github.com/anthropics/skills?tab=readme-ov-file";

const X_URL = "https://x.com/agentscope_ai";
const DISCORD_URL = "https://discord.gg/XJ9KWJ9WmN";
const YOUTUBE_URL = "https://www.youtube.com/@AgentScope";
const TERMS_URL =
  "https://www.alibabacloud.com/help/en/legal/latest/terms-of-service";
const PRIVACY_URL =
  "https://www.alibabacloud.com/help/en/legal/latest/alibaba-cloud-international-website-privacy-policy";

export function Footer() {
  const { t } = useTranslation();
  const linkClass =
    "block text-sm text-[var(--text-muted)] transition-colors hover:!text-[var(--text)]";
  const sectionTitleClass = "text-sm font-semibold text-[var(--text)]";

  return (
    <footer className="mt-auto bg-white">
      <div className="mx-auto max-w-7xl px-6 py-10 md:py-12">
        <div className="grid grid-cols-1 gap-10 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)] lg:gap-60">
          <section>
            <Link to="/" className="inline-flex items-center mb-4">
              <CopawMascot size={80} />
            </Link>
            <p className="mb-2 text-[15px] leading-7 text-[var(--text)]">
              {t("brandstory.para1")}
              <br />
              {t("brandstory.para2")}
            </p>
            <div className="mt-5 flex items-center gap-4 text-[#f2a25b]">
              <a
                href={X_URL}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={t("footer.social.x")}
              >
                <Twitter size={18} strokeWidth={1.8} className="text-orange-400" />
              </a>
              <a
                href="https://github.com/agentscope-ai/CoPaw"
                target="_blank"
                rel="noopener noreferrer"
                aria-label={t("footer.social.github")}
              >
                <Github size={18} strokeWidth={1.8} className="text-orange-400" />
              </a>
              <a
                href={DISCORD_URL}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={t("footer.social.discord")}
              >
                <MessageCircle size={18} strokeWidth={1.8} className="text-orange-400"/>
              </a>
              <a
                href={YOUTUBE_URL}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={t("footer.social.youtube")}
              >
                <Youtube size={18} strokeWidth={1.8} className="text-orange-400" />
              </a>
            </div>
          </section>

          <section className="grid grid-cols-2 gap-4 sm:grid-cols-3">
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

            <div className="space-y-3">
              <h4 className={sectionTitleClass}>
                {t("footer.sections.resources")}
              </h4>
              <Link to="/docs" className={linkClass}>
                {t("footer.links.docs")}
              </Link>
              <a
                href="https://github.com/agentscope-ai/CoPaw/discussions"
                target="_blank"
                rel="noopener noreferrer"
                className={linkClass}
              >
                {t("footer.links.blog")}
              </a>
              <Link to="/release-notes" className={linkClass}>
                {t("footer.links.changelog")}
              </Link>
            </div>

            <div className="space-y-3">
              <h4 className={sectionTitleClass}>
                {t("footer.sections.terms")}
              </h4>
              <a
                href={TERMS_URL}
                target="_blank"
                rel="noopener noreferrer"
                className={linkClass}
              >
                {t("footer.links.termsOfService")}
              </a>
              <a
                href={PRIVACY_URL}
                target="_blank"
                rel="noopener noreferrer"
                className={linkClass}
              >
                {t("footer.links.privacyPolicy")}
              </a>
            </div>
          </section>
        </div>

        <div className="mt-10 pt-6 text-base text-[var(--text-muted)]">
          <p>
            {t("footer.thanksSkills.text")}
            <a
              href={ANTHROPIC_SKILLS_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-2"
            >
              {t("footer.thanksSkills.name")}
            </a>
            {t("footer.thanksSkills.suffix")}
          </p>
          <p className="mt-2">
            {t("footer.copyright")}
          </p>
        </div>
      </div>
    </footer>
  );
}
