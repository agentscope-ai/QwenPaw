import { motion } from "motion/react";

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
    transition: { duration: 0.35, ease: "easeOut" },
  },
};

const AVATARS = [
  { key: "a1", src: "/copaw-symbol.png", alt: "CoPaw user avatar 1" },
  { key: "a2", src: "/copaw-symbol.png", alt: "CoPaw user avatar 2" },
  { key: "a3", src: "/copaw-symbol.png", alt: "CoPaw user avatar 3" },
  { key: "a4", src: "/copaw-symbol.png", alt: "CoPaw user avatar 4" },
  { key: "a5", src: "/copaw-symbol.png", alt: "CoPaw user avatar 5" },
] as const;

const TESTIMONIALS = [
  {
    key: "t1",
    text: "As an AI enthusiast who is keen on researching various open-source AI tools, my biggest feeling about copaw is that it has extremely high freedom.",
    name: "@Angelo Livanos",
    role: "Developer",
  },
  {
    key: "t2",
    text: "As an AI enthusiast who is keen on researching various open-source AI tools, my biggest feeling about copaw is that it has extremely high freedom.",
    name: "@Angelo Livanos",
    role: "Developer",
  },
  {
    key: "t3",
    text: "As an AI enthusiast who is keen on researching various open-source AI tools, my biggest feeling about copaw is that it has extremely high freedom.",
    name: "@Angelo Livanos",
    role: "Developer",
  },
  {
    key: "t4",
    text: "As an AI enthusiast who is keen on researching various open-source AI tools, my biggest feeling about copaw is that it has extremely high freedom.",
    name: "@Angelo Livanos",
    role: "Developer",
  },
  {
    key: "t5",
    text: "As an AI enthusiast who is keen on researching various open-source AI tools, my biggest feeling about copaw is that it has extremely high freedom.",
    name: "@Angelo Livanos",
    role: "Developer",
  },
  {
    key: "t6",
    text: "As an AI enthusiast who is keen on researching various open-source AI tools, my biggest feeling about copaw is that it has extremely high freedom.",
    name: "@Angelo Livanos",
    role: "Developer",
  },
] as const;

export function CopawClientVoices() {
  return (
    <motion.section
      className="px-4 py-10 md:py-14"
      variants={sectionVariants}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, amount: 0.2 }}
      aria-labelledby="copaw-client-voices-heading"
    >
      <div className="mx-auto max-w-7xl">
        <motion.div variants={itemVariants}>
          <div className="inline-flex items-center rounded-full border border-[#e8ddd3] bg-[#f6f1eb] px-2 py-1 shadow-[0_1px_2px_rgba(0,0,0,0.06)]">
            <div className="flex -space-x-2.5">
              {AVATARS.map((avatar) => (
                <img
                  key={avatar.key}
                  src={avatar.src}
                  alt={avatar.alt}
                  className="h-8 w-8 rounded-full border border-white object-cover md:h-9 md:w-9"
                  loading="lazy"
                />
              ))}
            </div>
          </div>

          <h2
            id="copaw-client-voices-heading"
            className="font-newsreader mt-4 text-[1.85rem] leading-[1.18] text-(--color-text) sm:text-[2rem] md:mt-5 md:text-[2.75rem]"
          >
            Listen to what our clients say about CoPaw
          </h2>
          <p className="font-inter mt-2 text-[13px] leading-relaxed text-(--color-text-tertiary) md:text-[1rem]">
            Memory and personalization under your control.
          </p>
        </motion.div>

        <motion.div
          className="mt-7 grid gap-4 sm:grid-cols-2 md:mt-8 md:grid-cols-3 md:gap-5"
          variants={itemVariants}
        >
          {TESTIMONIALS.map((item) => (
            <article
              key={item.key}
              className="flex min-h-55 flex-col rounded-2xl border border-[#ece2d9] bg-white p-4 shadow-[0_2px_8px_rgba(43,33,24,0.04)] md:min-h-60 md:p-5"
            >
              <p className="font-inter text-[0.98rem] leading-[1.75] text-(--color-text-secondary)">
                {item.text}
              </p>
              <div className="mt-auto flex items-center gap-3 pt-6">
                <img
                  src="/copaw-symbol.png"
                  alt={`${item.name} avatar`}
                  className="h-8 w-8 rounded-full border border-[#efe6de] object-cover"
                  loading="lazy"
                />
                <div className="leading-tight">
                  <p className="font-inter text-[0.98rem] font-medium text-(--color-text)">
                    {item.name}
                  </p>
                  <p className="font-inter mt-1 text-sm text-(--color-text-tertiary)">
                    {item.role}
                  </p>
                </div>
              </div>
            </article>
          ))}
        </motion.div>
      </div>
    </motion.section>
  );
}
