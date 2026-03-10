import type { SiteConfig } from "../config";
import { type Lang } from "../i18n";
import { Nav } from "../components/Nav";
import { Hero } from "../components/Hero";
import { FollowUs } from "../components/FollowUs";
import { Features } from "../components/Features";
import { UseCases } from "../components/UseCases";
import { Testimonials } from "../components/Testimonials";
import { QuickStart } from "../components/QuickStart";
import { BrandStory } from "../components/BrandStory";
import { Footer } from "../components/Footer";

interface HomeProps {
  config: SiteConfig;
  lang: Lang;
  onLangClick: () => void;
}

export function Home({ config, lang, onLangClick }: HomeProps) {
  return (
    <>
      <Nav
        projectName={config.projectName}
        lang={lang}
        onLangClick={onLangClick}
        docsPath={config.docsPath}
        repoUrl={config.repoUrl}
      />
      <main>
        <Hero
          projectName={config.projectName}
          tagline={
            lang === "zh" ? config.projectTaglineZh : config.projectTaglineEn
          }
          lang={lang}
          docsPath={config.docsPath}
        />
        <QuickStart config={config} lang={lang} />
        <Features lang={lang} />
        <UseCases lang={lang} />
        {config.showTestimonials !== false && <Testimonials lang={lang} />}
        <FollowUs lang={lang} />
        <BrandStory lang={lang} />
      </main>
      <Footer lang={lang} />
    </>
  );
}
