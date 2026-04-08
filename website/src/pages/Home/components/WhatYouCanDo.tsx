import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { useTranslation } from "react-i18next";
import { sectionStyles } from "@/lib/utils";

type UseCaseKey = "social" | "creative" | "productivity" | "research";

const CATEGORY_CONFIG: Array<{
  key: UseCaseKey;
  background: string;
  preview: string;
}> = [
  {
    key: "social",
    background:
      "https://img.alicdn.com/imgextra/i4/O1CN01tdSfuK1X2DrN462ga_!!6000000002865-2-tps-1578-946.png",
    preview:
      "https://img.alicdn.com/imgextra/i2/O1CN01EfhcLH1zgoCNkLp8g_!!6000000006744-2-tps-1362-894.png",
  },
  {
    key: "creative",
    background:
      "https://img.alicdn.com/imgextra/i3/O1CN010T7jhC1LptQKwxNGm_!!6000000001349-2-tps-2114-1180.png",
    preview:
      "https://img.alicdn.com/imgextra/i2/O1CN01orpWim1OyXkfeSJ2b_!!6000000001774-2-tps-1362-894.png",
  },
  {
    key: "productivity",
    background:
      "https://img.alicdn.com/imgextra/i3/O1CN01SVXYZd1a2Af7uEY94_!!6000000003271-2-tps-1874-1046.png",
    preview:
      "https://img.alicdn.com/imgextra/i2/O1CN01uCK9RI1ciQQtihtsi_!!6000000003634-2-tps-1362-894.png",
  },
  {
    key: "research",
    background:
      "https://img.alicdn.com/imgextra/i3/O1CN01oybwPf1vKaWII7bmm_!!6000000006154-2-tps-1962-1096.png",
    preview:
      "https://img.alicdn.com/imgextra/i1/O1CN018Vqtpf1PvARqdLsr7_!!6000000001902-2-tps-1362-894.png",
  },
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

  const renderPreview = (key: string) => {
    const active =
      CATEGORY_CONFIG.find((cat) => cat.key === key) ?? CATEGORY_CONFIG[0];
    return (
      <motion.div
        key={`preview-${key}`}
        className="relative flex flex-col overflow-hidden h-[200px] sm:h-[380px]"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.3 }}
      >
        <motion.div
          key={`${active.key}-bg`}
          className="absolute inset-0"
          initial={{ opacity: 0, scale: 1.04 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 1.15, ease: "easeOut" }}
        >
          <img
            src={active.background}
            alt=""
            aria-hidden
            loading="lazy"
            className="h-full w-full object-cover object-bottom opacity-90"
          />
        </motion.div>
        <motion.div
          key={`${active.key}-frame`}
          className="relative z-10 -mb-[18px] overflow-hidden p-4 pb-0 md:p-10 md:pb-0"
          initial={{
            opacity: 0,
            y: 56,
          }}
          animate={{
            opacity: 1,
            y: 0,
          }}
          transition={{
            duration: 1.05,
            delay: 0.1,
            ease: [0.22, 1, 0.36, 1],
          }}
        >
          <motion.div
            key={`${active.key}-preview`}
            className="w-full"
            initial={{ opacity: 0, y: 32 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              duration: 0.95,
              delay: 0.2,
              ease: [0.22, 1, 0.36, 1],
            }}
          >
            <img
              src={active.preview}
              alt=""
              aria-hidden
              className="block w-full object-cover object-top shadow-[0px_6px_56px_0px_rgba(38,33,29,0.24)] rounded-[8px]"
              loading="lazy"
            />
          </motion.div>
        </motion.div>
      </motion.div>
    );
  };

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
          <h2 id="copaw-usecase-heading" className={sectionStyles.title}>
            {t("usecases.title")}
          </h2>
          <p
            className={`${sectionStyles.subtitle} mx-auto mt-3 max-w-2xl px-2 sm:px-0 md:mb-16 md:mt-4`}
          >
            {t("usecases.sub")}
          </p>
        </motion.div>

        <div className="mt-7 grid gap-5 md:mt-15 md:grid-cols-[minmax(260px,1fr)_minmax(0,1.6fr)] md:items-start md:gap-6">
          <div className="p-1.5 md:p-3">
            {CATEGORY_CONFIG.map(({ key }) => {
              const active = key === activeKey;
              const title = t(`usecases.categories.${key}.title`);
              const description = t(`usecases.categories.${key}.description`);
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
                            src="https://img.alicdn.com/imgextra/i4/O1CN01vcAthP1tSFv3dB8Bd_!!6000000005900-55-tps-29-29.svg"
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
                          {title}
                        </div>
                        <div className="overflow-hidden">
                          <AnimatePresence initial={false} mode="sync">
                            {active && (
                              <motion.p
                                key={`${key}-desc`}
                                initial={{
                                  opacity: 1,
                                  height: 0,
                                  marginTop: 0,
                                }}
                                exit={{
                                  opacity: 0,
                                  scale: 0.8,
                                  height: 0,
                                  marginTop: 0,
                                }}
                                animate={{
                                  opacity: 1,
                                  height: "auto",
                                  marginTop: 8,
                                }}
                                transition={{
                                  duration: 0.5,
                                  ease: "easeOut",
                                }}
                                className="font-inter origin-top-left pr-1 text-sm leading-[1.55] break-words text-(--color-text-tertiary)"
                              >
                                {description}
                              </motion.p>
                            )}
                          </AnimatePresence>
                        </div>
                      </div>
                    </div>
                  </button>

                  {/* Mobile: show active preview under item */}
                  {active ? (
                    <div key={key} className="mt-3 md:hidden">
                      {renderPreview(key)}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>

          {/* Desktop: right panel switches with active category */}
          <div className="hidden md:block">{renderPreview(activeKey)}</div>
        </div>
      </div>
    </motion.section>
  );
}
