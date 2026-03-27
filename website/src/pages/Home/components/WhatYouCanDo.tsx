import { useMemo, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { useTranslation } from "react-i18next";
import { sectionStyles } from "@/lib/utils";

type UseCaseKey =
  | "social"
  | "creative"
  | "productivity"
  | "research"
  | "assistant";

const CATEGORIES: Array<{
  key: UseCaseKey;
}> = [
  { key: "social" },
  { key: "creative" },
  { key: "productivity" },
  { key: "research" },
  { key: "assistant" },
];

const container = {
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

const item = {
  hidden: { opacity: 0, y: 10 },
  show: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.5, ease: "easeOut" },
  },
};

export function CopawWhatYouCanDo() {
  const { t } = useTranslation();
  const [activeKey, setActiveKey] = useState<UseCaseKey>("social");

  const activeDescription = useMemo(
    () => t(`usecases.${activeKey}.1`),
    [activeKey, t],
  );

  const socialPreview = (
    <div className="overflow-hidden bg-[#f7a157] px-4 pt-4 sm:px-6 sm:pt-6 md:rounded-none md:px-10 md:pt-10">
      <img
        src="/copaw-console.png"
        alt="CoPaw console preview"
        className="block h-55 w-full rounded-t-xl object-cover object-top shadow-[0px_6px_56px_0px_rgba(38,33,29,0.24)] sm:h-75 md:h-full md:rounded-t-2xl"
        loading="lazy"
      />
    </div>
  );

  return (
    <motion.section
      className="px-4 py-16 md:py-24"
      variants={container}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, amount: 0.2 }}
      aria-labelledby="copaw-usecase-heading"
    >
      <div className="mx-auto max-w-7xl">
        <motion.div className="text-center" variants={item}>
          <h2
            id="copaw-usecase-heading"
            className={sectionStyles.title}
          >
            {t("usecases.title")}
          </h2>
          <p className={`${sectionStyles.subtitle} mx-auto mt-3 max-w-2xl px-2 sm:px-0 md:mb-16 md:mt-4`}>
            {t("usecases.sub")}
          </p>
        </motion.div>

        <div className="mt-7 grid gap-5 md:mt-15 md:grid-cols-[minmax(260px,1fr)_minmax(0,1.6fr)] md:items-start md:gap-6">
          <div className="p-1.5 md:p-3">
            {CATEGORIES.map(({ key }) => {
              const active = key === activeKey;
              return (
                <div key={key}>
                  <button
                    type="button"
                    onClick={() => setActiveKey(key)}
                    className="group relative w-full py-4 text-left md:py-5"
                  >
                    {/* Hover 背景 */}
                    {!active && (
                      <span
                        className="pointer-events-none absolute left-10 right-0 top-0 z-0 h-full bg-transparent transition-colors duration-200 group-hover:bg-[#FFF7F0] md:left-11"
                        aria-hidden
                      />
                    )}
                    <span
                      className="absolute bottom-0 left-10 right-0 h-px bg-[#FDE8D7] md:left-11"
                      aria-hidden
                    />
                    <div className="relative z-10 flex items-start gap-2.5 px-1.5 md:gap-3 md:px-2">
                      <div className="mt-1 h-6 w-6 shrink-0 md:mt-0.5 md:h-7 md:w-7">
                        {active && (
                          <motion.img
                            layoutId="copaw-usecase-active-logo"
                            src="/copaw-logo.svg"
                            alt=""
                            aria-hidden
                            className="h-6 w-6 object-contain md:h-7 md:w-7"
                            transition={{
                              type: "tween",
                              duration: 0.5,
                              ease: [0.25, 0.46, 0.45, 0.94],
                            }}
                          />
                        )}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div
                          className={`font-newsreader text-[1.85rem] leading-[1.05] sm:text-[1.95rem] md:text-[28px] ${
                            active
                              ? "text-(--color-text)"
                              : "text-(--color-text-tertiary) transition-colors duration-200 group-hover:text-(--color-text)"
                          }`}
                        >
                          {t(`usecases.category.${key}`)}
                        </div>
                        <div className="overflow-hidden">
                          <AnimatePresence initial={false} mode="sync">
                            {active && (
                              <motion.p
                                key={`${key}-desc`}
                                initial={{ opacity: 1, height: 0, marginTop: 0 }}
                                exit={{
                                  opacity: 0,
                                  scale: 0.8,
                                  height: 0,
                                  marginTop: 0,
                                }}
                                animate={{ opacity: 1, height: "auto", marginTop: 8 }}
                                transition={{
                                  duration: 0.5,
                                  ease: "easeOut",
                                }}
                                className="font-inter origin-top-left pr-1 text-sm leading-[1.55] text-(--color-text-tertiary)"
                              >
                                {activeDescription}
                              </motion.p>
                            )}
                          </AnimatePresence>
                        </div>
                      </div>
                    </div>
                  </button>

                  {/* Mobile: only show preview under social */}
                  {key === "social" && active ? (
                    <div className="mt-3 md:hidden">{socialPreview}</div>
                  ) : null}
                </div>
              );
            })}
          </div>

          {/* Desktop: right panel switches with active category (only social has content for now) */}
          <div className="hidden md:block">
            {activeKey === "social" ? socialPreview : socialPreview}
          </div>
        </div>
      </div>
    </motion.section>
  );
}
