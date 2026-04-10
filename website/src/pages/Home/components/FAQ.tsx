import { type ReactNode, useMemo, useState } from "react";
import { motion } from "motion/react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { sectionStyles } from "@/lib/utils";

type FaqCategory = "quickStart" | "features" | "troubleshooting";

type FaqItem = {
  id: string;
  question: string;
  answer: ReactNode | string;
};

const sectionVariants = {
  hidden: { opacity: 0, y: 16 },
  show: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.45,
      ease: "easeOut",
      when: "beforeChildren",
      staggerChildren: 0.08,
    },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 10 },
  show: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.5, ease: "easeOut" },
  },
};

export function FAQ() {
  const { t, i18n } = useTranslation();
  const [activeCategory, setActiveCategory] =
    useState<FaqCategory>("quickStart");
  const [openId, setOpenId] = useState("install");

  const categories: Array<{ key: FaqCategory; label: string }> = useMemo(
    () => [
      { key: "quickStart", label: t("homeFaq.categories.quickStart") },
      { key: "features", label: t("homeFaq.categories.features") },
      {
        key: "troubleshooting",
        label: t("homeFaq.categories.troubleshooting"),
      },
    ],
    [t, i18n.resolvedLanguage],
  );

  const faqData: Record<FaqCategory, FaqItem[]> = useMemo(
    () => ({
      quickStart: [
        {
          id: "install",
          question: t("homeFaq.quickStart.install.q"),
          answer: (
            <>
              <p>{t("homeFaq.quickStart.install.p1")}</p>
              <ul className="mt-2 list-disc space-y-1 pl-5">
                <li>{t("homeFaq.quickStart.install.li1")}</li>
                <li>{t("homeFaq.quickStart.install.li2")}</li>
                <li>{t("homeFaq.quickStart.install.li3")}</li>
                <li>{t("homeFaq.quickStart.install.li4")}</li>
                <li>{t("homeFaq.quickStart.install.li5")}</li>
                <li>{t("homeFaq.quickStart.install.li6")}</li>
              </ul>
              <p className="mt-2">
                {t("homeFaq.quickStart.install.ctaPrefix")}{" "}
                <Link
                  to="/docs/quickstart"
                  className="text-(--color-primary) no-underline transition hover:brightness-110"
                >
                  {t("homeFaq.quickStart.install.ctaLink")}
                </Link>{" "}
                {t("homeFaq.quickStart.install.ctaSuffix")}
              </p>
            </>
          ),
        },
        {
          id: "update",
          question: t("homeFaq.quickStart.update.q"),
          answer: (
            <>
              <p>{t("homeFaq.quickStart.update.p1")}</p>
              <ul className="mt-2 list-disc space-y-1 pl-5">
                <li>{t("homeFaq.quickStart.update.li1")}</li>
                <li>
                  {t("homeFaq.quickStart.update.li2Prefix")}{" "}
                  <code>pip install --upgrade qwenpaw</code>
                </li>
                <li>{t("homeFaq.quickStart.update.li3")}</li>
                <li>{t("homeFaq.quickStart.update.li4")}</li>
                <li>
                  {t("homeFaq.quickStart.update.li5Prefix")}
                  <ul className="mt-1 list-disc space-y-1 pl-5">
                    <li>{t("homeFaq.quickStart.update.li5a")}</li>
                    <li>
                      {t("homeFaq.quickStart.update.li5bPrefix")}{" "}
                      <a
                        href="https://github.com/agentscope-ai/QwenPaw/releases"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-(--color-primary) no-underline transition hover:brightness-110"
                      >
                        {t("homeFaq.quickStart.update.li5bLink")}
                      </a>
                      {t("homeFaq.quickStart.update.li5bSuffix")}
                    </li>
                    <li>{t("homeFaq.quickStart.update.li5c")}</li>
                  </ul>
                </li>
              </ul>
            </>
          ),
        },
        {
          id: "initialize",
          question: t("homeFaq.quickStart.initialize.q"),
          answer: (
            <>
              <p>
                {t("homeFaq.quickStart.initialize.p1")}{" "}
                <code>qwenpaw init --defaults</code>
              </p>
              <p>
                {t("homeFaq.quickStart.initialize.p2")} <code>qwenpaw app</code>
              </p>
              <p className="mt-2">
                {t("homeFaq.quickStart.initialize.p3Prefix")}{" "}
                <code>http://127.0.0.1:8088/</code>
                {t("homeFaq.quickStart.initialize.p3Suffix")}
              </p>
            </>
          ),
        },
        {
          id: "upgrade",
          question: t("homeFaq.quickStart.upgrade.q"),
          answer: (
            <>
              {t("homeFaq.quickStart.upgrade.p1")}{" "}
              <a
                href="https://github.com/agentscope-ai/QwenPaw/releases"
                target="_blank"
                rel="noopener noreferrer"
                className="text-(--color-primary) no-underline transition hover:brightness-110"
              >
                {t("homeFaq.quickStart.upgrade.link")}
              </a>{" "}
              {t("homeFaq.quickStart.upgrade.p2")}
            </>
          ),
        },
      ],
      features: [
        {
          id: "models",
          question: t("homeFaq.features.models.q"),
          answer: (
            <>
              <p>
                {t("homeFaq.features.models.p1Prefix")}{" "}
                <strong>{t("homeFaq.features.models.p1Strong")}</strong>{" "}
                {t("homeFaq.features.models.p1Mid")}{" "}
                <Link
                  to="/docs/models"
                  className="text-(--color-primary) no-underline transition hover:brightness-110"
                >
                  {t("homeFaq.features.models.modelsLink")}
                </Link>{" "}
                {t("homeFaq.features.models.p1Suffix")}
              </p>
              <ul className="mt-2 list-disc space-y-1 pl-5">
                <li>{t("homeFaq.features.models.li1")}</li>
                <li>
                  {t("homeFaq.features.models.li2Prefix")}{" "}
                  <code>llama.cpp</code>, <code>LM Studio</code>,{" "}
                  {t("homeFaq.features.models.li2Suffix")}
                </li>
              </ul>
              <p className="mt-2">{t("homeFaq.features.models.p2")}</p>
              <p className="mt-2">{t("homeFaq.features.models.p3")}</p>
              <p className="mt-2">
                {t("homeFaq.features.models.p4Prefix")}{" "}
                <code>qwenpaw models</code> {t("homeFaq.features.models.p4Mid")}{" "}
                <Link
                  to="/docs/cli#qwenpaw-models"
                  className="text-(--color-primary) no-underline transition hover:brightness-110"
                >
                  {t("homeFaq.features.models.cliLink")}
                </Link>
                {t("homeFaq.features.models.p4Suffix")}
              </p>
            </>
          ),
        },
        {
          id: "jobs",
          question: t("homeFaq.features.jobs.q"),
          answer: t("homeFaq.features.jobs.a"),
        },
        {
          id: "skills",
          question: t("homeFaq.features.skills.q"),
          answer: (
            <p>
              {t("homeFaq.features.skills.p1Prefix")}{" "}
              <strong>{t("homeFaq.features.skills.p1Strong")}</strong>{" "}
              {t("homeFaq.features.skills.p1Mid")}{" "}
              <Link
                to="/docs/skills"
                className="text-(--color-primary) no-underline transition hover:brightness-110"
              >
                {t("homeFaq.features.skills.link")}
              </Link>
              {t("homeFaq.features.skills.p1Suffix")}
            </p>
          ),
        },
        {
          id: "MCP",
          question: t("homeFaq.features.mcp.q"),
          answer: (
            <p>
              {t("homeFaq.features.mcp.p1Prefix")}{" "}
              <strong>{t("homeFaq.features.mcp.p1Strong")}</strong>{" "}
              {t("homeFaq.features.mcp.p1Mid")}{" "}
              <Link
                to="/docs/mcp"
                className="text-(--color-primary) no-underline transition hover:brightness-110"
              >
                {t("homeFaq.features.mcp.link")}
              </Link>
              {t("homeFaq.features.mcp.p1Suffix")}
            </p>
          ),
        },
      ],
      troubleshooting: [
        {
          id: "error-401",
          question: t("homeFaq.troubleshooting.error401.q"),
          answer: (
            <>
              <p>{t("homeFaq.troubleshooting.error401.p1")}</p>
              <pre className="mt-2 whitespace-pre-wrap rounded-lg bg-white/60 p-3 text-[12px] leading-relaxed text-(--color-text-secondary)">
                {t("homeFaq.troubleshooting.error401.err")}
              </pre>
              <p className="mt-2">{t("homeFaq.troubleshooting.error401.p2")}</p>
              <ul className="mt-2 list-disc space-y-1 pl-5">
                <li>{t("homeFaq.troubleshooting.error401.li1")}</li>
                <li>
                  {t("homeFaq.troubleshooting.error401.li2Prefix")}
                  <ul className="mt-1 list-disc space-y-1 pl-5">
                    <li>{t("homeFaq.troubleshooting.error401.li2a")}</li>
                    <li>{t("homeFaq.troubleshooting.error401.li2b")}</li>
                    <li>{t("homeFaq.troubleshooting.error401.li2c")}</li>
                  </ul>
                </li>
              </ul>
            </>
          ),
        },
        {
          id: "local-models",
          question: t("homeFaq.troubleshooting.localModels.q"),
          answer: (
            <>
              <p>{t("homeFaq.troubleshooting.localModels.p1")}</p>
              <p className="mt-2">
                {t("homeFaq.troubleshooting.localModels.p2")}
              </p>
              <ul className="mt-2 list-disc space-y-1 pl-5">
                <li>{t("homeFaq.troubleshooting.localModels.li1")}</li>
                <li>{t("homeFaq.troubleshooting.localModels.li2")}</li>
                <li>{t("homeFaq.troubleshooting.localModels.li3")}</li>
                <li>{t("homeFaq.troubleshooting.localModels.li4")}</li>
              </ul>
              <p className="mt-3 font-semibold">
                {t("homeFaq.troubleshooting.localModels.fixTitle")}
              </p>
              <ul className="mt-2 list-disc space-y-1 pl-5">
                <li>{t("homeFaq.troubleshooting.localModels.fix1")}</li>
                <li>{t("homeFaq.troubleshooting.localModels.fix2")}</li>
              </ul>
            </>
          ),
        },
        {
          id: "cron-jobs",
          question: t("homeFaq.troubleshooting.cron.q"),
          answer: (
            <>
              <p>{t("homeFaq.troubleshooting.cron.p1")}</p>
              <ol className="mt-2 list-decimal space-y-1 pl-5">
                <li>{t("homeFaq.troubleshooting.cron.s1")}</li>
                <li>{t("homeFaq.troubleshooting.cron.s2")}</li>
                <li>{t("homeFaq.troubleshooting.cron.s3")}</li>
                <li>{t("homeFaq.troubleshooting.cron.s4")}</li>
                <li>{t("homeFaq.troubleshooting.cron.s5")}</li>
                <li>{t("homeFaq.troubleshooting.cron.s6")}</li>
                <li>{t("homeFaq.troubleshooting.cron.s7")}</li>
              </ol>
            </>
          ),
        },
        {
          id: "help",
          question: t("homeFaq.troubleshooting.help.q"),
          answer: (
            <>
              <p>{t("homeFaq.troubleshooting.help.p1")}</p>
              <ol className="mt-2 list-decimal space-y-1 pl-5">
                <li>
                  {t("homeFaq.troubleshooting.help.s1Prefix")}{" "}
                  <a
                    href="https://qr.dingtalk.com/action/joingroup?code=v1,k1,OmDlBXpjW+I2vWjKDsjvI9dhcXjGZi3bQiojOq3dlDw=&_dt_no_comment=1&origin=11"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-(--color-primary) no-underline transition hover:brightness-110"
                  >
                    {t("homeFaq.troubleshooting.help.dingtalk")}
                  </a>{" "}
                  {t("homeFaq.troubleshooting.help.s1Mid")}{" "}
                  <a
                    href="https://discord.com/invite/eYMpfnkG8h"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-(--color-primary) no-underline transition hover:brightness-110"
                  >
                    {t("homeFaq.troubleshooting.help.discord")}
                  </a>{" "}
                  {t("homeFaq.troubleshooting.help.s1Suffix")}
                </li>
                <li>
                  {t("homeFaq.troubleshooting.help.s2Prefix")}{" "}
                  <a
                    href="https://github.com/agentscope-ai/QwenPaw/issues"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-(--color-primary) no-underline transition hover:brightness-110"
                  >
                    {t("homeFaq.troubleshooting.help.githubIssues")}
                  </a>{" "}
                  {t("homeFaq.troubleshooting.help.s2Mid")}{" "}
                  <code>qwenpaw_query_error_qzbx1mv1.json</code>
                  {t("homeFaq.troubleshooting.help.s2Suffix")}
                </li>
              </ol>
            </>
          ),
        },
      ],
    }),
    [t, i18n.resolvedLanguage],
  );

  const currentFaqs = useMemo(
    () => faqData[activeCategory],
    [activeCategory, faqData],
  );

  return (
    <motion.section
      className="px-4 py-12 md:py-16"
      variants={sectionVariants}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, amount: 0.2 }}
      aria-labelledby="qwenpaw-faq-heading"
    >
      <div className="mx-auto max-w-7xl">
        <div className="grid gap-8 md:grid-cols-[40%_60%] md:gap-12">
          <motion.div variants={itemVariants}>
            <h2 id="qwenpaw-faq-heading" className={sectionStyles.title}>
              {t("homeFaq.title")}
            </h2>
            <p
              className={`${sectionStyles.subtitle} mx-auto mt-3 max-w-2xl px-2 sm:px-0 md:mb-16 md:mt-4`}
            >
              {t("homeFaq.sub")}
            </p>

            <div className="mt-5 flex flex-wrap gap-2 md:mt-6 md:block md:border-l-2 md:border-[#e9dfd6] md:pl-0.5">
              {categories.map((category) => {
                const active = category.key === activeCategory;
                return (
                  <button
                    key={category.key}
                    type="button"
                    onClick={() => {
                      setActiveCategory(category.key);
                      setOpenId(faqData[category.key][0]?.id ?? "");
                    }}
                    className={`relative inline-flex w-fit items-center rounded-full px-3 py-1.5 text-left text-[20px] leading-[1.2] transition md:block md:w-full md:rounded-none md:py-5 md:pl-3 md:pr-0 md:text-[20px] md:leading-[1.05] ${
                      active
                        ? "font-newsreader bg-[rgba(236,146,69,0.12)] text-(--color-primary) md:bg-transparent"
                        : "font-newsreader text-(--color-text)"
                    }`}
                  >
                    {active ? (
                      <span className="absolute bottom-0 -left-1 top-0 hidden w-0.5 bg-(--color-primary) md:block" />
                    ) : null}
                    {category.label}
                  </button>
                );
              })}
            </div>
          </motion.div>

          <motion.div className="md:pt-1" variants={itemVariants}>
            <p className="font-inter mb-5 max-w-[52ch] text-right text-[13px] leading-[1.72] text-(--color-text-tertiary) text-pretty md:mb-16 md:ml-auto md:text-[1rem]">
              {t("homeFaq.intro")}
            </p>

            <div className="space-y-1.5 md:space-y-2">
              {currentFaqs.map((faq) => {
                const isOpen = faq.id === openId;
                return (
                  <div
                    key={faq.id}
                    className={`transition ${
                      isOpen
                        ? "rounded-xl bg-[#f7f3ef]"
                        : "rounded-none bg-transparent"
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => setOpenId(isOpen ? "" : faq.id)}
                      className={`flex w-full items-center justify-between gap-4 text-left ${
                        isOpen
                          ? "px-3.5 pb-1.5 pt-3.5 md:px-5 md:pb-2 md:pt-4"
                          : "px-3.5 py-2.5 md:px-5 md:py-3.5"
                      }`}
                    >
                      <span className="font-newsreader text-[1.5rem] leading-[1.08] text-(--color-text) md:text-[24px]">
                        {faq.question}
                      </span>
                      <span
                        aria-hidden
                        className="font-inter text-[1.5rem] leading-none text-(--color-text) md:text-[1.85rem]"
                      >
                        {isOpen ? "−" : "+"}
                      </span>
                    </button>
                    {isOpen && faq.answer ? (
                      <div className="p-4 md:p-6">
                        <div className="font-inter text-[13px] leading-[1.65] text-(--color-text-secondary) md:text-base">
                          {faq.answer}
                        </div>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </motion.div>
        </div>
      </div>
    </motion.section>
  );
}
