import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

type CardKey =
  | "osShell"
  | "workspace"
  | "creator"
  | "thirdPartyAgents"
  | "browserUse"
  | "computerUse"
  | "checkpoint"
  | "scroll";

type CardConfig = {
  key: CardKey;
  icon: string;
  href: string;
};

const cards: CardConfig[] = [
  {
    key: "osShell",
    icon: "https://img.alicdn.com/imgextra/i1/O1CN014f1A4DOhc8C0tO9Q_!!6000000005275-2-tps-440-440.png",
    href: "/blog/qwenpaw-os-shell",
  },
  {
    key: "workspace",
    icon: "https://img.alicdn.com/imgextra/i2/O1CN01RAPKrJTdLiE0tO9Q_!!6000000001309-2-tps-440-440.png",
    href: "/blog/qwenpaw-files-workspace",
  },
  {
    key: "creator",
    icon: "https://img.alicdn.com/imgextra/i3/O1CN01OYqOIpNkY4E0tO9Q_!!6000000000622-2-tps-440-440.png",
    href: "/docs/creator",
  },
  {
    key: "thirdPartyAgents",
    icon: "https://img.alicdn.com/imgextra/i2/O1CN01wLKOiNfUg7H0tO9Q_!!6000000006833-2-tps-440-440.png",
    href: "/blog/cross-harness-agent-os",
  },
  {
    key: "browserUse",
    icon: "https://img.alicdn.com/imgextra/i4/O1CN01VTtdxYTVHWH0yQKu_!!6000000001120-2-tps-480-440.png",
    href: "/docs/browser",
  },
  {
    key: "computerUse",
    icon: "https://img.alicdn.com/imgextra/i1/O1CN01B4Zh0VfrvgB0yQKu_!!6000000003266-2-tps-480-440.png",
    href: "/docs/computer-use",
  },
  {
    key: "checkpoint",
    icon: "https://img.alicdn.com/imgextra/i4/O1CN01ufoiDfvVoEE0yQKu_!!6000000002198-2-tps-480-440.png",
    href: "/blog/qwenpaw-checkpoint",
  },
  {
    key: "scroll",
    icon: "https://img.alicdn.com/imgextra/i3/O1CN01ViALPzudWCE1GYCe_!!6000000004102-2-tps-624-440.png",
    href: "/blog/qwenpaw-scroll-executable-memory",
  },
];

const CARDS_PER_PAGE = 4;
const pageCount = Math.ceil(cards.length / CARDS_PER_PAGE);
const pages = Array.from({ length: pageCount }, (_, page) => page);
const AUTO_ROTATE_MS = 5000;

