import { Download } from "lucide-react";
import { motion } from "motion/react";
import Grainient from "@/components/Grainient";

const sectionVariants = {
  hidden: { opacity: 0, y: 16 },
  show: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.45,
      ease: "easeOut",
    },
  },
};

export function CopawFinalCTA() {
  return (
    <motion.section
      className="relative overflow-hidden py-12 md:py-16"
      variants={sectionVariants}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, amount: 0.2 }}
    >
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
        <div className="flex min-h-125 md:min-h-150 h-full w-full items-center justify-center px-4">
          <div className="flex mx-auto w-full max-w-190">
            <div className="relative min-h-75 w-full overflow-hidden rounded-xl border border-[#ece5dc] bg-white px-5 pb-5 pt-5 shadow-[0_8px_24px_rgba(56,33,12,0.08)] sm:px-7 sm:pb-6 sm:pt-6 md:min-h-107.5 md:px-8 md:pb-7 md:pt-7">
              <div className="relative z-10 h-[48%] w-full">
                <h2 className="font-newsreader text-[2rem] leading-[1.08] text-(--color-text) sm:text-[2.3rem]  md:text-[3.05rem]">
                  Get your <em className="font-newsreader font-normal italic">paws up now</em>,
                  <br />
                  power your dev life.
                </h2>
              </div>
              <a
                href="https://github.com/agentscope-ai/CoPaw/releases"
                target="_blank"
                rel="noopener noreferrer"
                className="font-inter absolute bottom-5 left-5 z-10 inline-flex items-center gap-1.5 rounded-md bg-(--color-primary) px-3 py-1.5 text-xs font-semibold text-[#6e3b10] shadow-[0_1px_2px_rgba(0,0,0,0.12)] transition hover:brightness-105 sm:bottom-6 sm:left-7 sm:text-sm md:bottom-7 md:left-8"
              >
                <Download size={14} aria-hidden />
                Download from Github
              </a>

              <img
                src="/copaw-logo2.png"
                alt="CoPaw mascot"
                className="pointer-events-none absolute bottom-0 -right-12 h-58 w-auto translate-y-[33%] select-none object-contain sm:-right-9 sm:h-50 md:-right-6 md:h-98"
                loading="lazy"
              />
            </div>
          </div>
        </div>
      </Grainient>
    </motion.section>
  );
}
