import React from "react";
import type { ProviderInfo, ActiveModelsInfo } from "../../../../../api/types";
import { LocalProviderCard } from "./LocalProviderCard";
import { RemoteProviderCard } from "./RemoteProviderCard";

interface ProviderCardProps {
  provider: ProviderInfo;
  activeModels: ActiveModelsInfo | null;
  onSaved: () => void;
}

export const ProviderCard = React.memo(function ProviderCard({
  provider,
  activeModels,
  onSaved,
}: ProviderCardProps) {
  if (provider.id === "qwenpaw-local") {
    return <LocalProviderCard provider={provider} onSaved={onSaved} />;
  }

  return (
    <RemoteProviderCard
      provider={provider}
      activeModels={activeModels}
      onSaved={onSaved}
    />
  );
});
