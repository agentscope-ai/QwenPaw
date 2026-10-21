import { useState } from "react";
import { Power, Settings } from "lucide-react";
import { useTranslation } from "react-i18next";
import { IconButton } from "@/components/interaction/IconButton";
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
        <IconButton
          icon={Settings}
          label={settingsLabel}
          className={styles.providerSettings}
          onClick={onConfigure}
        />
      )}
      <IconButton
        icon={Power}
        label={disableLabel}
        className={styles.providerClose}
        loading={busy}
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
      />
    </>
  );
}
