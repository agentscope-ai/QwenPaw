import { useSiteConfig } from "@/config-context";
import { CopawChannels } from "./components/Channels";
import { CopawClientVoices } from "./components/ClientVoices";
import { CopawFAQ } from "./components/FAQ";
import { CopawFinalCTA } from "./components/FinalCTA";
import { CopawHero } from "./components/Hero";
import { CopawQuickStart } from "./components/QuickStart";
import { CopawWhatYouCanDo } from "./components/WhatYouCanDo";
import { CopawWorksForYou } from "./components/WorksForYou";
import { CopawWhy } from "./components/WhyCopaw";

export function Home() {
  const config = useSiteConfig();
  const docsBase = (config.docsPath ?? "/docs/").replace(/\/$/, "") || "/docs";

  return (
    <main className="min-h-screen bg-(--bg) text-(--text)">
      <CopawHero pipInstallTo={`${docsBase}/quickstart`} />
      <CopawQuickStart docsBase={docsBase} />
      <CopawChannels />
      <CopawWhy />
      <CopawWhatYouCanDo />
      <CopawWorksForYou />
      <CopawClientVoices />
      <CopawFAQ />
      <CopawFinalCTA />
    </main>
  );
}
