import { Tabs } from "antd";
import { Brain, Clock3, LibraryBig, Settings2, Sparkles } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { AgentRequestContext } from "../../api/modules/agentRequestContext";
import AgentConfigPanel from "./AgentConfigPanel";
import ArtifactPanel from "./ArtifactPanel";
import FilePreviewPane from "./FilePreviewPane";
import { buildFileCenterPath, type FileCategory, type FileLocator } from "./fileLocator";
import MemoryPanel from "./MemoryPanel";
import PersonalLibraryPanel from "./PersonalLibraryPanel";
import TemporaryAttachmentsPanel from "./TemporaryAttachmentsPanel";
import styles from "./PersonalWorkspaceNavigator.module.less";

export interface UnifiedFileCenterProps {
  agentId: string;
  requestContext: AgentRequestContext;
  initialLocator?: FileLocator | null;
  onOpen?: (locator: FileLocator) => void;
  syncLocation?: boolean;
}

export default function UnifiedFileCenter({ agentId, requestContext, initialLocator, onOpen, syncLocation = false }: UnifiedFileCenterProps) {
  const { t } = useTranslation();
  const [activeCategory, setActiveCategory] = useState<FileCategory>(initialLocator?.category ?? "attachment");
  const [selectedLocator, setSelectedLocator] = useState<FileLocator | null>(initialLocator ?? null);
  const [libraryRevision, setLibraryRevision] = useState(0);
  const [artifactRevision, setArtifactRevision] = useState(0);

  useEffect(() => {
    if (initialLocator?.agentId === agentId) {
      setActiveCategory(initialLocator.category);
      setSelectedLocator(initialLocator);
    } else {
      setActiveCategory("attachment");
      setSelectedLocator(null);
    }
  }, [agentId, initialLocator]);

  const open = (locator: FileLocator) => {
    setSelectedLocator(locator);
    setActiveCategory(locator.category);
    if (syncLocation) window.history.replaceState(null, "", buildFileCenterPath(locator));
    onOpen?.(locator);
  };
  const label = (icon: ReactNode, text: string) => <span className={styles.tabLabel}>{icon}{text}</span>;
  const categoryPanel = (category: FileCategory, content: ReactNode) => <div className={`${styles.categoryLayout} ${selectedLocator?.category === category ? styles.categoryLayoutWithPreview : ""}`}>
    <div className={styles.categoryList}>{content}</div>
    {selectedLocator?.category === category ? <div className={styles.categoryPreview}>
      <FilePreviewPane locator={selectedLocator} requestContext={requestContext} />
    </div> : null}
  </div>;

  return <div className={styles.surface} style={{ flex: "1 1 auto", width: "100%", minWidth: 0 }} data-testid="unified-file-center" data-selected-item={selectedLocator?.stableId ?? selectedLocator?.relativePath ?? ""}>
    <Tabs className={styles.tabs} activeKey={activeCategory} onChange={(key) => {
      const category = key as FileCategory;
      setActiveCategory(category);
      if (category === "artifact") setArtifactRevision((value) => value + 1);
    }} items={[
      { key: "attachment", label: label(<Clock3 size={15} />, t("files.fileCenter.attachments")), children: categoryPanel("attachment", <TemporaryAttachmentsPanel key={agentId} requestContext={requestContext} onLibraryChanged={() => setLibraryRevision((value) => value + 1)} onOpen={open} />) },
      { key: "library", label: label(<LibraryBig size={15} />, t("files.fileCenter.library")), children: categoryPanel("library", <PersonalLibraryPanel key={agentId} requestContext={requestContext} refreshToken={libraryRevision} onOpen={open} />) },
      { key: "artifact", label: label(<Sparkles size={15} />, t("files.fileCenter.artifacts")), children: categoryPanel("artifact", <ArtifactPanel key={agentId} requestContext={requestContext} refreshToken={artifactRevision} onLibraryChanged={() => setLibraryRevision((value) => value + 1)} onOpen={open} />) },
      { key: "agent_config", label: label(<Settings2 size={15} />, t("files.fileCenter.agentConfig")), children: <div className={styles.workspacePanel}><AgentConfigPanel agentId={agentId} requestContext={requestContext} /></div> },
      { key: "memory", label: label(<Brain size={15} />, t("files.fileCenter.memory")), children: <div className={styles.workspacePanel}><MemoryPanel key={agentId} agentId={agentId} requestContext={requestContext} initialLocator={selectedLocator?.category === "memory" ? selectedLocator : null} onOpen={open} /></div> },
    ]} />
  </div>;
}
