import type { ProviderInfo } from "../../../../../api/types";
import { LocalModelManageModal } from "./LocalModelManageModal";
import { RemoteModelManageModal } from "./RemoteModelManageModal";

interface ModelManageModalProps {
  provider: ProviderInfo;
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}

export function ModelManageModal({
  provider,
  open,
  onClose,
  onSaved,
}: ModelManageModalProps) {
  // Route to the appropriate specialized modal based on provider type
  if (provider.id === "qwenpaw-local") {
    return (
      <LocalModelManageModal
        provider={provider}
        open={open}
        onClose={onClose}
        onSaved={onSaved}
      />
    );
  }

  return (
    <RemoteModelManageModal
      provider={provider}
      open={open}
      onClose={onClose}
      onSaved={onSaved}
    />
  );
}
