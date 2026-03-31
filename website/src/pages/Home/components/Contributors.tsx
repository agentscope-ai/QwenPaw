import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { motion } from "motion/react";

type Contributor = {
  login: string;
  avatar_url: string;
  html_url: string;
};

const ITEMS_PER_PAGE = 54;

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

export function CopawContributors() {
  const { t } = useTranslation();
  const [contributors, setContributors] = useState<Contributor[]>([]);
  const [page, setPage] = useState(1);

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

  const totalPages = Math.max(
    1,
    Math.ceil(contributors.length / ITEMS_PER_PAGE),
  );
  const currentPage = Math.min(page, totalPages);

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  const pageItems = useMemo(() => {
    const start = (currentPage - 1) * ITEMS_PER_PAGE;
    return contributors.slice(start, start + ITEMS_PER_PAGE);
  }, [contributors, currentPage]);

  return (
    <>
      <motion.section
        id="contributor"
        className="scroll-mt-24 px-4 py-16 md:py-20"
        variants={sectionVariants}
        initial="hidden"
        whileInView="show"
        viewport={{ once: true, amount: 0.2 }}
        aria-labelledby="copaw-contributors-heading"
      >
        <div className="mx-auto max-w-7xl text-center">
          <motion.h2
            id="copaw-contributors-heading"
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
                className="pointer-events-none absolute left-1/2 top-full w-[120%] max-w-none -translate-x-1/2 -translate-y-1.5 select-none md:w-[128%] md:-translate-y-5"
                loading="lazy"
              />
              <img
                src="/communityIcon/contributor1.svg"
                alt=""
                aria-hidden
                className="pointer-events-none absolute -right-8 -top-4 h-9 w-9 select-none md:-right-5 md:-top-10 md:h-16 md:w-16"
                loading="lazy"
              />
              <img
                src="/communityIcon/contributor2.svg"
                alt=""
                aria-hidden
                className="pointer-events-none absolute -right-12 -top-2 h-9 w-9 -rotate-12 select-none md:-right-13 md:-top-5 md:h-16 md:w-16"
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

          <motion.div
            className="mt-12 grid grid-cols-6 gap-x-2 gap-y-6 sm:grid-cols-8 md:grid-cols-12 lg:grid-cols-18"
            variants={itemVariants}
          >
            {pageItems.map((contributor) => (
              <a
                key={contributor.login}
                href={contributor.html_url}
                target="_blank"
                rel="noopener noreferrer"
                className="group flex min-w-0 flex-col items-center gap-1.5"
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
            ))}
          </motion.div>

          <motion.div
            className="mt-6 flex items-center justify-center gap-4"
            variants={itemVariants}
          >
            <button
              type="button"
              onClick={() => setPage((prev) => Math.max(1, prev - 1))}
              disabled={currentPage <= 1}
              className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-[#ece2d9] text-(--color-text-tertiary) transition hover:bg-[#f5efea] disabled:cursor-not-allowed disabled:opacity-40"
              aria-label={t("contributors.prev")}
            >
              <ChevronLeft size={15} />
            </button>
            <span className="font-inter text-xs tracking-[0.12em] text-(--color-text-secondary)">
              {String(currentPage).padStart(2, "0")}
            </span>
            <button
              type="button"
              onClick={() => setPage((prev) => Math.min(totalPages, prev + 1))}
              disabled={currentPage >= totalPages}
              className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-[#ece2d9] text-(--color-text-tertiary) transition hover:bg-[#f5efea] disabled:cursor-not-allowed disabled:opacity-40"
              aria-label={t("contributors.next")}
            >
              <ChevronRight size={15} />
            </button>
          </motion.div>

          <div
            className="pointer-events-none relative left-1/2 mt-10 h-px w-screen -translate-x-1/2 animate-[copaw-dash-move-right_1s_linear_infinite]"
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
                href="https://github.com/agentscope-ai/CoPaw"
                target="_blank"
                rel="noopener noreferrer"
                className="text-(--color-primary) ml-1"
              >
                agentscope-ai/CoPaw
              </a>
              .
            </p>
          </motion.div>
        </div>
      </motion.section>
    </>
  );
}
