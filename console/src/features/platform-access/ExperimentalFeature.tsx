import { Tooltip } from "antd";
import { FlaskConical } from "lucide-react";
import { useTranslation } from "react-i18next";

export function ExperimentalFeature() {
  const { t } = useTranslation();
  return (
    <Tooltip title={t("platformAccess.betaNotice")}>
      <span tabIndex={0} role="img" aria-label="Beta">
        <FlaskConical size={15} />
      </span>
    </Tooltip>
  );
}
