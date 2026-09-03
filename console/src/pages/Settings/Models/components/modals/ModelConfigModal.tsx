import { Modal } from "antd";
import { useTranslation } from "react-i18next";

import type { ModelInfo, ProviderInfo } from "../../../../../api/types";
import { useTheme } from "../../../../../contexts/ThemeContext";
import { ModelConfigEditor } from "./ModelConfigEditor";

interface ModelConfigModalProps {
  open: boolean;
  provider: ProviderInfo | null;
  model: ModelInfo | null;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
  onProviderUpdated?: (provider: ProviderInfo) => void;
}

export function ModelConfigModal({
  open,
  provider,
  model,
  onClose,
  onSaved,
  onProviderUpdated,
}: ModelConfigModalProps) {
  const { t } = useTranslation();
  const { isDark } = useTheme();

  return (
    <Modal
      open={open}
      title={t("models.modelConfigTitle", {
        model: model?.name || model?.id || "",
      })}
      footer={null}
      width={640}
      destroyOnHidden
      onCancel={onClose}
    >
      {provider && model && (
        <ModelConfigEditor
          providerId={provider.id}
          model={model}
          onSaved={onSaved}
          onProviderUpdated={onProviderUpdated}
          onClose={onClose}
          isDark={isDark}
          chatModel={provider.chat_model}
        />
      )}
    </Modal>
  );
}
