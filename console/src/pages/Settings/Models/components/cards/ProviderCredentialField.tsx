import { useTranslation } from "react-i18next";
import type { ProviderInfo } from "@/api/types";
import { ProviderApiKeyLink } from "../ProviderApiKeyLink";
import styles from "../../index.module.less";

export function ProviderCredentialField({
  provider,
  onEdit,
}: {
  provider: ProviderInfo;
  onEdit: (provider: ProviderInfo) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className={styles.groupCardField}>
      <span className={styles.groupCardFieldLabel}>
        API Key
        <ProviderApiKeyLink url={provider.meta?.api_key_url} />
      </span>
      <div className={styles.groupCardMono}>
        <span>
          {provider.api_key
            ? "••••••••"
            : t(
                provider.require_api_key === false
                  ? "models.notRequired"
                  : "models.notConfiguredYet",
              )}
        </span>
        <button
          type="button"
          className={styles.groupCardChangeBtn}
          onClick={() => onEdit(provider)}
        >
          {t(provider.api_key ? "models.changeApiKey" : "models.add")}
        </button>
      </div>
    </div>
  );
}