export function WorksForYou() {
  const { t } = useTranslation();
  const sectionRef = useRef<HTMLElement>(null);
  const carouselRef = useRef<HTMLDivElement>(null);
  const scrollEndTimerRef = useRef<number | null>(null);
  const isScrollingRef = useRef(false);
  const [activePage, setActivePage] = useState(0);
  const [isScrolling, setIsScrolling] = useState(false);
  const [isInView, setIsInView] = useState(false);
  const [isDesktop, setIsDesktop] = useState(() =>
    typeof window !== "undefined"
      ? window.matchMedia("(min-width: 640px)").matches
      : false,
  );
  const reduceMotion = useReducedMotion();

  useLayoutEffect(() => {
    if (!isDesktop) return;
    const carousel = carouselRef.current;
    if (!carousel) return;
    carousel.scrollLeft = activePage * carousel.clientWidth;
  }, [activePage, isDesktop]);

  useEffect(() => {
    const mediaQuery = window.matchMedia("(min-width: 640px)");
    const updateDesktop = () => setIsDesktop(mediaQuery.matches);
    updateDesktop();
    mediaQuery.addEventListener("change", updateDesktop);
    return () => mediaQuery.removeEventListener("change", updateDesktop);
  }, []);

  useEffect(() => {
    const section = sectionRef.current;
    if (!section) return;

    const observer = new IntersectionObserver(
      ([entry]) => setIsInView(entry.isIntersecting),
      { threshold: 0.15 },
    );
    observer.observe(section);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const carousel = carouselRef.current;
    if (!carousel) return;

    const settleCarousel = () => {
      const pageWidth = carousel.clientWidth;
      if (!pageWidth) return;
      const page = Math.min(
        pageCount - 1,
        Math.max(0, Math.round(carousel.scrollLeft / pageWidth)),
      );

      setActivePage(page);
      isScrollingRef.current = false;
      setIsScrolling(false);
    };

    const handleScroll = () => {
      if (carousel.scrollTop !== 0) carousel.scrollTop = 0;
      if (!isScrollingRef.current) {
        isScrollingRef.current = true;
        setIsScrolling(true);
      }
      if (scrollEndTimerRef.current !== null) {
        window.clearTimeout(scrollEndTimerRef.current);
      }
      scrollEndTimerRef.current = window.setTimeout(settleCarousel, 120);
    };

    carousel.addEventListener("scroll", handleScroll, { passive: true });
    return () => {
      carousel.removeEventListener("scroll", handleScroll);
      if (scrollEndTimerRef.current !== null) {
        window.clearTimeout(scrollEndTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (
      reduceMotion ||
      !isDesktop ||
      !isInView ||
      isScrolling ||
      pageCount < 2
    ) {
      return;
    }

    const timer = window.setTimeout(() => {
      const carousel = carouselRef.current;
      if (!carousel) return;
      const nextPage = activePage === 0 ? 1 : 0;
      carousel.scrollTo({
        left: nextPage * carousel.clientWidth,
        behavior: reduceMotion ? "auto" : "smooth",
      });
    }, AUTO_ROTATE_MS);

    return () => window.clearTimeout(timer);
  }, [activePage, isDesktop, isInView, isScrolling, reduceMotion]);

  const scrollToPage = (page: number) => {
    const carousel = carouselRef.current;
    if (!carousel) return;
    carousel.scrollTo({
      left: page * carousel.clientWidth,
      behavior: reduceMotion ? "auto" : "smooth",
    });
  };

  const autoProgressing =
    !reduceMotion && isDesktop && isInView && !isScrolling;

  return (
    <motion.section
      ref={sectionRef}
      className="relative overflow-x-clip px-4 py-12 md:py-16"
      initial={reduceMotion ? false : { opacity: 0, y: 16 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.2 }}
      aria-labelledby="qwenpaw-works-heading"
    >
      <div className="mx-auto max-w-7xl">
        <h2
          id="qwenpaw-works-heading"
          className="font-newsreader text-3xl leading-[1.2] font-semibold text-(--color-text) sm:text-[2rem] md:text-4xl"
        >
          {t("worksForYou.title")}
        </h2>
        <p className="font-inter mt-2 max-w-[34ch] text-[13px] leading-relaxed text-(--color-text-tertiary) sm:max-w-none md:text-base">
          {t("worksForYou.sub")}
        </p>

        <div className="relative mt-8 py-8 md:mt-12 md:py-12">
          <div
            className="pointer-events-none absolute left-1/2 top-0 h-px w-screen -translate-x-1/2 animate-[qwenpaw-dash-move-right_1s_linear_infinite]"
            style={{
              background:
                "repeating-linear-gradient(to right, rgba(255,157,77,0.45) 0 8px, transparent 8px 16px)",
              backgroundSize: "16px 100%",
            }}
            aria-hidden
          />

          <div className="divide-y divide-[#F1E5DC] sm:hidden">
            {cards.map((card, index) => (
              <FeatureCard
                key={card.key}
                card={card}
                index={index}
                title={t(`worksForYou.cards.${card.key}.title`)}
                description={t(`worksForYou.cards.${card.key}.desc`)}
                learnMore={t("worksForYou.learnMore")}
                reduceMotion={Boolean(reduceMotion)}
              />
            ))}
          </div>

          <div
            ref={carouselRef}
            className="hidden overflow-x-auto overflow-y-hidden scroll-smooth snap-x snap-mandatory sm:block [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
            aria-label={t("worksForYou.title")}
            tabIndex={0}
          >
            <div className="flex items-stretch">
              {pages.map((page) => (
                <div
                  key={page}
                  className="grid w-full min-w-full shrink-0 basis-full snap-start grid-cols-1 gap-x-6 gap-y-0 sm:grid-cols-4 sm:gap-x-8 md:gap-x-10"
                >
                  {cards
                    .slice(page * CARDS_PER_PAGE, (page + 1) * CARDS_PER_PAGE)
                    .map((card, pageIndex) => (
                      <FeatureCard
                        key={card.key}
                        card={card}
                        index={page * CARDS_PER_PAGE + pageIndex}
                        title={t(`worksForYou.cards.${card.key}.title`)}
                        description={t(`worksForYou.cards.${card.key}.desc`)}
                        learnMore={t("worksForYou.learnMore")}
                        reduceMotion={Boolean(reduceMotion)}
                      />
                    ))}
                </div>
              ))}
            </div>
          </div>

          <div
            className="pointer-events-none absolute bottom-0 left-1/2 h-px w-screen -translate-x-1/2 animate-[qwenpaw-dash-move-left_1s_linear_infinite]"
            style={{
              background:
                "repeating-linear-gradient(to right, rgba(255,157,77,0.45) 0 8px, transparent 8px 16px)",
              backgroundSize: "16px 100%",
            }}
            aria-hidden
          />

          <div
            className="absolute bottom-4 left-1/2 z-10 hidden -translate-x-1/2 items-center gap-5 sm:flex md:bottom-5"
            role="tablist"
            aria-label="Works for you pages"
          >
            {pages.map((page) => (
              <button
                key={page}
                type="button"
                role="tab"
                aria-selected={activePage === page}
                aria-label={`Page ${page + 1} of ${pageCount}`}
                onClick={() => scrollToPage(page)}
                className="group flex h-5 w-16 items-center justify-center focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-primary)"
              >
                <div className="relative h-0.5 w-14 overflow-hidden rounded-full bg-[#E3E0DC] leading-none transition-colors duration-300 group-hover:bg-[#D5D0CB]">
                  {activePage === page && (
                    <motion.div
                      key={`${page}-${autoProgressing ? "timed" : "idle"}`}
                      className="absolute top-0 bottom-0 left-0 rounded-full bg-[linear-gradient(90deg,#FFB36F_0%,#FF9D4D_55%,#F7852D_100%)]"
                      initial={reduceMotion ? false : { width: "0%" }}
                      animate={{
                        width: reduceMotion
                          ? "100%"
                          : autoProgressing
                          ? "100%"
                          : "0%",
                      }}
                      transition={{
                        duration: autoProgressing
                          ? AUTO_ROTATE_MS / 1000
                          : 0.15,
                        ease: autoProgressing ? "linear" : "easeOut",
                      }}
                    />
                  )}
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </motion.section>
  );
}

function FeatureCard({
  card,
  index,
  title,
  description,
  learnMore,
  reduceMotion,
}: {
  card: CardConfig;
  index: number;
  title: string;
  description: string;
  learnMore: string;
  reduceMotion: boolean;
}) {
  return (
    <motion.article
      className="group flex min-w-0 h-full flex-col border-b border-[#F1E5DC] py-6 last:border-b-0 sm:border-b-0 sm:py-0"
      initial={reduceMotion ? false : { opacity: 0, y: 12 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.2 }}
      transition={{
        duration: 0.45,
        delay: reduceMotion ? 0 : (index % CARDS_PER_PAGE) * 0.05,
        ease: "easeOut",
      }}
    >
      <div className="flex h-20 items-center md:h-24">
        <img
          src={card.icon}
          alt=""
          aria-hidden
          loading="eager"
          decoding="async"
          className="h-20 w-20 object-contain opacity-80 md:h-24 md:w-24"
        />
      </div>
      <h3 className="font-newsreader mt-4 text-[1.55rem] leading-[1.1] text-(--color-text) sm:text-[1.65rem] md:mt-5 md:text-[1.75rem]">
        {title}
      </h3>
      <p className="font-inter mt-3 text-[13px] leading-[1.65] text-(--color-text-secondary) md:text-sm">
        {description}
      </p>
      <Link
        to={card.href}
        target="_blank"
        rel="noopener noreferrer"
        className="font-inter group/link mt-auto inline-flex w-fit items-center gap-2 pt-5 text-sm text-(--color-text) no-underline transition-colors hover:text-(--color-primary)"
      >
        {learnMore}
        <span
          className="transition-transform group-hover/link:translate-x-1"
          aria-hidden
        >
          →
        </span>
      </Link>
    </motion.article>
  );
}
