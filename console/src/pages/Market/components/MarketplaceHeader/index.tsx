import type { ReactNode } from "react";
import { Tabs, type TabsProps } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { useIsMobile } from "@/hooks/useIsMobile";
import styles from "./index.module.less";

export type MarketplaceSection = "apps" | "plugins" | "skills" | "community";

const SECTION_PATHS: Record<MarketplaceSection, string> = {
  community: "/market?tab=community",
  apps: "/market",
  plugins: "/market?tab=plugins",
  skills: "/market?tab=skills",
};

interface MarketplaceHeaderProps {
  activeSection: MarketplaceSection;
  extra?: ReactNode;
}

export function MarketplaceHeader({
  activeSection,
  extra,
}: MarketplaceHeaderProps) {
  const { t } = useTranslation();
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const items: TabsProps["items"] = [
    { key: "apps", label: t("nav.apps", "Apps") },
    { key: "plugins", label: t("nav.plugins", "Plugins") },
    { key: "skills", label: t("nav.skills", "Skills") },
    ...(!isMobile
      ? [{ key: "community", label: t("communityCompose.nav", "Community") }]
      : []),
  ];

  const handleChange = (section: string) => {
    const path = SECTION_PATHS[section as MarketplaceSection];
    const target = searchParams.get("target");
    const targetSuffix =
      target === "pool" || target === "workspace"
        ? `${path.includes("?") ? "&" : "?"}target=${target}`
        : "";
    navigate(`${path}${targetSuffix}`);
  };

  return (
    <PageHeader
      current={t("nav.marketplace", "Extension")}
      center={
        <div className={styles.navigation}>
          <Tabs
            className={styles.sectionSwitch}
            activeKey={activeSection}
            items={items}
            onChange={handleChange}
            type="segmented"
          />
        </div>
      }
      extra={extra}
    />
  );
}
