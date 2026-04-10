import { motion } from "motion/react";
import { useTranslation } from "react-i18next";

const TOP_CHANNELS = [
  {
    iconSrc:
      "https://img.alicdn.com/imgextra/i2/O1CN01ikAjLG1jhh721iEUc_!!6000000004580-2-tps-48-48.png",
    name: "WeChat",
  },
  {
    iconSrc:
      "https://img.alicdn.com/imgextra/i4/O1CN01o4Bmgr1OsabSKSh4X_!!6000000001761-2-tps-58-60.png",
    name: "Xiaoyi",
  },
  {
    iconSrc:
      "https://img.alicdn.com/imgextra/i2/O1CN01qu8Gf51LvqZZqjmU5_!!6000000001362-2-tps-48-48.png",
    name: "Mattermost",
  },
  {
    iconSrc:
      "https://img.alicdn.com/imgextra/i2/O1CN01OsQiMO1ZYrJXp3TmX_!!6000000003207-2-tps-42-48.png",
    name: "Discord",
  },
  {
    iconSrc:
      "https://img.alicdn.com/imgextra/i4/O1CN01wCpTM41LOPeyP7wKc_!!6000000001289-2-tps-48-48.png",
    name: "Feishu",
  },
  {
    iconSrc:
      "https://img.alicdn.com/imgextra/i3/O1CN01ApVkC91JeKBkQfgj9_!!6000000001053-2-tps-41-48.png",
    name: "QQ",
  },
  {
    iconSrc:
      "https://img.alicdn.com/imgextra/i2/O1CN01oWpOyx1TPnmnrzxlq_!!6000000002375-2-tps-48-48.png",
    name: "WeCom",
  },
  {
    iconSrc:
      "https://img.alicdn.com/imgextra/i1/O1CN01w5mzV01tFtE37wkJI_!!6000000005873-2-tps-48-48.png",
    name: "DingTalk",
  },
  {
    iconSrc:
      "https://img.alicdn.com/imgextra/i3/O1CN01YfEzZu1DWdqgAdqtu_!!6000000000224-2-tps-48-48.png",
    name: "Matrix",
  },
  {
    iconSrc:
      "https://img.alicdn.com/imgextra/i4/O1CN013VVoKf1jsgcNn40KA_!!6000000004604-2-tps-48-48.png",
    name: "Telegram",
  },
  {
    iconSrc:
      "https://img.alicdn.com/imgextra/i4/O1CN01QtLiI31uAgL02USNH_!!6000000005997-2-tps-48-48.png",
    name: "iMessage",
  },
  {
    iconSrc:
      "https://img.alicdn.com/imgextra/i4/O1CN014ALZcD1iBnv2GeYdE_!!6000000004375-2-tps-64-64.png",
    name: "MQTT",
  },
  {
    iconSrc:
      "https://img.alicdn.com/imgextra/i2/O1CN01nwY8ZK1eY0etBKDWb_!!6000000003882-2-tps-48-48.png",
    name: "Twilio",
  },
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

export function Channels() {
  const { t, i18n } = useTranslation();
  const isZh = i18n.resolvedLanguage === "zh";

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
          className="font-newsreader text-2xl font-semibold leading-[1.2] text-(--color-text) sm:text-3xl md:text-4xl"
          variants={itemVariants}
        >
          <span className="inline-flex flex-wrap items-center justify-center gap-x-2">
            <span
              className={`inline-flex items-center ${
                isZh
                  ? "whitespace-nowrap"
                  : "flex-col sm:flex-row sm:whitespace-nowrap"
              }`}
            >
              <span className="mr-2">{t("channels.titleWe")}</span>
              <img
                src="https://img.alicdn.com/imgextra/i4/O1CN01aJaU1x1eYT3UlTm19_!!6000000003883-55-tps-771-132.svg"
                alt=""
                className={`inline-block h-5 w-auto shrink-0 pr-0 sm:h-6 sm:pr-0.5 md:h-7 ${
                  isZh
                    ? "mb-1 sm:mb-0 md:mb-1 md:translate-y-0"
                    : "mt-1 sm:mt-0 sm:mb-2 md:mb-3 md:translate-y-[1px]"
                }`}
                aria-hidden
              />
            </span>
            <em className="italic text-[#301601] font-semibold">
              {t("channels.titleEverything")}
            </em>
          </span>
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
          <div className="inline-flex w-max items-center gap-3 whitespace-nowrap py-1 will-change-transform animate-[qwenpaw-channels-marquee-right_72s_linear_infinite] group-hover/row-top:[animation-play-state:paused]">
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
          <div className="inline-flex w-max items-center gap-3 whitespace-nowrap py-2 will-change-transform animate-[qwenpaw-channels-marquee-left_72s_linear_infinite] group-hover/row-bottom:[animation-play-state:paused]">
            {[...TOP_CHANNELS, ...TOP_CHANNELS].map((item, idx) => (
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
