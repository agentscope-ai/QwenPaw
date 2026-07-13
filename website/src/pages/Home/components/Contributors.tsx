import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { motion } from "motion/react";

type Contributor = {
  login: string;
  avatar_url: string;
  html_url: string;
};

const ROW_COUNT = 3;
const ROW_DIRECTIONS = [
  "qwenpaw-channels-marquee-left",
  "qwenpaw-channels-marquee-right",
  "qwenpaw-channels-marquee-left",
] as const;

/** Calibrated for w-20 items: ~41 items/row at 121 contributors ≈ 80s per cycle. */
const REFERENCE_ITEMS_PER_ROW = 41;
const BASE_CYCLE_DURATION_SEC = 80;
const MIN_CYCLE_DURATION_SEC = 40;

/** Keep pixels/sec stable as contributor count grows (duration scales with row length). */
function getMarqueeDurationSec(itemCount: number): number {
  if (itemCount <= 0) return BASE_CYCLE_DURATION_SEC;
  const scaled =
    BASE_CYCLE_DURATION_SEC * (itemCount / REFERENCE_ITEMS_PER_ROW);
  return Math.max(MIN_CYCLE_DURATION_SEC, scaled);
}

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

function ContributorItem({ contributor }: { contributor: Contributor }) {
  return (
    <a
      href={contributor.html_url}
      target="_blank"
      rel="noopener noreferrer"
      className="group flex w-20 shrink-0 flex-col items-center gap-1.5"
      title={contributor.login}
    >
      <img
        src={contributor.avatar_url}
        alt={contributor.login}
        className="h-11 w-11 rounded-full object-cover ring-1 ring-black/6 shadow-[0_1px_2px_rgba(0,0,0,0.06)] transition duration-250 ease-out group-hover:scale-112"
        loading="lazy"
      />
      <span className="font-inter max-w-full truncate text-[11px] text-(--color-text-tertiary)">
        {contributor.login}
      </span>
    </a>
  );
}

