import { useState } from "react";
import { Power, Settings } from "lucide-react";
import { Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import { providerApi } from "@/api/modules/provider";
import { useAppMessage } from "@/hooks/useAppMessage";
import styles from "../../index.module.less";

export function ProviderCloseButton({
  ids,
  providerName,
  onSaved,
  onConfigure,
}: {
  ids: string[];
  providerName: string;
  onSaved: () => void;
  onConfigure?: () => void;
}) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [busy, setBusy] = useState(false);
  const settingsLabel = `${t("models.settings")}: ${providerName}`;
  const disableLabel = `${t("models.disableBtn")}: ${providerName}`;
  return (
    <>
      {onConfigure && (
        <Tooltip title={settingsLabel}>
          <button
            type="button"
            className={styles.providerSettings}
            aria-label={settingsLabel}
            onClick={onConfigure}
          >
            <Settings size={16} strokeWidth={1.6} />
          </button>
        </Tooltip>
      )}
      <Tooltip title={disableLabel}>
        <button
          type="button"
          className={styles.providerClose}
          aria-label={disableLabel}
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const results = await Promise.allSettled(
                ids.map((id) =>
                  providerApi.configureProvider(id, { enabled: false }),
                ),
              );
              onSaved();
              const failure = results.find(
                (result) => result.status === "rejected",
              );
              if (failure?.status === "rejected")
                message.error(String(failure.reason));
            } finally {
              setBusy(false);
            }
          }}
        >
          <Power size={16} strokeWidth={1.6} />
        </button>
      </Tooltip>
    </>
  );
}
