import { Link } from "react-router-dom";
import {  SquareTerminal } from "lucide-react";
import { useTranslation } from "react-i18next";
import { motion } from "motion/react";
import DottedlinedownArrowIcon from "@/components/Icon/IncentivesIcon";

type CopawHeroProps = {
  pipInstallTo: string;
};

const container = {
  hidden: { opacity: 0, y: 14 },
  visible: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.45,
      ease: "easeOut",
      when: "beforeChildren",
      staggerChildren: 0.1,
    },
  },
};

const item = {
  hidden: { opacity: 0, y: 10 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.35, ease: "easeOut" },
  },
};

function isExternalHref(to: string) {
  return /^https?:\/\//i.test(to);
}

export function CopawHero({ pipInstallTo }: CopawHeroProps) {
  const { t } = useTranslation();
  const scrollToQuickStart = () => {
    const section = document.getElementById("copaw-quickstart");
    if (!section) return;
    section.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  return (
    <motion.section
      className="relative text-center"
      aria-labelledby="copaw-hero-heading"
      variants={container}
      initial="hidden"
      animate="visible"
    >
      <div className="mx-auto max-w-7xl px-4 pt-19">
        <motion.h1
          id="copaw-hero-heading"
          className="font-newsreader font-semibold leading-[1.1] tracking-[-0.02em] text-(--color-text) sm:leading-[1.08] text-[32px] md:text-[52px] md:leading-[1.06]"
          variants={item}
        >
          <span className="font-newsreader font-medium whitespace-pre-wrap">
            {t("hero.titleleft")}
          </span>
          <span className="mx-0.5 inline-flex -translate-y-[0.08em] items-center align-middle select-none sm:-translate-y-[0.1em]">
            <img
              src="/copaw-slogan.png"
              alt=""
              className="h-11 w-11 object-contain sm:h-12 sm:w-12 md:h-20 md:w-20"
              aria-hidden
            />
          </span>
          <span
            className="font-newsreader relative top-[0.02em] inline-block font-normal italic border-b-2 border-dashed border-[#f4a460] leading-[0.9]"
            style={{ borderColor: "var(--color-primary)" }}
          >
            {t("hero.titleright")}
          </span>
          <span className="mt-1 block font-newsreader text-[0.92em] font-medium text-(--color-text-secondary) sm:mt-1.5 sm:text-[1em]">
            {t("hero.slogan")}
          </span>
        </motion.h1>
        <motion.p
          className="font-inter mx-auto mt-5 max-w-2xl px-2 text-[14px] font-medium leading-[1.55] text-(--color-text-tertiary) sm:mt-6 sm:px-0 sm:text-[15px] md:mt-7 md:text-[16px]"
          variants={item}
        >
          {t("hero.sub")}
        </motion.p>

        <motion.div
          className="mt-7 flex w-full flex-col items-center justify-center gap-2.5 sm:mt-8 sm:w-auto sm:flex-row sm:gap-3"
          variants={item}
        >
          <button
            type="button"
            onClick={scrollToQuickStart}
            className="inline-flex h-11 w-full max-w-60 items-center justify-center gap-1.5 rounded-lg bg-(--color-primary) px-4 text-[15px] font-semibold text-white shadow-[0_1px_2px_rgba(0,0,0,0.12)] transition hover:brightness-105 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-primary) sm:h-10 sm:w-auto sm:max-w-none"
          >
            <DottedlinedownArrowIcon />
            <span>{t("hero.quickStart")}</span>
          </button>
          {isExternalHref(pipInstallTo) ? (
            <a
              href={pipInstallTo}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex h-11 w-full max-w-60 items-center justify-center gap-1.5 rounded-lg border border-[#d9d9d9] bg-white px-4 text-[15px] font-semibold text-[#555] transition hover:bg-neutral-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-neutral-400 sm:h-10 sm:w-auto sm:max-w-none"
            >
              <SquareTerminal
                className="h-4 w-4 shrink-0"
                strokeWidth={2}
                aria-hidden
              />
              <span>{t("hero.pipInstall")}</span>
            </a>
          ) : (
            <Link
              to={pipInstallTo}
              className="inline-flex h-11 w-full max-w-60 items-center justify-center gap-1.5 rounded-lg border border-[#d9d9d9] bg-white px-4 text-[15px] font-semibold text-[#555] transition hover:bg-neutral-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-neutral-400 sm:h-10 sm:w-auto sm:max-w-none"
            >
              <SquareTerminal
                className="h-4 w-4 shrink-0"
                strokeWidth={2}
                aria-hidden
              />
              <span>{t("hero.pipInstall")}</span>
            </Link>
          )}
        </motion.div>

        <motion.div
          className="relative mt-10 h-90 overflow-hidden md:mt-12 md:h-150"
          variants={item}
        >
          <motion.img
            src="/copaw-bg.png"
            alt=""
            className="absolute inset-0 h-full w-full object-cover"
            aria-hidden
            loading="lazy"
            initial={{ opacity: 0, scale: 1.06, filter: "blur(10px)" }}
            whileInView={{ opacity: 1, scale: 1, filter: "blur(0px)" }}
            viewport={{ once: true, amount: 0.35 }}
            transition={{ duration: 1.15, ease: "easeOut" }}
          />
          <motion.div
            className="relative z-10 h-full overflow-hidden p-4 pb-0 md:p-16 md:pb-0"
            initial={{ opacity: 0, y: 56, scale: 0.95, filter: "blur(6px)" }}
            whileInView={{ opacity: 1, y: 0, scale: 1, filter: "blur(0px)" }}
            viewport={{ once: true, amount: 0.35 }}
            transition={{
              duration: 1.05,
              delay: 0.25,
              ease: [0.22, 1, 0.36, 1],
            }}
          >
            <motion.img
              src="/copaw-console.png"
              alt="CoPaw console preview"
              className="block h-full w-full rounded-t-2xl object-cover object-top shadow-[0px_6px_56px_0px_rgba(38,33,29,0.24)]"
              loading="lazy"
              initial={{ opacity: 0, y: 32 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, amount: 0.35 }}
              transition={{
                duration: 0.95,
                delay: 0.42,
                ease: [0.22, 1, 0.36, 1],
              }}
            />
          </motion.div>
        </motion.div>
      </div>
    </motion.section>
  );
}
