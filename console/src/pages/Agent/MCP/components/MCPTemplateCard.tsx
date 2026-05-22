import { useTranslation } from "react-i18next";
import type { MCPMarketTemplate } from "../market/mcpTemplates";
import { MCPTemplateIcon } from "../market/templateIcons";
import styles from "./MCPMarketplaceModal.module.less";

interface MCPTemplateCardProps {
  template: MCPMarketTemplate;
  selected: boolean;
  onSelect: () => void;
}

export function MCPTemplateCard({
  template,
  selected,
  onSelect,
}: MCPTemplateCardProps) {
  const { t } = useTranslation();

  return (
    <div
      className={`${styles.templateCard} ${
        selected ? styles.templateCardActive : ""
      }`}
      onClick={onSelect}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
    >
      <MCPTemplateIcon iconId={template.iconId} />
      <div className={styles.templateCardBody}>
        <div className={styles.templateCardName}>{t(template.nameKey)}</div>
        <div className={styles.templateCardDesc}>
          {t(template.descriptionKey)}
        </div>
      </div>
      <span className={styles.templateCardTransport}>
        {template.transport === "stdio"
          ? template.command === "uvx"
            ? "uvx"
            : "Stdio"
          : "HTTP"}
      </span>
    </div>
  );
}
