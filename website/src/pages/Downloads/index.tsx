import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { useSiteConfig } from "@/config-context";
import { CDN_BASE, PLATFORM_ICONS } from "./constants";
import { DownloadCard } from "./components/DownloadCard";
import {
  DOWNLOADS_PANEL_IDS,
  DOWNLOADS_TAB_IDS,
  DownloadsHeader,
  type DownloadsTab,
} from "./components/DownloadsHeader";
import { PluginsSection } from "./components/PluginsSection";
import { PlatformGrid, ProductSection } from "./components/ProductSection";
import type { DesktopIndex, FileMetadata, MainIndex } from "./types";
import {
  compareVersionDesc,
  detectOS,
  isPreviewVersion,
  orderVersionsWithDefault,
} from "./utils";

const OTHER_METHODS = [
  {
    emoji: "📦",
    titleKey: "downloads.pip" as const,
    descKey: "downloads.pipDesc" as const,
    hash: { zh: "方式一pip-安装", en: "Option-1-pip-install" },
  },
  {
    emoji: "📜",
    titleKey: "downloads.script" as const,
    descKey: "downloads.scriptDesc" as const,
    hash: { zh: "方式二脚本安装", en: "Option-2-Script-install" },
  },
  {
    emoji: "🐳",
    titleKey: "downloads.docker" as const,
    descKey: "downloads.dockerDesc" as const,
    hash: { zh: "方式三Docker", en: "Option-3-Docker" },
  },
  {
    emoji: "☁️",
    titleKey: "downloads.cloud" as const,
    descKey: "downloads.cloudDesc" as const,
    hash: {
      zh: "方式四部署到阿里云-ECS",
      en: "Option-4-Deploy-to-Alibaba-Cloud-ECS",
    },
  },
] as const;

async function fetchProductIndex(
  indexUrl: string,
): Promise<DesktopIndex | null> {
  const response = await fetch(`${CDN_BASE}${indexUrl}`);
  if (!response.ok) {
    console.warn("Product index fetch failed:", response.status, indexUrl);
    return null;
  }
  return response.json();
}

