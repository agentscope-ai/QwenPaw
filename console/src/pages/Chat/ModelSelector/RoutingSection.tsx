import { CheckOutlined, RightOutlined } from "@ant-design/icons";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { ModelSlotConfig, RoutingMode } from "../../../api/types";
import styles from "./index.module.less";

export type SlotKind = "local" | "cloud";

interface EligibleProvider {
  id: string;
  name: string;
  base_url?: string;
  isLocal: boolean;
  models: Array<{ id: string; name: string; is_free?: boolean }>;
}

interface RoutingSectionProps {
  routingFeatureReady: boolean;
  routingEnabled: boolean;
  routingMode: RoutingMode;
  effectiveLocalSlot: ModelSlotConfig | null;
  effectiveCloudSlot: ModelSlotConfig | null;
  localProviders: EligibleProvider[];
  cloudProviders: EligibleProvider[];
  renderProviderModelMenu: (
    providersList: EligibleProvider[],
    selectedSlot: ModelSlotConfig | null,
    onSelect: (providerId: string, modelId: string) => void,
  ) => ReactNode;
  onActivateRouting: (mode: RoutingMode) => void;
  onSetSlot: (kind: SlotKind, providerId: string, modelId: string) => void;
}

export default function RoutingSection({
  routingFeatureReady,
  routingEnabled,
  routingMode,
  effectiveLocalSlot,
  effectiveCloudSlot,
  localProviders,
  cloudProviders,
  renderProviderModelMenu,
  onActivateRouting,
  onSetSlot,
}: RoutingSectionProps) {
  const { t } = useTranslation();

  const renderProviderGroup = (
    kind: SlotKind,
    providersList: EligibleProvider[],
    selectedSlot: ModelSlotConfig | null,
    title: string,
  ) => {
    if (providersList.length === 0) {
      return null;
    }

    return (
      <>
        <div className={styles.sectionLabel}>{title}</div>
        {renderProviderModelMenu(
          providersList,
          selectedSlot,
          (providerId, modelId) => {
            onSetSlot(kind, providerId, modelId);
          },
        )}
      </>
    );
  };

  const renderRoutingModeItem = (mode: RoutingMode) => {
    const isActive = routingEnabled && routingMode === mode;
    const label =
      mode === "local_first"
        ? t("chatRoutingSelector.localFirst", { defaultValue: "Local First" })
        : t("chatRoutingSelector.cloudFirst", { defaultValue: "Cloud First" });

    return (
      <div
        className={[
          styles.providerItem,
          isActive ? styles.providerItemActive : "",
        ].join(" ")}
        onClick={(e) => {
          e.stopPropagation();
          onActivateRouting(mode);
        }}
      >
        <span className={styles.providerName}>{label}</span>
        {isActive && <CheckOutlined className={styles.checkIcon} />}
        <RightOutlined className={styles.providerArrow} />

        <div
          className={`${styles.submenu} ${styles.routingSubmenu} modelSubmenu`}
        >
          {renderProviderGroup(
            "local",
            localProviders,
            effectiveLocalSlot,
            t("chatRoutingSelector.localProviders", {
              defaultValue: "Local Providers",
            }),
          )}
          {localProviders.length > 0 && cloudProviders.length > 0 ? (
            <div className={styles.sectionDivider} />
          ) : null}
          {renderProviderGroup(
            "cloud",
            cloudProviders,
            effectiveCloudSlot,
            t("chatRoutingSelector.cloudProviders", {
              defaultValue: "Cloud Providers",
            }),
          )}
        </div>
      </div>
    );
  };

  return (
    <div
      className={[
        styles.section,
        !routingFeatureReady ? styles.sectionDisabled : "",
      ].join(" ")}
    >
      <div className={styles.sectionLabel}>
        {t("chatRoutingSelector.routing", { defaultValue: "Routing" })}
        {!routingFeatureReady ? (
          <span className={styles.sectionHint}>
            {t("chatRoutingSelector.configureGlobalFirst", {
              defaultValue: "Set up Local and Cloud in Settings",
            })}
          </span>
        ) : null}
      </div>
      {renderRoutingModeItem("local_first")}
      {renderRoutingModeItem("cloud_first")}
    </div>
  );
}
