import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "motion/react";
import { useTranslation } from "react-i18next";

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

const PAW_ANIMATION_DURATION = 10;

export function CopawWhy() {
  const { t } = useTranslation();
  const [progress, setProgress] = useState(0);
  const [animationsStarted, setAnimationsStarted] = useState(false);
  const sectionRef = useRef<HTMLElement | null>(null);
  const [isInView, setIsInView] = useState(false);

  const heroLine = t("whyCopaw.heroLine");
  const secondPrefix = t("whyCopaw.secondPrefix");
  const secondEmphasis = t("whyCopaw.secondEmphasis");
  const secondSuffix = t("whyCopaw.secondSuffix");
  const secondLine = `${secondPrefix}${secondEmphasis}${secondSuffix}`;
  const heroLineLength = heroLine.length;
  const secondLineLength = secondLine.length;

  // Start paw and circle animations after container animation completes
  const handleContainerAnimationComplete = () => {
    setAnimationsStarted(true);
  };

  const prefersReducedMotion = useMemo(() => {
    if (typeof window === "undefined") return false;
    return window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
  }, []);

  useEffect(() => {
    const el = sectionRef.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") {
      setIsInView(true);
      return;
    }

    const obs = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        setIsInView(Boolean(entry?.isIntersecting));
      },
      { threshold: 0.15 },
    );

    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  useEffect(() => {
    if (!animationsStarted) return;
    if (!isInView) return;
    if (prefersReducedMotion) return;
    let rafId = 0;
    const durationMs = PAW_ANIMATION_DURATION * 1000;
    // Preserve phase when leaving/entering viewport.
    const start = performance.now() - progress * durationMs;

    const tick = (now: number) => {
      const nextProgress = ((now - start) % durationMs) / durationMs;
      setProgress(nextProgress);
      rafId = requestAnimationFrame(tick);
    };

    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, [animationsStarted, isInView, prefersReducedMotion, progress]);

  const isTopPhase = progress < 0.5;
  const topPhaseProgress = Math.min(1, progress / 0.5);
  const bottomPhaseProgress = Math.max(0, (progress - 0.5) / 0.5);

  const pawIndexTop = Math.min(
    heroLineLength - 1,
    Math.floor(topPhaseProgress * heroLineLength),
  );
  const pawIndexSecond = Math.min(
    secondLineLength - 1,
    Math.floor(bottomPhaseProgress * secondLineLength),
  );

  const topSplit = isTopPhase
    ? Math.min(heroLineLength, pawIndexTop + 1)
    : heroLineLength;
  const secondSplit = isTopPhase
    ? 0
    : Math.min(secondLineLength, pawIndexSecond + 1);
  const leftText = heroLine.slice(0, topSplit);
  const rightText = heroLine.slice(topSplit);

  const renderSecondText = (from: number, to: number, highlighted: boolean) => {
    const text = secondLine.slice(from, to);
    const baseClass = highlighted
      ? "text-[#ffffff]"
      : "text-[rgba(255,255,255,0.45)]";

    // Calculate which line the 'from' position is in (0, 1, or 2)
    const textBeforeFrom = secondLine.slice(0, from);
    const startLineIndex = textBeforeFrom.split("\n").length - 1;

    const lines = text.split("\n");
    return (
      <>
        {lines.map((line, idx) => {
          // Original line index in the full text
          const originalLineIndex = startLineIndex + idx;
          return (
            <span key={idx}>
              <span
                className={`${baseClass} ${
                  originalLineIndex === 1 ? "italic" : ""
                }`}
              >
                {line}
              </span>
              {idx < lines.length - 1 && <br />}
            </span>
          );
        })}
      </>
    );
  };

  return (
    <motion.section
      ref={sectionRef}
      className="relative min-h-114 overflow-hidden bg-[#E77C29] px-4 py-4 text-[#ffe8d7] sm:h-[680px] md:h-[700px] md:py-0"
      variants={container}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, amount: 0.2 }}
      onAnimationComplete={handleContainerAnimationComplete}
      style={{
        backgroundImage:
          "radial-gradient(rgba(255,244,232,0.22) 1px, transparent 1px)",
        backgroundSize: "24px 24px",
      }}
    >
      <div className="mx-auto flex h-full max-w-7xl flex-col items-center justify-start md:items-stretch md:justify-center">
        <motion.div
          className="flex w-full flex-col items-center gap-4 border-b border-[rgba(255,235,220,0.35)] pb-5 md:pb-6 mt-2 md:mt-0 md:flex-row md:items-center md:justify-between"
          variants={item}
        >
          <div className="relative pt-7 md:pt-10">
            <img
              src="https://img.alicdn.com/imgextra/i1/O1CN01g2HNmz1NwshO2uhvo_!!6000000001635-2-tps-222-222.png"
              alt=""
              aria-hidden
              className="pointer-events-none absolute -top-2 left-0 z-20 h-11 w-11 object-contain md:-top-6 md:h-20 md:w-20"
            />
            <h2 className="font-newsreader font-semibold relative z-10 text-3xl leading-[0.98] text-[#ffffff] sm:text-[42px] md:text-[52px]">
              <span>{t("whyCopaw.headingPrefix")} </span>
              <span className="inline-block italic whitespace-nowrap">
                {t("whyCopaw.headingEmphasis")}
              </span>
              <svg
                aria-hidden
                viewBox="0 0 360 120"
                className="pointer-events-none absolute left-[4.5em] top-[0.3em] h-[3em] w-[4.65em] -translate-x-1/2 -translate-y-1/2 rotate-[-7deg]"
              >
                <motion.ellipse
                  cx="180"
                  cy="60"
                  rx="168"
                  ry="50"
                  fill="none"
                  stroke="rgba(255, 241, 230, 0.95)"
                  strokeWidth="2.4"
                  strokeDasharray="1070"
                  initial={{ strokeDashoffset: 1070 }}
                  animate={{ strokeDashoffset: animationsStarted ? 0 : 1070 }}
                  transition={{ duration: 1, ease: [0.4, 0, 0.2, 1] }}
                />
              </svg>
            </h2>
          </div>
          <p className="font-inter text-center text-[13px] leading-5 text-[rgba(255,255,255,0.7)] sm:text-sm sm:leading-6 md:text-right md:text-base md:pt-8">
            {t("whyCopaw.sub")
              .split("\n")
              .map((line, idx) => (
                <span key={idx}>
                  {line}
                  {idx === 0 ? <br /> : null}
                </span>
              ))}
          </p>
        </motion.div>

        <motion.div
          className="font-newsreader mt-6 max-w-4xl text-center text-[20px] leading-[1.38] tracking-[-0.01em] text-[#ffffff] sm:mt-7 sm:text-[24px] md:mt-10 md:text-left md:text-4xl"
          variants={item}
        >
          <p
            className="whitespace-pre-line text-[rgba(220,210,201,0.9)]"
            style={{ lineHeight: "1.6em" }}
          >
            <span className="text-[#ffffff]">{leftText}</span>
            {isTopPhase ? (
              <span className="mx-0.5 inline-flex h-[1.5em] w-[1.5em] -translate-y-[0.04em] items-center justify-center align-middle">
                <motion.img
                  src="/paw.png"
                  alt=""
                  aria-hidden
                  className="h-full w-full object-contain"
                  animate={{ y: [0, -1.8, 0] }}
                  transition={{
                    duration: 0.9,
                    ease: "easeInOut",
                    repeat: Infinity,
                  }}
                />
              </span>
            ) : null}
            <span className="text-[rgba(255,255,255,0.45)]">{rightText}</span>
          </p>
          <p
            className="mt-4 whitespace-pre-line text-[rgba(220,210,201,0.9)] sm:mt-5 md:mt-8"
            style={{ lineHeight: "1.6em" }}
          >
            {renderSecondText(0, secondSplit, true)}
            {!isTopPhase ? (
              <span className="mx-0.5 inline-flex h-[1.5em] w-[1.5em] -translate-y-[0.04em] items-center justify-center align-middle">
                <motion.img
                  src="/paw.png"
                  alt=""
                  aria-hidden
                  className="h-full w-full object-contain"
                  animate={{ y: [0, -0.9, 0] }}
                  transition={{
                    duration: 0.9,
                    ease: "easeInOut",
                    repeat: Infinity,
                  }}
                />
              </span>
            ) : null}
            {renderSecondText(secondSplit, secondLineLength, false)}
          </p>
        </motion.div>
      </div>
    </motion.section>
  );
}
