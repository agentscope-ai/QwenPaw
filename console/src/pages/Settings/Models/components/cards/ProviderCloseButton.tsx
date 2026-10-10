import { useState } from "react";
import { Power, Settings } from "lucide-react";
import { Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import { providerApi } from "@/api/modules/provider";
import { useAppMessage } from "@/hooks/useAppMessage";
import styles from "../../index.module.less";

export function ProviderCloseButton({
  ids,
  onSaved,
  onConfigure,
}: {
  ids: string[];
  onSaved: () => void;
  onConfigure?: () => void;
}) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [busy, setBusy] = useState(false);
  return (
    <>
      {onConfigure && (
        <Tooltip title={t("models.settings")}>
          <button
            type="button"
            className={styles.providerSettings}
            aria-label={t("models.settings")}
            onClick={onConfigure}
          >
            <Settings size={16} strokeWidth={1.6} />
          </button>
        </Tooltip>
      )}
      <Tooltip title={t("common.disable")}>
        <button
          type="button"
          className={styles.providerClose}
          aria-label={t("common.disable")}
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
