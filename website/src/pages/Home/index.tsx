import { useEffect } from "react";
import { useSiteConfig } from "@/config-context";
import { CopawChannels } from "./components/Channels";
import { CopawClientVoices } from "./components/ClientVoices";
import { CopawContributors } from "./components/Contributors";
import { CopawFAQ } from "./components/FAQ";
import { CopawFinalCTA } from "./components/FinalCTA";
import { CopawHero } from "./components/Hero";
import { CopawQuickStart } from "./components/QuickStart";
import { CopawWhatYouCanDo } from "./components/WhatYouCanDo";
import { CopawWorksForYou } from "./components/WorksForYou";
import { CopawWhy } from "./components/WhyCopaw";

export default function Home() {
  const config = useSiteConfig();
  const docsBase = (config.docsPath ?? "/docs/").replace(/\/$/, "") || "/docs";

  // Config load delays first paint; the browser scrolls to #id before the
  // target exists. Re-apply hash scroll after the home sections mount.
  useEffect(() => {
    const raw = window.location.hash.slice(1);
    if (!raw) return;
    let id: string;
    try {
      id = decodeURIComponent(raw);
    } catch {
      id = raw;
    }
    const scroll = () => {
      document.getElementById(id)?.scrollIntoView({
        behavior: "auto",
        block: "start",
      });
    };
    requestAnimationFrame(() => {
      requestAnimationFrame(scroll);
    });
  }, []);

  return (
    <main className="min-h-screen bg-(--bg) text-(--text)">
      <CopawHero />
      <CopawQuickStart docsBase={docsBase} />
      <CopawChannels />
      <CopawWhy />
      <CopawWhatYouCanDo />
      <CopawWorksForYou />
      <CopawClientVoices />
      <CopawFAQ />
      <CopawContributors />
      <CopawFinalCTA />
    </main>
  );
}
