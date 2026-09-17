import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { DOWNLOADS_HEADER_BG_URL } from "../constants";

export type DownloadsTab = "desktop" | "plugins";

export const DOWNLOADS_TAB_IDS = {
  desktop: "downloads-tab-desktop",
  plugins: "downloads-tab-plugins",
} as const satisfies Record<DownloadsTab, string>;

export const DOWNLOADS_PANEL_IDS = {
  desktop: "downloads-panel-desktop",
  plugins: "downloads-panel-plugins",
} as const satisfies Record<DownloadsTab, string>;

interface DownloadsHeaderProps {
  activeTab: DownloadsTab;
  onTabChange: (tab: DownloadsTab) => void;
  showDesktopTab: boolean;
  showPluginsTab: boolean;
}

export function DownloadsHeader({
  activeTab,
  onTabChange,
  showDesktopTab,
  showPluginsTab,
}: DownloadsHeaderProps) {
  const { t } = useTranslation();
  const showTabs = showDesktopTab && showPluginsTab;

  const tabClass = (tab: DownloadsTab) =>
    cn(
      "relative px-1 pb-3 text-base font-medium transition-colors",
      activeTab === tab
        ? "text-(--color-primary) after:absolute after:-inset-x-3 after:bottom-0 after:h-[3px] after:rounded-full after:bg-(--color-primary)"
        : "text-site-text-muted hover:text-site-text",
    );

  return (
    <header className="relative -mt-4 mb-10 pt-8 text-center sm:-mt-6 lg:-mt-8">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 left-[calc(50%-50vw)] -z-10 w-screen bg-cover bg-bottom bg-no-repeat"
        style={{ backgroundImage: `url(${DOWNLOADS_HEADER_BG_URL})` }}
      />
      <h1 className="relative mb-3 mt-8 text-4xl font-bold tracking-tight text-site-text md:text-[2.75rem]">
        {t("downloads.title")}
      </h1>
      <p className="relative mb-10 text-base text-site-text-muted md:text-lg">
        {t("downloads.subtitle")}
      </p>

      {showTabs && (
        <nav className="relative" aria-label={t("downloads.tabNavLabel")}>
          <div
            className="pointer-events-none absolute bottom-0 left-[calc(50%-50vw)] h-px w-screen bg-border"
            aria-hidden
          />
          <div
            role="tablist"
            className="relative mx-auto flex max-w-md justify-center gap-10"
          >
            {showDesktopTab && (
              <button
                type="button"
                id={DOWNLOADS_TAB_IDS.desktop}
                className={tabClass("desktop")}
                role="tab"
                aria-selected={activeTab === "desktop"}
                aria-controls={DOWNLOADS_PANEL_IDS.desktop}
                onClick={() => onTabChange("desktop")}
              >
                {t("downloads.desktopTitle")}
              </button>
            )}
            {showPluginsTab && (
              <button
                type="button"
                id={DOWNLOADS_TAB_IDS.plugins}
                className={tabClass("plugins")}
                role="tab"
                aria-selected={activeTab === "plugins"}
                aria-controls={DOWNLOADS_PANEL_IDS.plugins}
                onClick={() => onTabChange("plugins")}
              >
                {t("downloads.pluginsTitle")}
              </button>
            )}
          </div>
        </nav>
      )}
    </header>
  );
}
