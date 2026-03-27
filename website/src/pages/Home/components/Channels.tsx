import { motion } from "motion/react";
import { useTranslation } from "react-i18next";

const CHANNEL_ICON_BASE = "/channelsIcon";

const TOP_CHANNELS = [
  { iconSrc: `${CHANNEL_ICON_BASE}/Clause.png`, name: "Clause" },
  { iconSrc: `${CHANNEL_ICON_BASE}/WhatsApp.png`, name: "WhatsApp" },
  { iconSrc: `${CHANNEL_ICON_BASE}/X.png`, name: "X" },
  { iconSrc: `${CHANNEL_ICON_BASE}/WeChar.png`, name: "WeChat" },
  { iconSrc: `${CHANNEL_ICON_BASE}/Xiaoyi.png`, name: "Xiaoyi" },
  { iconSrc: `${CHANNEL_ICON_BASE}/Wattermost.png`, name: "Mattermost" },
  { iconSrc: `${CHANNEL_ICON_BASE}/Discord.png`, name: "Discord" },
  { iconSrc: `${CHANNEL_ICON_BASE}/Feishu.png`, name: "Feishu" },
  { iconSrc: `${CHANNEL_ICON_BASE}/QQ.png`, name: "QQ" },
  { iconSrc: `${CHANNEL_ICON_BASE}/WeCom.png`, name: "WeCom" },
  { iconSrc: `${CHANNEL_ICON_BASE}/DingTalk.png`, name: "DingTalk" },
  { iconSrc: `${CHANNEL_ICON_BASE}/Matrix.png`, name: "Matrix" },
  { iconSrc: `${CHANNEL_ICON_BASE}/Telegram.png`, name: "Telegram" },
];

const BOTTOM_CHANNELS = [
  { iconSrc: `${CHANNEL_ICON_BASE}/Doubao.png`, name: "Doubao" },
  { iconSrc: `${CHANNEL_ICON_BASE}/Deepseek.png`, name: "Deepseek" },
  { iconSrc: `${CHANNEL_ICON_BASE}/ChatFPT.png`, name: "ChatGPT" },
  { iconSrc: `${CHANNEL_ICON_BASE}/Gmail.png`, name: "Gmail" },
  { iconSrc: `${CHANNEL_ICON_BASE}/NetEaseMusic.png`, name: "NetEaseMusic" },
  { iconSrc: `${CHANNEL_ICON_BASE}/Spotify.png`, name: "Spotify" },
  { iconSrc: `${CHANNEL_ICON_BASE}/Github.png`, name: "Github" },
  { iconSrc: `${CHANNEL_ICON_BASE}/iMessage.png`, name: "iMessage" },
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
    transition: { duration: 0.5, ease: "easeOut" },
  },
};

function ChannelPill({ iconSrc, name }: { iconSrc: string; name: string }) {
  return (
    <div className="inline-flex h-11 w-43 shrink-0 items-center justify-center gap-2 rounded-xl border border-[#F5F3EF] bg-white px-4 py-2 text-sm font-normal text-(--color-text-secondary)  md:text-[1.02rem]">
      <img
        src={iconSrc}
        alt=""
        className="h-6 w-6 shrink-0 object-contain md:h-7 md:w-7"
        width={28}
        height={28}
        loading="lazy"
        decoding="async"
        aria-hidden
      />
      <span>{name}</span>
    </div>
  );
}

export function CopawChannels() {
  const { t } = useTranslation();

  return (
    <motion.section
      className="relative px-4 py-10 md:py-24"
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
          className="font-newsreader inline-block text-4xl font-semibold leading-[1.2] text-(--color-text) md:text-4xl"
          variants={itemVariants}
        >
          <span className="inline-flex items-center whitespace-nowrap">
            <span className="mr-2">{t("channels.titleWe")}</span>
            <img
              src="/copaw-logo3.svg"
              alt=""
              className="mb-1.5 block h-5 w-auto shrink-0 pr-0 sm:mb-2 sm:h-6 sm:pr-0.5 md:mb-3 md:h-7 md:translate-y-[1px]"
              aria-hidden
            />
            <span>{t("channels.titleOperateWith")}</span>
          </span>
          <em className="mt-1 block font-normal italic text-[#301601] md:mt-0 md:ml-1 md:inline">
            {t("channels.titleEverything")}
          </em>
        </motion.h2>
        <motion.p
          className="font-inter mx-auto mt-3 max-w-3xl text-sm leading-relaxed text-(--color-text-tertiary) md:text-[1.03rem]"
          variants={itemVariants}
        >
          {t("channels.sub")}
        </motion.p>
      </motion.div>

      <motion.div className="relative mt-12 w-full" variants={itemVariants}>
        <div className="group/row-top overflow-hidden">
          <div className="inline-flex w-max items-center gap-3 whitespace-nowrap py-1 will-change-transform animate-[copaw-channels-marquee-right_62s_linear_infinite] group-hover/row-top:[animation-play-state:paused]">
            {[...TOP_CHANNELS, ...TOP_CHANNELS].map((item, idx) => (
              <ChannelPill
                key={`${item.name}-${idx}`}
                iconSrc={item.iconSrc}
                name={item.name}
              />
            ))}
          </div>
        </div>

        <div className="group/row-bottom mt-3 overflow-hidden">
          <div className="inline-flex w-max items-center gap-3 whitespace-nowrap py-2 will-change-transform animate-[copaw-channels-marquee-left_48s_linear_infinite] group-hover/row-bottom:[animation-play-state:paused]">
            {[...BOTTOM_CHANNELS, ...BOTTOM_CHANNELS].map((item, idx) => (
              <ChannelPill
                key={`${item.name}-bottom-${idx}`}
                iconSrc={item.iconSrc}
                name={item.name}
              />
            ))}
          </div>
        </div>

        <div className="pointer-events-none absolute inset-y-0 left-0 w-32 bg-linear-to-r from-(--bg) to-transparent" />
        <div className="pointer-events-none absolute inset-y-0 right-0 w-32 bg-linear-to-l from-(--bg) to-transparent" />
      </motion.div>
    </motion.section>
  );
}
