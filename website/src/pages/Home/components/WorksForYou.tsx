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

const cards = [
  {
    key: "skills",
    icon: "/support-skills.svg",
    title: "Support Skills",
    href: "/docs/skills",
  },
  {
    key: "control",
    icon: "/under-control.svg",
    title: "Under your control",
    href: "/docs/privacy",
  },
  {
    key: "apps",
    icon: "/explore-apps.svg",
    title: "Explore Apps",
    href: "/docs/apps",
  },
] as const;

export function CopawWorksForYou() {
  return (
    <motion.section
      className="px-4 pb-12 md:pb-16"
      variants={container}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, amount: 0.2 }}
      aria-labelledby="copaw-works-heading"
    >
      <div className="mx-auto max-w-7xl">
        <motion.div variants={item}>
          <h2
            id="copaw-works-heading"
            className="font-newsreader text-[1.8rem] leading-[1.2] text-(--color-text) sm:text-[2rem] md:text-[2.75rem]"
          >
            Works for you, grows with you
          </h2>
          <p className="font-inter mt-2 max-w-[34ch] text-[13px] leading-relaxed text-(--color-text-tertiary) sm:max-w-none md:text-[1rem]">
            Memory and personalization under your control.
          </p>
        </motion.div>

        <div className="relative mt-7 py-7 md:mt-10 md:py-10">
          <div
            className="pointer-events-none absolute left-1/2 top-0 h-px w-screen -translate-x-1/2"
            style={{
              background:
                "repeating-linear-gradient(to right, rgba(255,157,77,0.45) 0 8px, transparent 8px 16px)",
            }}
          />
          <motion.div
            className="grid gap-0 divide-y divide-[#f1e5dc] md:grid-cols-3 md:gap-10 md:divide-y-0"
            variants={item}
          >
            {cards.map((card) => (
              <article
                key={card.key}
                className="flex flex-col py-6 first:pt-0 last:pb-0 md:py-0"
              >
                <img
                  src={card.icon}
                  alt=""
                  aria-hidden
                  className="h-20 w-20 object-contain opacity-80 md:h-23 md:w-23"
                />
                <h3 className="font-newsreader mt-3 text-[1.65rem] leading-[1.1] text-(--color-text) sm:text-[1.8rem] md:mt-4 md:text-[2.05rem]">
                  {card.title}
                </h3>
                <p className="font-inter mt-2 text-[13px] leading-[1.65] text-(--color-text-secondary) md:text-[0.95rem]">
                  Memory and personalization under your control. Deploy locally or
                  in the cloud; scheduled reminders and collaboration to any
                  channel reminders.
                </p>
                <a
                  href={card.href}
                  className="font-inter mt-4 inline-flex w-fit items-center gap-2 text-[0.95rem] font-medium text-(--color-text) transition hover:text-orange-400! md:mt-5 md:text-[0.98rem]"
                >
                  Learn more
                  <span aria-hidden>→</span>
                </a>
              </article>
            ))}
          </motion.div>
          <div
            className="pointer-events-none absolute bottom-0 left-1/2 h-px w-screen -translate-x-1/2"
            style={{
              background:
                "repeating-linear-gradient(to right, rgba(255,157,77,0.45) 0 8px, transparent 8px 16px)",
            }}
          />
        </div>
      </div>
    </motion.section>
  );
}
