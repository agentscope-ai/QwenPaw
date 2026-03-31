import { Download } from "lucide-react";
import { motion } from "motion/react";
import { useTranslation } from "react-i18next";
import Grainient from "@/components/Grainient";

const sectionVariants = {
  hidden: { opacity: 0, y: 0, scale: 1 },
  show: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: {
      duration: 0.5,
      ease: "easeOut",
    },
  },
};

export function CopawFinalCTA() {
  const { t } = useTranslation();

  return (
    <section className="relative overflow-hidden">
      <Grainient
        className="min-h-125 md:min-h-150"
        color1="#ffcd9e"
        color2="#ff9a47"
        color3="#fbcd7f"
        timeSpeed={3.45}
        colorBalance={0.02}
        warpStrength={1}
        warpFrequency={5}
        warpSpeed={1}
        warpAmplitude={50}
        blendAngle={0}
        blendSoftness={0.05}
        rotationAmount={500}
        noiseScale={0.75}
        grainAmount={0.1}
        grainScale={2}
        grainAnimated={false}
        contrast={1.5}
        gamma={1}
        saturation={1}
        centerX={0}
        centerY={0}
        zoom={1.4}
      >
        <motion.div
          className="flex min-h-125 md:min-h-150 h-full w-full items-center justify-center px-4"
          variants={sectionVariants}
          initial="hidden"
          whileInView="show"
          viewport={{ once: true, amount: 0.2 }}
        >
          <div className="flex mx-auto w-full max-w-190">
            <div className="relative min-h-75 w-full overflow-hidden rounded-xl border border-[#ece5dc] bg-white px-5 pb-5 pt-5 sm:px-7 sm:pb-6 sm:pt-6 md:min-h-107.5 md:px-8 md:pb-7 md:pt-7">
              <div className="relative z-10 h-[48%] w-full">
                <h2 className="font-newsreader text-[2rem] font-medium leading-[1.2] text-(--color-text) sm:text-[2.3rem] md:text-[3.05rem]">
                  {t("finalCta.titleBefore")}{" "}
                  <em className="font-newsreader font-medium italic">
                    {t("finalCta.titleEmphasis")}
                  </em>
                  {t("finalCta.titleAfter")}
                  <br />
                  {t("finalCta.titleLine2")}
                </h2>
              </div>
              <a
                href="https://github.com/agentscope-ai/CoPaw/releases"
                target="_blank"
                rel="noopener noreferrer"
                className="font-inter absolute bottom-5 left-5 z-10 inline-flex items-center gap-1.5 rounded-md bg-(--color-primary) px-3 py-1.5 text-xs font-normal text-[#6e3b10] transition hover:brightness-105 sm:bottom-6 sm:left-7 sm:text-sm md:bottom-7 md:left-8"
              >
                <Download size={14} aria-hidden />
                {t("finalCta.downloadFromGithub")}
              </a>

              <video
                src="https://cloud.video.taobao.com/vod/xr9IOUDj4cHliHlhQ0bcd6jfG8_fY7ohNL85pSx-yEs.mp4"
                autoPlay
                loop
                muted
                playsInline
                className="pointer-events-none absolute bottom-0 right-0 h-48 w-auto  select-none object-contain sm:h-48 md:h-64"
              />
            </div>
          </div>
        </motion.div>
      </Grainient>
    </section>
  );
}
