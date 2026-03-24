import type { ProviderInfo, ActiveModelsInfo } from "../../../../../api/types";
import { LocalProviderCard } from "./LocalProviderCard";
import { RemoteProviderCard } from "./RemoteProviderCard";

interface ProviderCardProps {
  provider: ProviderInfo;
  activeModels: ActiveModelsInfo | null;
  onSaved: () => void;
  isHover: boolean;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
}

export function ProviderCard({
  provider,
  activeModels,
  onSaved,
  isHover,
  onMouseEnter,
  onMouseLeave,
}: ProviderCardProps) {
  if (provider.is_local) {
    return (
      <LocalProviderCard
        provider={provider}
        onSaved={onSaved}
        isHover={isHover}
        onMouseEnter={onMouseEnter}
        onMouseLeave={onMouseLeave}
      />
    );
  }

  return (
    <RemoteProviderCard
      provider={provider}
      activeModels={activeModels}
      onSaved={onSaved}
      isHover={isHover}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    />
  );
}
