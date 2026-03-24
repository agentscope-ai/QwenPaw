import { motion } from "motion/react";

const TOP_CHANNELS = [
  { icon: "🟢", name: "WhatsApp" },
  { icon: "🟣", name: "Discord" },
  { icon: "🌀", name: "Feishu" },
  { icon: "🐧", name: "QQ" },
  { icon: "🟩", name: "WeChat" },
  { icon: "🔷", name: "DingTalk" },
  { icon: "✖", name: "X" },
];

const BOTTOM_CHANNELS = [
  { icon: "🧠", name: "Doubao" },
  { icon: "🌀", name: "Deepseek" },
  { icon: "🌀", name: "ChatGPT" },
  { icon: "✉️", name: "Gmail" },
  { icon: "🎵", name: "NetEaseMusic" },
  { icon: "🟢", name: "Spotify" },
  { icon: "🐙", name: "Github" },
  { icon: "💬", name: "iMessage" },
];

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

function ChannelPill({ icon, name }: { icon: string; name: string }) {
  return (
    <div className="inline-flex h-13 w-43 shrink-0 items-center justify-center gap-2 rounded-xl border border-[#ece7e2] bg-white px-6 py-2 text-sm font-medium text-(--color-text-secondary) shadow-[0_1px_0_rgba(0,0,0,0.02)] md:text-[1.02rem]">
      <span className="text-sm" aria-hidden>
        {icon}
      </span>
      <span>{name}</span>
    </div>
  );
}

export function CopawChannels() {
  return (
    <motion.section
      className="relative px-4 py-10 md:py-12"
      variants={sectionVariants}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, amount: 0.2 }}
    >
      <motion.div
        className="mx-auto flex max-w-5xl flex-col items-center text-center"
        variants={itemVariants}
      >
        <motion.h2
          className="font-newsreader text-[clamp(1.9rem,4vw,3rem)] font-semibold leading-[1.2] text-(--color-text)"
          variants={itemVariants}
        >
          We Cooperate with <em className="font-normal italic">Everything.</em>
        </motion.h2>
        <motion.p
          className="font-inter mx-auto mt-3 max-w-3xl text-sm leading-relaxed text-(--color-text-tertiary) md:text-[1.03rem]"
          variants={itemVariants}
        >
          Memory and personalization under your control. Memory and
          personalization under your control.Memory and personalization under
          your control.
        </motion.p>
      </motion.div>

      <motion.div className="relative mt-8 w-full" variants={itemVariants}>
        <div className="group/row-top overflow-hidden">
          <div className="inline-flex w-max items-center gap-3 whitespace-nowrap py-2 will-change-transform animate-[copaw-channels-marquee-right_42s_linear_infinite] group-hover/row-top:[animation-play-state:paused]">
            {[...TOP_CHANNELS, ...TOP_CHANNELS, ...TOP_CHANNELS,].map((item, idx) => (
              <ChannelPill
                key={`${item.name}-${idx}`}
                icon={item.icon}
                name={item.name}
              />
            ))}
          </div>
        </div>

        <div className="group/row-bottom mt-3 overflow-hidden">
          <div className="inline-flex w-max items-center gap-3 whitespace-nowrap py-2 will-change-transform animate-[copaw-channels-marquee-left_48s_linear_infinite] group-hover/row-bottom:[animation-play-state:paused]">
              {[...BOTTOM_CHANNELS, ...BOTTOM_CHANNELS, ...BOTTOM_CHANNELS,].map((item, idx) => (
                <ChannelPill key={`${item.name}-bottom-${idx}`} icon={item.icon} name={item.name} />
              ))}
          </div>
        </div>

        <div className="pointer-events-none absolute inset-y-0 left-0 w-14 bg-linear-to-r from-(--bg) to-transparent" />
        <div className="pointer-events-none absolute inset-y-0 right-0 w-14 bg-linear-to-l from-(--bg) to-transparent" />
      </motion.div>
    </motion.section>
  );
}
