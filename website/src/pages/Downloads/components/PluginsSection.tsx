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
      <PlatformGrid>
        {kinds.flatMap((kind) => {
          const files = getFilesForPluginPlatform(pluginsIndex, kind);
          if (files.length === 0) return [];

          const latestByPluginId = latestFileIdByPluginId(files);
          const kindLabel = formatPlatformKindLabel(kind);

          return groupFilesByPluginId(files).map(({ pluginId, versions }) => {
            const latestStableId = latestByPluginId.get(pluginId) ?? null;
            return (
              <DownloadCard
                key={`${kind}-${pluginId}`}
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
          });
        })}
      </PlatformGrid>
    </ProductSection>
  );
}