export default function Downloads() {
  const { t, i18n } = useTranslation();
  const isZh = i18n.resolvedLanguage === "zh";
  const { docsPath } = useSiteConfig();
  const [loading, setLoading] = useState(true);
  const [isEmpty, setIsEmpty] = useState(false);
  const [desktopIndex, setDesktopIndex] = useState<DesktopIndex | null>(null);
  const [pluginsIndex, setPluginsIndex] = useState<DesktopIndex | null>(null);
  const [activeTab, setActiveTab] = useState<DownloadsTab>("desktop");
  const userOS = detectOS();

  const hasDesktop =
    Boolean(desktopIndex) &&
    Object.keys(desktopIndex?.platforms ?? {}).length > 0;
  const hasPlugins =
    Boolean(pluginsIndex) && Object.keys(pluginsIndex?.files ?? {}).length > 0;
  const docsBase = docsPath.replace(/\/$/, "") || "/docs";

  useEffect(() => {
    let cancelled = false;

    async function loadDownloads() {
      try {
        const mainIndexResponse = await fetch(
          `${CDN_BASE}/metadata/index.json`,
        );

        if (!mainIndexResponse.ok) {
          if (mainIndexResponse.status === 404) {
            console.warn("Main index not found (404)");
          } else {
            throw new Error("Failed to fetch main index");
          }
          if (!cancelled) {
            setIsEmpty(true);
            setLoading(false);
          }
          return;
        }

        const mainIndex: MainIndex = await mainIndexResponse.json();
        const [desktopData, pluginsData] = await Promise.all([
          mainIndex.products?.desktop
            ? fetchProductIndex(mainIndex.products.desktop.index_url)
            : Promise.resolve(null),
          mainIndex.products?.plugins
            ? fetchProductIndex(mainIndex.products.plugins.index_url)
            : Promise.resolve(null),
        ]);
        if (cancelled) return;

        if (desktopData) setDesktopIndex(desktopData);
        if (pluginsData) setPluginsIndex(pluginsData);

        const hasDesktopData = Boolean(desktopData);
        const hasPluginsData = Object.keys(pluginsData?.files ?? {}).length > 0;

        if (!hasDesktopData && !hasPluginsData) {
          console.warn("No downloadable data available, showing empty state");
          setIsEmpty(true);
        } else if (!hasDesktopData && hasPluginsData) {
          setActiveTab("plugins");
        }

        setLoading(false);
      } catch (err) {
        console.error("Error loading downloads:", err);
        if (!cancelled) {
          setIsEmpty(true);
          setLoading(false);
        }
      }
    }

    loadDownloads();
    return () => {
      cancelled = true;
    };
  }, []);

  const showDesktopPanel =
    hasDesktop && (activeTab === "desktop" || !hasPlugins);
  const showPluginsPanel =
    hasPlugins && (activeTab === "plugins" || !hasDesktop);

  return (
    <div className="flex min-h-screen flex-col">
      <div className="mx-auto w-full max-w-7xl flex-1 p-4 sm:p-6 lg:p-8">
        {!loading && !isEmpty && (
          <DownloadsHeader
            activeTab={activeTab}
            onTabChange={setActiveTab}
            showDesktopTab={hasDesktop}
            showPluginsTab={hasPlugins}
          />
        )}

        {(loading || isEmpty) && (
          <header className="mb-12 pt-8 text-center">
            <h1 className="mb-3 text-4xl font-bold tracking-tight text-site-text md:text-[2.75rem]">
              {t("downloads.title")}
            </h1>
            <p className="text-base text-site-text-muted md:text-lg">
              {t("downloads.subtitle")}
            </p>
          </header>
        )}

        {loading && (
          <div className="py-16 text-center">
            <div
              className="mx-auto mb-4 size-12 animate-spin rounded-full border-4 border-border border-t-accent"
              role="status"
              aria-label={t("downloads.loading")}
            />
            <p>{t("downloads.loading")}</p>
          </div>
        )}

        {isEmpty && !loading && (
          <div className="mx-auto my-8 max-w-xl py-16 text-center">
            <div className="mb-4 text-6xl opacity-50">📦</div>
            <h3 className="mb-3 text-2xl font-semibold text-site-text">
              {t("downloads.emptyTitle")}
            </h3>
            <p className="mb-6 leading-relaxed text-site-text-muted">
              {t("downloads.emptyDesc")}
            </p>
            <Link
              to={`${docsBase}/quickstart`}
              className="inline-block rounded-md bg-accent px-6 py-3 font-semibold text-white no-underline transition-all hover:-translate-y-px hover:bg-site-text"
            >
              {t("downloads.emptyCta")}
            </Link>
          </div>
        )}

        {!loading && !isEmpty && (
          <section className="mb-16">
            {showDesktopPanel && desktopIndex && (
              <div
                id={DOWNLOADS_PANEL_IDS.desktop}
                role="tabpanel"
                aria-labelledby={DOWNLOADS_TAB_IDS.desktop}
              >
                <ProductSection
                  title={t("downloads.desktopTitle")}
                  description={t("downloads.desktopDesc")}
                  className="mb-12"
                >
                  <PlatformGrid>
                    {Object.entries(desktopIndex.platforms).map(
                      ([platform, platformData]) => {
                        const platformVersions = (platformData.versions || [])
                          .map((fileId) => desktopIndex.files[fileId])
                          .filter((item): item is FileMetadata => Boolean(item))
                          .sort((a, b) =>
                            compareVersionDesc(a.version, b.version),
                          );

                        if (platformVersions.length === 0) return null;

                        const latestStable = platformVersions.find(
                          (item) => !isPreviewVersion(item.version),
                        );

                        return (
                          <DownloadCard
                            key={platform}
                            versions={orderVersionsWithDefault(
                              platformVersions,
                              latestStable?.id,
                            )}
                            latestStableFileId={latestStable?.id ?? null}
                            icon={
                              PLATFORM_ICONS[platform] ?? PLATFORM_ICONS.win
                            }
                            isRecommended={platform === userOS}
                          />
                        );
                      },
                    )}
                  </PlatformGrid>
                </ProductSection>
              </div>
            )}

            {showPluginsPanel && pluginsIndex && (
              <div
                id={DOWNLOADS_PANEL_IDS.plugins}
                role="tabpanel"
                aria-labelledby={DOWNLOADS_TAB_IDS.plugins}
              >
                <PluginsSection pluginsIndex={pluginsIndex} />
              </div>
            )}

            <ProductSection
              title={t("downloads.otherMethodsTitle")}
              description={t("downloads.otherMethodsDesc")}
            >
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
                {OTHER_METHODS.map(({ emoji, titleKey, descKey, hash }) => (
                  <Link
                    key={titleKey}
                    to={`${docsBase}/quickstart#${isZh ? hash.zh : hash.en}`}
                    className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-5 text-inherit no-underline transition-all hover:-translate-y-px hover:border-(--color-primary) hover:shadow-sm"
                  >
                    <div className="text-2xl">{emoji}</div>
                    <h4 className="m-0 text-lg font-semibold">{t(titleKey)}</h4>
                    <p className="m-0 text-sm leading-relaxed text-site-text-muted">
                      {t(descKey)}
                    </p>
                  </Link>
                ))}
              </div>
            </ProductSection>

            <section className="mt-12 grid grid-cols-1 gap-6 md:grid-cols-2">
              <div className="rounded-lg border border-border bg-surface p-6">
                <h4 className="mb-3 text-lg font-semibold">
                  {t("downloads.verifyTitle")}
                </h4>
                <p className="m-0 text-[15px] leading-relaxed text-site-text-muted">
                  {t("downloads.verifyDesc")}
                </p>
              </div>
              <div className="rounded-lg border border-border bg-surface p-6">
                <h4 className="mb-3 text-lg font-semibold">
                  {t("downloads.helpTitle")}
                </h4>
                <p className="m-0 text-[15px] leading-relaxed text-site-text-muted">
                  {t("downloads.helpPrefix")}{" "}
                  <Link
                    to={`${docsBase}/quickstart`}
                    className="font-medium text-accent no-underline hover:text-site-text-muted"
                  >
                    {t("downloads.helpLink")}
                  </Link>{" "}
                  {t("downloads.helpSuffix")}
                </p>
              </div>
            </section>
          </section>
        )}
      </div>
    </div>
  );
}
