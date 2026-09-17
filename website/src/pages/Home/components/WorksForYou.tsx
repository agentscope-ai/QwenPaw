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

const cards = [
  {
    key: "agentOs",
    icon: "https://img.alicdn.com/imgextra/i1/O1CN01b9Y72C1bJrbBiUsMl_!!6000000003445-2-tps-330-330.png",
    href: "/docs/architecture",
  },
  {
    key: "tui",
    icon: "https://img.alicdn.com/imgextra/i4/O1CN018nPL7R2AEpnnWjaI1_!!6000000008172-2-tps-330-330.png",
    href: "/docs/tui",
  },
  {
    key: "scrollContext",
    icon: "https://img.alicdn.com/imgextra/i1/O1CN01mlnREC1Moo7dQ3tgE_!!6000000001482-2-tps-330-330.png",
    href: "/docs/context",
  },
  {
    key: "loopEngineering",
    icon: "https://img.alicdn.com/imgextra/i1/O1CN01aDM9r51VQpvzgywwx_!!6000000002648-2-tps-330-330.png",
    href: "/docs/loop-engineering",
  },
] as const;

export function WorksForYou() {
  const { t } = useTranslation();

  return (
    <>
      <motion.section
        className="px-4 py-12 md:py-16"
        variants={container}
        initial="hidden"
        whileInView="show"
        viewport={{ once: true, amount: 0.2 }}
        aria-labelledby="qwenpaw-works-heading"
      >
        <div className="mx-auto max-w-7xl">
          <motion.div variants={item}>
            <h2
              id="qwenpaw-works-heading"
              className="font-newsreader font-semibold text-3xl leading-[1.2] text-(--color-text) sm:text-[2rem] md:text-4xl"
            >
              {t("worksForYou.title")}
            </h2>
            <p className="font-inter mt-2 max-w-[34ch] text-[13px] leading-relaxed text-(--color-text-tertiary) sm:max-w-none md:text-[1rem]">
              {t("worksForYou.sub")}
            </p>
          </motion.div>

          <div className="relative mt-8 py-8 md:mt-12 md:py-12">
            <div
              className="pointer-events-none absolute left-1/2 top-0 h-px w-screen -translate-x-1/2 animate-[qwenpaw-dash-move-right_1s_linear_infinite]"
              style={{
                background:
                  "repeating-linear-gradient(to right, rgba(255,157,77,0.45) 0 8px, transparent 8px 16px)",
                backgroundSize: "16px 100%",
              }}
            />
            <motion.div
              className="grid gap-0 divide-y divide-[#f1e5dc] md:grid-cols-4 md:gap-x-6 md:divide-y-0 lg:gap-x-10"
              variants={item}
            >
              {cards.map((card) => (
                <article
                  key={card.key}
                  className="flex h-full flex-col py-6 first:pt-0 last:pb-0 md:py-0"
                >
                  <img
                    src={card.icon}
                    alt=""
                    aria-hidden
                    className="h-20 w-20 object-contain opacity-80 md:h-23 md:w-23"
                  />
                  <h3 className="font-newsreader mt-3 text-[1.65rem] leading-[1.1] text-(--color-text) sm:text-[1.8rem] md:mt-6 md:text-[1.8rem]">
                    {t(`worksForYou.cards.${card.key}.title`)}
                  </h3>
                  <p className="font-inter mt-2 text-[13px] leading-[1.65] text-(--color-text-secondary) md:text-base">
                    {t(`worksForYou.cards.${card.key}.desc`)}
                  </p>
                  <a
                    href={card.href}
                    className="font-inter mt-auto inline-flex w-fit items-center gap-2 pt-4 text-[0.95rem] text-(--color-text) transition hover:text-orange-400! md:pt-5 md:text-base"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {t("worksForYou.learnMore")}
                    <span aria-hidden>→</span>
                  </a>
                </article>
              ))}
            </motion.div>
            <div
              className="pointer-events-none absolute bottom-0 left-1/2 h-px w-screen -translate-x-1/2 animate-[qwenpaw-dash-move-left_1s_linear_infinite]"
              style={{
                background:
                  "repeating-linear-gradient(to right, rgba(255,157,77,0.45) 0 8px, transparent 8px 16px)",
                backgroundSize: "16px 100%",
              }}
            />
          </div>
        </div>
      </motion.section>
    </>
  );
}
