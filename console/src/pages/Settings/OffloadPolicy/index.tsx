import { useTranslation } from "react-i18next";
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
      <OffloadPolicyCard />
    </div>
  );
}
