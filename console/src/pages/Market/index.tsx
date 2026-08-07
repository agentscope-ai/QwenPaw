import { useSearchParams } from "react-router-dom";
import { MarketplaceHeader } from "./components/MarketplaceHeader";
import AppCenterPage from "../AppCenter";
import PluginManagerPage from "../Settings/PluginManager";
import { MarketPanel } from "../Settings/Market/MarketPanel";
import styles from "./index.module.less";

function SkillMarketplace() {
  return (
    <div className={styles.page}>
      <MarketplaceHeader activeSection="skills" />
      <MarketPanel installTarget="pool" />
    </div>
  );
}

export default function MarketplacePage() {
  const [searchParams] = useSearchParams();
  const tab = searchParams.get("tab");

  if (tab === "plugins") return <PluginManagerPage />;
  if (tab === "skills") return <SkillMarketplace />;
  return <AppCenterPage />;
}
