import { useSearchParams } from "react-router-dom";
import { MarketplaceHeader } from "./components/MarketplaceHeader";
import AppCenterPage from "../AppCenter";
import PluginManagerPage from "../Settings/PluginManager";
import { MarketPanel } from "../Settings/Market/MarketPanel";
import type { InstallTarget } from "../Settings/Market/useMarketInstall";
import styles from "./index.module.less";

function getSkillMarketTarget(value: string | null): InstallTarget {
  return value === "pool" ? "pool" : "workspace";
}

function SkillMarketplace({ installTarget }: { installTarget: InstallTarget }) {
  return (
    <div className={styles.page}>
      <MarketplaceHeader activeSection="skills" />
      <MarketPanel installTarget={installTarget} />
    </div>
  );
}

export default function MarketplacePage() {
  const [searchParams] = useSearchParams();
  const tab = searchParams.get("tab");

  if (tab === "plugins") return <PluginManagerPage />;
  if (tab === "skills") {
    return (
      <SkillMarketplace
        installTarget={getSkillMarketTarget(searchParams.get("target"))}
      />
    );
  }
  return <AppCenterPage />;
}
