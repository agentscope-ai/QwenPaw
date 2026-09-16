import { Alert, Tag } from "antd";
import { useTranslation } from "react-i18next";

interface GovernanceConfigAlertProps {
  agentName: string;
  agentId: string;
  ownerUserId: string | null;
}

export function GovernanceConfigAlert({
  agentName,
  agentId,
  ownerUserId,
}: GovernanceConfigAlertProps) {
  const { t } = useTranslation();
  return (
    <Alert
      type="warning"
      showIcon
      message={
        <span>
          <Tag color="orange">{t("agentConfig.governanceBadge")}</Tag>
          {t("agentConfig.governanceTitle")}
        </span>
      }
      description={t("agentConfig.governanceDescription", {
        agentName,
        agentId,
        ownerUserId: ownerUserId || t("common.unknown"),
      })}
    />
  );
}
