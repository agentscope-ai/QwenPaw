import { useEffect, useState } from "react";
import { motion } from "motion/react";

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
    transition: { duration: 0.35, ease: "easeOut" },
  },
};

const HERO_LINE =
  'CoPaw represents both a Co Personal Agent Workstation and a "co-paw" -- a partner always by your side.';
const SECOND_PREFIX = "More than just a cold tool, ";
const SECOND_EMPHASIS = "(CoPaw always ready to lend a paw)";
const SECOND_SUFFIX = " It is the ultimate teammate for your digital life.";
const SECOND_LINE = `${SECOND_PREFIX}${SECOND_EMPHASIS}${SECOND_SUFFIX}`;
const HERO_LINE_LENGTH = HERO_LINE.length;
const SECOND_LINE_LENGTH = SECOND_LINE.length;
const PAW_ANIMATION_DURATION = 160;

export function CopawWhy() {
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    let rafId = 0;
    const durationMs = PAW_ANIMATION_DURATION * 1000;
    const start = performance.now();

    const tick = (now: number) => {
      const nextProgress = ((now - start) % durationMs) / durationMs;
      setProgress(nextProgress);
      rafId = requestAnimationFrame(tick);
    };

    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, []);

  const isTopPhase = progress < 0.5;
  const topPhaseProgress = Math.min(1, progress / 0.5);
  const bottomPhaseProgress = Math.max(0, (progress - 0.5) / 0.5);

  const pawIndexTop = Math.min(
    HERO_LINE_LENGTH - 1,
    Math.floor(topPhaseProgress * HERO_LINE_LENGTH),
  );
  const pawIndexSecond = Math.min(
    SECOND_LINE_LENGTH - 1,
    Math.floor(bottomPhaseProgress * SECOND_LINE_LENGTH),
  );

  const topSplit = isTopPhase
    ? Math.min(HERO_LINE_LENGTH, pawIndexTop + 1)
    : HERO_LINE_LENGTH;
  const secondSplit = isTopPhase
    ? 0
    : Math.min(SECOND_LINE_LENGTH, pawIndexSecond + 1);
  const leftText = HERO_LINE.slice(0, topSplit);
  const rightText = HERO_LINE.slice(topSplit);
  const secondRanges = [
    { text: SECOND_PREFIX, emphasis: false },
    { text: SECOND_EMPHASIS, emphasis: true },
    { text: SECOND_SUFFIX, emphasis: false },
  ];

  const renderSecondText = (from: number, to: number, highlighted: boolean) => {
    let offset = 0;
    return secondRanges.map((range, idx) => {
      const start = offset;
      const end = offset + range.text.length;
      offset = end;
      const sliceStart = Math.max(from, start);
      const sliceEnd = Math.min(to, end);
      if (sliceEnd <= sliceStart) return null;
      const text = range.text.slice(sliceStart - start, sliceEnd - start);
      const baseClass = highlighted
        ? "text-[#ffe8d7]"
        : "text-[rgba(238,226,214,0.62)]";
      const emphasisClass = range.emphasis
        ? highlighted
          ? "inline-block align-baseline text-[0.92em] italic leading-[1.1] text-[#ffe8d7]"
          : "inline-block align-baseline text-[0.92em] italic leading-[1.1] text-[rgba(246,236,226,0.78)]"
        : "";
      return (
        <span key={`${highlighted ? "h" : "m"}-${idx}-${sliceStart}`} className={`${baseClass} ${emphasisClass}`.trim()}>
          {text}
        </span>
      );
    });
  };

  return (
    <motion.section
      className="relative overflow-hidden bg-[#E77C29] px-4 py-9 text-[#ffe8d7] md:py-14"
      variants={container}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, amount: 0.2 }}
      style={{
        backgroundImage:
          "radial-gradient(rgba(255,244,232,0.22) 1px, transparent 1px)",
        backgroundSize: "24px 24px",
      }}
    >
      <div className="mx-auto max-w-7xl">
        <motion.div
          className="flex flex-col gap-4 border-b border-[rgba(255,235,220,0.35)] pb-5 md:pb-6 md:flex-row md:items-center md:justify-between"
          variants={item}
        >
          <div className="relative pt-7 md:pt-10">
            <img
              src="/leopard.png"
              alt=""
              aria-hidden
              className="pointer-events-none absolute top-0 left-0 z-20 h-11 w-11 object-contain md:-top-6 md:h-20 md:w-20"
            />
            <h2 className="font-newsreader relative z-10 text-[38px] leading-[0.98] text-[#fff1e6] sm:text-[42px] md:text-[52px]">
              <span>Why </span>
              <span className="relative inline-block italic">
                CoPaw?
                <svg
                  aria-hidden
                  viewBox="0 0 360 120"
                  className="pointer-events-none absolute left-1/2 top-[30%] h-[3em] w-[4.25em] -translate-x-1/2 -translate-y-1/2 rotate-[-7deg]"
                >
                  <ellipse
                    cx="180"
                    cy="60"
                    rx="168"
                    ry="50"
                    fill="none"
                    stroke="rgba(255, 241, 230, 0.95)"
                    strokeWidth="2.4"
                  />
                </svg>
              </span>
            </h2>
          </div>
          <p className="font-inter max-w-md text-left text-[13px] leading-5 text-[rgba(255,240,228,0.78)] sm:text-sm sm:leading-6 md:text-right md:text-base">
            Memory and personalization under your control. Memory and
            personalization under your control.
          </p>
        </motion.div>

        <motion.div
          className="font-newsreader mt-6 max-w-4xl text-[25px] leading-[1.38] tracking-[-0.01em] text-[#ffe8d7] sm:mt-7 sm:text-[28px] md:mt-10 md:text-[46px]"
          variants={item}
        >
          <p className="whitespace-normal text-[rgba(220,210,201,0.9)]">
            <span className="text-[#ffe8d7]">{leftText}</span>
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
            <span className="text-[rgba(238,226,214,0.62)]">{rightText}</span>
          </p>
          <p className="mt-4 whitespace-normal text-[rgba(220,210,201,0.9)] sm:mt-5 md:mt-8">
            {renderSecondText(0, secondSplit, true)}
            {!isTopPhase ? (
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
            {renderSecondText(secondSplit, SECOND_LINE_LENGTH, false)}
          </p>
        </motion.div>
      </div>
    </motion.section>
  );
}