export function Contributors() {
  const { t, i18n } = useTranslation();
  const isZh = i18n.language?.startsWith("zh");
  const [contributors, setContributors] = useState<Contributor[]>([]);
  const [hoveredRow, setHoveredRow] = useState<number | null>(null);

  useEffect(() => {
    let canceled = false;
    async function loadContributors() {
      try {
        const response = await fetch("/contributors_data.json");
        if (!response.ok) return;
        const data = (await response.json()) as Contributor[];
        if (canceled) return;
        const sorted = [...data].sort((a, b) =>
          a.login.localeCompare(b.login, "en", { sensitivity: "base" }),
        );
        setContributors(sorted);
      } catch {
        if (!canceled) setContributors([]);
      }
    }
    void loadContributors();
    return () => {
      canceled = true;
    };
  }, []);

  const rows = useMemo(() => {
    const result: Contributor[][] = [];
    for (let i = 0; i < ROW_COUNT; i++) {
      result.push(contributors.filter((_, idx) => idx % ROW_COUNT === i));
    }
    return result;
  }, [contributors]);
  const handleRowEnter = useCallback((idx: number) => setHoveredRow(idx), []);
  const handleRowLeave = useCallback(() => setHoveredRow(null), []);
  return (
    <>
      <motion.section
        id="contributor"
        className="scroll-mt-24 px-4 py-16 md:py-20"
        variants={sectionVariants}
        initial="hidden"
        whileInView="show"
        viewport={{ once: true, amount: 0.2 }}
        aria-labelledby="qwenpaw-contributors-heading"
      >
        <div className="mx-auto max-w-7xl text-center">
          <motion.h2
            id="qwenpaw-contributors-heading"
            className="font-newsreader text-3xl font-semibold leading-[1.2] text-(--color-text) md:text-4xl"
            variants={itemVariants}
          >
            {t("contributors.titlePrefix")}{" "}
            <span className="relative inline-block">
              <span
                className="font-newsreader inline-block"
                style={{ borderColor: "var(--color-primary)" }}
              >
                {t("contributors.titleHighlight")}
              </span>
              <img
                src="/communityIcon/path.svg"
                alt=""
                aria-hidden
                className={`pointer-events-none absolute left-1/2 top-full w-[120%] max-w-none -translate-x-1/2 -translate-y-1.5 select-none md:w-[128%] ${
                  isZh ? "md:-translate-y-2" : "md:-translate-y-5"
                }`}
                loading="lazy"
              />
              <img
                src="/communityIcon/contributor1.svg"
                alt=""
                aria-hidden
                className={`pointer-events-none absolute -right-8 -top-4 h-9 w-9 select-none md:-right-5 md:h-16 md:w-16 ${
                  isZh ? "md:-top-14" : "md:-top-11"
                }`}
                loading="lazy"
              />
              <img
                src="/communityIcon/contributor2.svg"
                alt=""
                aria-hidden
                className={`pointer-events-none absolute -right-12 -top-2 h-9 w-9 -rotate-12 select-none md:-right-13 md:h-16 md:w-16 ${
                  isZh ? "md:-top-9" : "md:-top-6"
                }`}
                loading="lazy"
              />
            </span>
          </motion.h2>

          <motion.p
            className="font-inter mx-auto mt-3 max-w-2xl text-sm leading-relaxed text-(--color-text-tertiary) md:text-base"
            variants={itemVariants}
          >
            {t("contributors.sub")}
          </motion.p>
        </div>

        <motion.div className="relative mt-12 w-full" variants={itemVariants}>
          {rows.map((row, rowIdx) => {
            if (row.length === 0) return null;
            const durationSec = getMarqueeDurationSec(row.length);
            return (
              <div
                key={rowIdx}
                className={`${rowIdx > 0 ? "mt-4" : ""} overflow-hidden`}
                onMouseEnter={() => handleRowEnter(rowIdx)}
                onMouseLeave={handleRowLeave}
              >
                <div
                  className="inline-flex w-max items-center whitespace-nowrap py-1 will-change-transform"
                  style={{
                    animation: `${ROW_DIRECTIONS[rowIdx]} ${durationSec}s linear infinite`,
                    animationPlayState:
                      hoveredRow === rowIdx ? "paused" : "running",
                  }}
                >
                  {[...row, ...row].map((contributor, idx) => (
                    <ContributorItem
                      key={`${contributor.login}-${idx}`}
                      contributor={contributor}
                    />
                  ))}
                </div>
              </div>
            );
          })}

          {/* Fade edges */}
          <div className="pointer-events-none absolute inset-y-0 left-0 w-24 bg-linear-to-r from-(--bg) to-transparent md:w-32" />
          <div className="pointer-events-none absolute inset-y-0 right-0 w-24 bg-linear-to-l from-(--bg) to-transparent md:w-32" />
        </motion.div>

        <div className="mx-auto max-w-7xl text-center">
          <div
            className="pointer-events-none relative left-1/2 mt-10 h-px w-screen -translate-x-1/2 animate-[qwenpaw-dash-move-right_1s_linear_infinite]"
            style={{
              background:
                "repeating-linear-gradient(to right, rgba(255,157,77,0.45) 0 8px, transparent 8px 16px)",
              backgroundSize: "16px 100%",
            }}
          />

          <motion.div
            className="font-inter mx-auto mt-12 max-w-3xl space-y-4 text-sm text-(--color-text-tertiary) md:text-base"
            variants={itemVariants}
          >
            <p>
              {t("contributors.noteLine1Prefix")}
              <a
                href="/docs/community/"
                className="text-(--color-primary) ml-1"
              >
                {t("contributors.contactUs")}
              </a>
              {t("contributors.noteLine1Suffix")}
            </p>
            <p>
              {t("contributors.noteLine2Prefix")}
              <a
                href="https://github.com/agentscope-ai/QwenPaw"
                target="_blank"
                rel="noopener noreferrer"
                className="text-(--color-primary) ml-1"
              >
                agentscope-ai/QwenPaw
              </a>
              .
            </p>
          </motion.div>
        </div>
      </motion.section>
    </>
  );
}
