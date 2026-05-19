import React from "react";
import type { ProviderInfo, ActiveModelsInfo } from "../../../../../api/types";
import { LocalProviderCard } from "./LocalProviderCard";
import { RemoteProviderCard } from "./RemoteProviderCard";

interface ProviderCardProps {
  provider: ProviderInfo;
  activeModels: ActiveModelsInfo | null;
  onSaved: () => void;
  onOpenConfig: (provider: ProviderInfo) => void;
  onOpenModels: (provider: ProviderInfo) => void;
}

export const ProviderCard = React.memo(function ProviderCard({
  provider,
  onSaved,
  onOpenConfig,
  onOpenModels,
}: ProviderCardProps) {
  if (provider.id === "qwenpaw-local") {
    return (
      <LocalProviderCard provider={provider} onOpenModels={onOpenModels} />
    );
  }

  return (
    <RemoteProviderCard
      provider={provider}
      onSaved={onSaved}
      onOpenConfig={onOpenConfig}
      onOpenModels={onOpenModels}
    />
  );
});
