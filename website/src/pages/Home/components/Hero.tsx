import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { motion } from "motion/react";
import { DottedlinedownArrowIcon, PathIcon } from "@/components/Icon";
import ShinyText from "@/components/ShinyText";

const container = {
  hidden: { opacity: 0, y: 14 },
  visible: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.8,
      ease: "easeOut",
      when: "beforeChildren",
      staggerChildren: 0.2,
    },
  },
};

export function CopawHero() {
  const { t, i18n } = useTranslation();
  const isZh = i18n.resolvedLanguage === "zh";
  const [isHovered, setIsHovered] = useState(false);
  const [showIdle, setShowIdle] = useState(false);
  const [idlePlayedOnce, setIdlePlayedOnce] = useState(false);
  const [startGifLoaded, setStartGifLoaded] = useState(false);

  // After start gif plays once, switch to idle
  useEffect(() => {
    if (!startGifLoaded) return;
    const timer = setTimeout(() => {
      setShowIdle(true);
    }, 1600);
    return () => clearTimeout(timer);
  }, [startGifLoaded]);

  // Preload images to prevent flash on switch
  useEffect(() => {
    const preloadImages = [
      "https://img.alicdn.com/imgextra/i1/O1CN016cb70x1KlwOGcvRgb_!!6000000001205-1-tps-120-120.gif",
      "https://img.alicdn.com/imgextra/i1/O1CN01UzhqBc1tym2X8dhl6_!!6000000005971-2-tps-120-120.png",
    ];
    preloadImages.forEach((src) => {
      const img = new Image();
      img.src = src;
    });
  }, []);

  // After idle plays once, switch to static image
  useEffect(() => {
    if (!showIdle || idlePlayedOnce) return;
    const timer = setTimeout(() => {
      setIdlePlayedOnce(true);
    }, 1000); // idle gif duration
    return () => clearTimeout(timer);
  }, [showIdle, idlePlayedOnce]);

  const scrollToQuickStart = () => {
    const section = document.getElementById("copaw-quickstart");
    if (!section) return;
    section.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const mascotSrc = !showIdle
    ? "https://img.alicdn.com/imgextra/i4/O1CN01nMDfdp23mXcSGecsm_!!6000000007298-1-tps-120-120.gif"
    : isHovered || !idlePlayedOnce
    ? "https://img.alicdn.com/imgextra/i1/O1CN016cb70x1KlwOGcvRgb_!!6000000001205-1-tps-120-120.gif"
    : "https://img.alicdn.com/imgextra/i1/O1CN01UzhqBc1tym2X8dhl6_!!6000000005971-2-tps-120-120.png";

  return (
    <>
      <motion.section
        className="relative text-center"
        aria-labelledby="copaw-hero-heading"
        variants={container}
        initial="hidden"
        animate="visible"
      >
        <div className="mx-auto max-w-7xl px-4 pt-10">
          <div className="mx-auto mb-5 inline-flex box-border items-center gap-2 rounded-full border border-(--border) bg-(--surface) px-4 py-1.5 text-sm text-(--color-text-secondary) sm:mb-6">
            <PathIcon size={16} />
            <ShinyText
              text={t("hero.releaseNote")}
              speed={1.8}
              delay={0}
              color="#9c9b9a"
              shineColor="#cdcdcc"
              spread={120}
              direction="left"
              yoyo={false}
              pauseOnHover={false}
              disabled={false}
            />
          </div>
          <h1
            id="copaw-hero-heading"
            className="font-newsreader font-semibold leading-[1.1] tracking-[-0.02em] text-(--color-text) sm:leading-[1.08] text-[32px] md:text-[48px] md:leading-[1.06]"
          >
            <span className="font-newsreader font-medium whitespace-pre-wrap">
              {t("hero.titleleft")}
            </span>
            <span
              className="mx-2 inline-flex -translate-y-[0.08em] items-center align-middle select-none sm:-translate-y-[0.1em] cursor-pointer"
              onMouseEnter={() => setIsHovered(true)}
              onMouseLeave={() => setIsHovered(false)}
            >
              <img
                src={mascotSrc}
                alt=""
                className="h-11 w-11 object-contain sm:h-12 sm:w-12 md:h-18 md:w-18"
                onLoad={() => {
                  if (!showIdle) setStartGifLoaded(true);
                }}
                aria-hidden
              />
            </span>
            <span
              className={`font-newsreader relative top-[0.02em] inline-block italic leading-[0.9] ${
                isZh ? "font-medium" : "font-normal"
              }`}
            >
              <span className="relative">
                {t("hero.titleright")}
                <span
                  className="absolute bottom-0 left-0 h-[2px] w-0 animate-[copaw-hero-trim-path_0.8s_ease-out_forwards] [animation-delay:1s]"
                  style={{
                    background:
                      "repeating-linear-gradient(to right, var(--color-primary) 0 8px, transparent 8px 16px)",
                  }}
                />
              </span>
            </span>
            <span className="mt-1 block font-newsreader text-[0.92em] font-medium text-(--color-text-secondary) sm:mt-1.5 sm:text-[1em]">
              {t("hero.slogan")}
            </span>
          </h1>
          <p className="font-inter mx-auto mt-3 max-w-3xl px-2 text-[14px] font-medium leading-[1.55] text-(--color-text-tertiary) sm:mt-4 sm:px-0 sm:text-[15px] md:mt-5 md:text-[16px]">
            {t("hero.sub")}
            <br />
            {t("hero.sub1")}
          </p>

          <div className="mt-7 flex w-full flex-col items-center justify-center gap-2.5 sm:mt-8 sm:w-auto sm:flex-row sm:gap-3">
            <button
              type="button"
              onClick={scrollToQuickStart}
              className="inline-flex h-11 w-full max-w-60 items-center justify-center gap-1.5 rounded-lg bg-(--color-primary) px-4 text-[15px] font-normal text-(--color-text) ] transition hover:brightness-105 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-primary) sm:h-10 sm:w-auto sm:max-w-none"
            >
              <DottedlinedownArrowIcon />
              <span>{t("hero.quickStart")}</span>
            </button>
          </div>

          <motion.div
            className="relative mt-10 h-56 overflow-hidden sm:h-90 md:mt-12 md:h-150"
            initial={{ opacity: 0, filter: "blur(10px)" }}
            whileInView={{ opacity: 1, scale: 1, filter: "blur(0px)" }}
            viewport={{ once: true, amount: 0.35 }}
            transition={{ duration: 1.15, ease: "easeOut" }}
          >
            <img
              src="https://img.alicdn.com/imgextra/i1/O1CN01omYMId1zLHaFKHulx_!!6000000006697-2-tps-2936-1650.png"
              alt=""
              className="absolute inset-0 h-full w-full object-cover"
              aria-hidden
              loading="lazy"
            />
            <motion.div
              className="relative z-10 flex h-full flex-col justify-end overflow-hidden p-4 pb-0 md:p-16 md:pb-0"
              initial={{ opacity: 0, y: 56, scale: 0.95, filter: "blur(6px)" }}
              whileInView={{ opacity: 1, y: 0, scale: 1, filter: "blur(0px)" }}
              viewport={{ once: true, amount: 0.35 }}
              transition={{
                duration: 1.05,
                delay: 0.25,
                ease: [0.22, 1, 0.36, 1],
              }}
            >
              <img
                src="https://img.alicdn.com/imgextra/i1/O1CN01cIH6fF1g0h4zuKzOZ_!!6000000004080-2-tps-2270-1419.png"
                alt="CoPaw console preview"
                className="block h-auto max-h-full w-full rounded-t-[8px] object-top shadow-[0px_6px_56px_0px_rgba(38,33,29,0.24)] md:h-full md:object-cover"
                loading="lazy"
              />
            </motion.div>
          </motion.div>
        </div>
      </motion.section>
    </>
  );
}
