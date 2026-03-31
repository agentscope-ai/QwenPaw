import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { motion } from "motion/react";
import { DottedlinedownArrowIcon } from "@/components/Icon";

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

const item = {
  hidden: { opacity: 0, y: 10 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.6, ease: "easeOut" },
  },
};

export function CopawHero() {
  const { t } = useTranslation();
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
      "/copaw-slogan-idle.gif",
      "/copaw-slogan-idle-001.png",
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
    ? "/copaw-slogan-start.gif"
    : isHovered || !idlePlayedOnce
    ? "/copaw-slogan-idle.gif"
    : "/copaw-slogan-idle-001.png";

  return (
    <>
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
            className="font-newsreader font-semibold leading-[1.1] tracking-[-0.02em] text-(--color-text) sm:leading-[1.08] text-[32px] md:text-[48px] md:leading-[1.06]"
            variants={item}
          >
            <span className="font-newsreader font-medium whitespace-pre-wrap">
              {t("hero.titleleft")}
            </span>
            <span
              className="ml-4 mr-0 inline-flex -translate-y-[0.08em] items-center align-middle select-none sm:-translate-y-[0.1em] cursor-pointer"
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
            <span className="font-newsreader relative top-[0.02em] inline-block font-normal italic leading-[0.9]">
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
          </motion.h1>
          <motion.p
            className="font-inter mx-auto mt-3 max-w-2xl px-2 text-[14px] font-medium leading-[1.55] text-(--color-text-tertiary) sm:mt-4 sm:px-0 sm:text-[15px] md:mt-5 md:text-[16px]"
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
              className="inline-flex h-11 w-full max-w-60 items-center justify-center gap-1.5 rounded-lg bg-(--color-primary) px-4 text-[15px] font-normal text-(--color-text) ] transition hover:brightness-105 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-primary) sm:h-10 sm:w-auto sm:max-w-none"
            >
              <DottedlinedownArrowIcon />
              <span>{t("hero.quickStart")}</span>
            </button>
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
                src="https://img.alicdn.com/imgextra/i3/O1CN016c7HKZ1bRBuniPqeT_!!6000000003461-2-tps-2278-1469.png"
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
    </>
  );
}
