import { motion } from "motion/react";
import { useTranslation } from "react-i18next";
import { sectionStyles } from "@/lib/utils";

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

const AVATARS = [
  {
    key: "a1",
    src: "/communityIcon/1.svg",
    alt: "CoPaw user avatar 1",
  },
  {
    key: "a2",
    src: "/communityIcon/2.svg",
    alt: "CoPaw user avatar 2",
  },
  {
    key: "a3",
    src: "/communityIcon/3.svg",
    alt: "CoPaw user avatar 3",
  },
  {
    key: "a4",
    src: "/communityIcon/4.svg",
    alt: "CoPaw user avatar 4",
  },
  {
    key: "a5",
    src: "/communityIcon/5.svg",
    alt: "CoPaw user avatar 5",
  },
] as const;

const TESTIMONIALS = [
  {
    key: "t1",
    name: "@Shidan Guo",
    avatarSrc: "/communityIcon/1.svg",
    avatarAlt: "Shidan Guo avatar",
  },
  {
    key: "t2",
    name: "@Hubm",
    avatarSrc: "/communityIcon/2.svg",
    avatarAlt: "Hubm avatar",
  },
  {
    key: "t3",
    name: "@ends of the earth",
    avatarSrc: "/communityIcon/3.svg",
    avatarAlt: "ends of the earth avatar",
  },
  {
    key: "t4",
    name: "@FortiCore",
    avatarSrc: "/communityIcon/4.svg",
    avatarAlt: "FortiCore avatar",
  },
  {
    key: "t5",
    name: "@soro",
    avatarSrc: "/communityIcon/5.svg",
    avatarAlt: "soro avatar",
  },
  {
    key: "t6",
    name: "@xiangli",
    avatarSrc: "/communityIcon/6.svg",
    avatarAlt: "xiangli avatar",
  },
] as const;

export function CopawClientVoices() {
  const { t } = useTranslation();

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
          <div className="inline-flex items-center relative py-6">
            <div className="inline-flex items-center rounded-full border border-[#EBEBEB] bg-[#FEFBF9] px-2 py-1 shadow-[0px_0px_2px_0px_rgba(170,170,170,0.25)]  transform-[rotate(-8deg)]">
              <div className="flex -space-x-2.5">
                {AVATARS.slice(0, 3).map((avatar) => (
                  <img
                    key={avatar.key}
                    src={avatar.src}
                    alt={avatar.alt}
                    className="h-8 w-8 rounded-full object-cover md:h-9 md:w-9"
                    loading="lazy"
                  />
                ))}
              </div>
            </div>
            <div className="inline-flex items-center rounded-full border border-[#EBEBEB] bg-[#FEFBF9] px-2 py-1 shadow-[0px_0px_2px_0px_rgba(170,170,170,0.25)]  transform-[rotate(8deg)] -ml-2.5">
              <div className="flex -space-x-2.5">
                {AVATARS.slice(3, 5).map((avatar) => (
                  <img
                    key={avatar.key}
                    src={avatar.src}
                    alt={avatar.alt}
                    className="h-8 w-8 rounded-full object-cover md:h-9 md:w-9"
                    loading="lazy"
                  />
                ))}
              </div>
            </div>
          </div>

          <h2
            id="copaw-client-voices-heading"
            className={`${sectionStyles.title} text-left`}
          >
            {t("clientVoices.title")}
          </h2>
          <p className={`${sectionStyles.subtitle} mt-2 text-left`}>
            {t("clientVoices.sub")}
          </p>
        </motion.div>

        <motion.div
          className="mt-7 grid gap-4 sm:grid-cols-2 md:mt-8 md:grid-cols-3 md:gap-5"
          variants={itemVariants}
        >
          {TESTIMONIALS.map((item) => (
            <article
              key={item.key}
              className="flex min-h-55 flex-col rounded-2xl border border-[#F3F1F0] bg-white p-4  md:min-h-60 md:p-5"
            >
              <p className="font-newsreader text-[0.98rem] leading-[1.75] text-(--color-text-secondary)">
                {t(`clientVoices.items.${item.key}.text`)}
              </p>
              <div className="mt-auto flex items-center gap-3 pt-6">
                <img
                  src={item.avatarSrc}
                  alt={item.avatarAlt}
                  className="h-8 w-8 rounded-full object-cover"
                  loading="lazy"
                />
                <div className="leading-tight">
                  <p className="font-inter text-[0.98rem] font-medium text-(--color-text)">
                    {item.name}
                  </p>
                  <p className="font-inter mt-1 text-sm text-(--color-text-tertiary)">
                    {t(`clientVoices.items.${item.key}.role`)}
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
