import { Puzzle } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { DesktopIndex } from "../types";
import {
  formatPlatformKindLabel,
  getFilesForPluginPlatform,
  getPluginPlatformKinds,
  groupFilesByPluginId,
  latestFileIdByPluginId,
  orderVersionsWithDefault,
} from "../utils";
import { DownloadCard } from "./DownloadCard";
import { PlatformGrid, ProductSection } from "./ProductSection";

interface PluginsSectionProps {
  pluginsIndex: DesktopIndex;
}

export function PluginsSection({ pluginsIndex }: PluginsSectionProps) {
  const { t } = useTranslation();
  const kinds = getPluginPlatformKinds(pluginsIndex);

  return (
    <ProductSection
      title={t("downloads.pluginsTitle")}
      description={t("downloads.pluginsDesc")}
      className="mb-12"
    >
      {kinds.map((kind, index) => {
        const files = getFilesForPluginPlatform(pluginsIndex, kind);
        if (files.length === 0) return null;

        const latestByPluginId = latestFileIdByPluginId(files);
        const kindLabel = formatPlatformKindLabel(kind);

        return (
          <div key={kind} className={index > 0 ? "mt-6" : undefined}>
            <PlatformGrid>
              {groupFilesByPluginId(files).map(({ pluginId, versions }) => {
                const latestStableId = latestByPluginId.get(pluginId) ?? null;
                return (
                  <DownloadCard
                    key={pluginId}
                    versions={orderVersionsWithDefault(
                      versions,
                      latestStableId ?? undefined,
                    )}
                    latestStableFileId={latestStableId}
                    icon={Puzzle}
                    kindLabel={kindLabel}
                    downloadLabelKey="downloads.downloadZip"
                  />
                );
              })}
            </PlatformGrid>
          </div>
        );
      })}
    </ProductSection>
  );
}
