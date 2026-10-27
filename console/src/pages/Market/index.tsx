import { useSearchParams } from "react-router-dom";
import { MarketplaceHeader } from "./components/MarketplaceHeader";
import AppCenterPage from "../AppCenter";
import PluginManagerPage from "../Settings/PluginManager";
import { InstallQueuePanel, MarketPanel } from "../Settings/Market/MarketPanel";
import {
  useMarketInstall,
  type InstallTarget,
  type MarketInstallController,
} from "../Settings/Market/useMarketInstall";
import { useAgentStore } from "../../stores/agentStore";
import styles from "./index.module.less";

function getSkillMarketTarget(value: string | null): InstallTarget {
  return value === "pool" ? "pool" : "workspace";
}

function SkillMarketplace({
  installTarget,
  install,
}: {
  installTarget: InstallTarget;
  install: MarketInstallController;
}) {
  return (
    <div className={styles.page}>
      <MarketplaceHeader activeSection="skills" />
      <MarketPanel installTarget={installTarget} install={install} />
    </div>
  );
}

export default function MarketplacePage() {
  const [searchParams] = useSearchParams();
  const tab = searchParams.get("tab");
  const selectedAgent = useAgentStore((state) => state.selectedAgent);
  const install = useMarketInstall({ selectedAgent });

  let content = <AppCenterPage />;
  if (tab === "plugins") {
    content = <PluginManagerPage />;
  } else if (tab === "skills") {
    content = (
      <SkillMarketplace
        installTarget={getSkillMarketTarget(searchParams.get("target"))}
        install={install}
      />
    );
  }

  return (
    <>
      {content}
      {install.queue.length > 0 && (
        <InstallQueuePanel
          queue={install.queue}
          onClearCompleted={install.clearFinished}
          onCancel={install.cancel}
          onRetry={install.retry}
        />
      )}
    </>
  );
}
