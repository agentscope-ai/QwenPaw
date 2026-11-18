import { useState } from "react";
import { useTranslation } from "react-i18next";
import { providerApi } from "@/api/modules/provider";
import type { ProviderInfo } from "@/api/types";
import { useAppMessage } from "@/hooks/useAppMessage";
import { ProviderApiKeyLink } from "../ProviderApiKeyLink";
import { getValidApiKeyPrefixes, validateApiKey } from "../../apiKeyValidation";
import styles from "../../index.module.less";

export function ProviderCredentialField({
  provider,
  onSaved,
}: {
  provider: ProviderInfo;
  onSaved: () => void | Promise<void>;
}) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [editing, setEditing] = useState(false);
  const [draftApiKey, setDraftApiKey] = useState("");
  const [saving, setSaving] = useState(false);

  const stopEditing = () => {
    setDraftApiKey("");
    setEditing(false);
  };

  const saveApiKey = async () => {
    const apiKey = draftApiKey.trim();
    if (!apiKey) return;

    const validation = validateApiKey(
      apiKey,
      getValidApiKeyPrefixes(provider),
      provider.auth_mode ?? "api_key",
    );
    if (!validation.valid) {
      message.error(
        t("models.apiKeyShouldStart", { prefix: validation.prefix }),
      );
      return;
    }

    setSaving(true);
    try {
      await providerApi.configureProvider(provider.id, { api_key: apiKey });
      await onSaved();
      stopEditing();
      message.success(t("models.configurationSaved", { name: provider.name }));
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : t("models.failedToSaveConfig");
      message.error(errorMessage);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={styles.groupCardField}>
      <span className={styles.groupCardFieldLabel}>
        API Key
        <ProviderApiKeyLink url={provider.meta?.api_key_url} />
      </span>
      <div className={styles.groupCardMono}>
        {editing ? (
          <div className={styles.groupCardKeyInput}>
            <input
              autoFocus
              autoComplete="off"
              spellCheck={false}
              type="password"
              className={styles.groupCardKeyField}
              aria-label={t("models.apiKey")}
              placeholder={
                provider.api_key
                  ? t("models.leaveBlankKeep")
                  : t(
                      provider.require_api_key === false
                        ? "models.enterApiKeyOptional"
                        : "models.enterApiKeyRequired",
                    )
              }
              value={draftApiKey}
              disabled={saving}
              onChange={(event) => setDraftApiKey(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void saveApiKey();
                if (event.key === "Escape") stopEditing();
              }}
            />
            <div className={styles.groupCardKeyActions}>
              <button
                type="button"
                className={styles.groupCardChangeBtn}
                disabled={saving || !draftApiKey.trim()}
                onClick={() => void saveApiKey()}
              >
                {saving ? t("common.saving") : t("models.saveApiKey")}
              </button>
              <button
                type="button"
                className={styles.groupCardKeyCancelBtn}
                disabled={saving}
                onClick={stopEditing}
              >
                {t("models.cancel")}
              </button>
            </div>
          </div>
        ) : (
          <>
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
              onClick={() => setEditing(true)}
            >
              {t(provider.api_key ? "models.changeApiKey" : "models.add")}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
