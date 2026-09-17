import { useTranslation } from "react-i18next";
import { Alert } from "antd";
import { PageHeader } from "@/components/PageHeader";
import { OffloadPolicyCard } from "./OffloadPolicyCard";

export default function OffloadPolicyPage() {
  const { t } = useTranslation();

  return (
    <div style={{ padding: "0 4px 24px" }}>
      <PageHeader
        parent={t("nav.settings")}
        current={t("nav.offloadPolicy", "Tool Offload")}
      />
      <Alert
        type="warning"
        showIcon
        message={t(
          "agentConfig.offloadPolicy.adminOnly",
          "Only platform administrators can change this deployment-wide default.",
        )}
        style={{ marginBottom: 16 }}
      />
      <OffloadPolicyCard />
    </div>
  );
}
