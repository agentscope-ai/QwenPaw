import { useEffect } from "react";
import { useSiteConfig } from "@/config-context";
import { Channels } from "./components/Channels";
import { ClientVoices } from "./components/ClientVoices";
import { Contributors } from "./components/Contributors";
import { FAQ } from "./components/FAQ";
import { FinalCTA } from "./components/FinalCTA";
import { Hero } from "./components/Hero";
import { QuickStart } from "./components/QuickStart";
import { WhatYouCanDo } from "./components/WhatYouCanDo";
import { WorksForYou } from "./components/WorksForYou";
import { Why } from "./components/Why";

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
      <Hero />
      <QuickStart docsBase={docsBase} />
      <Channels />
      <Why />
      <WhatYouCanDo />
      <WorksForYou />
      <ClientVoices />
      <FAQ />
      <Contributors />
      <FinalCTA />
    </main>
  );
}
