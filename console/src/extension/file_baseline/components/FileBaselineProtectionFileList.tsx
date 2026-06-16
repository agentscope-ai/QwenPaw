import { useMemo, useState } from "react";
import { Button, Switch, Tooltip } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import {
  FILE_BASELINE_PRESET_PATHS,
  FILE_BASELINE_PRESET_PATH_SET,
} from "../constants/pathCandidates";
import { useFileBaselineProtectionContext } from "./FileBaselineProtectionSection";
import { WorkspaceProtectableFilePickerModal } from "./WorkspaceProtectableFilePickerModal";
import styles from "./FileBaselineProtectionFileList.module.less";

function FileBaselinePathRow({
  path,
  title,
  description,
  protected: isProtected,
  loading,
  onToggle,
}: {
  path: string;
  title: string;
  description: string;
  protected: boolean;
  loading: boolean;
  onToggle: (path: string, next: boolean) => void;
}) {
  const { t } = useTranslation();

  return (
    <div
      className={`${styles.fileItem} ${isProtected ? styles.fileItemProtected : ""}`}
    >
      <div className={styles.fileItemHeader}>
        <div className={styles.fileInfo}>
          <div className={styles.fileItemName}>
            {isProtected ? <span className={styles.enabledBadge}>●</span> : null}
            {title}
          </div>
          <div className={styles.fileItemMeta}>{description}</div>
          <div className={styles.fileItemMeta}>{path}</div>
        </div>
        <div className={styles.fileItemActions}>
          <Tooltip title={t("security.integrityProtection.fileBaselineToggleTooltip")}>
            <Switch
              size="small"
              checked={isProtected}
              loading={loading}
              onChange={(checked) => {
                onToggle(path, checked);
              }}
            />
          </Tooltip>
        </div>
      </div>
    </div>
  );
}

export function FileBaselineProtectionFileList() {
  const { t } = useTranslation();
  const {
    protectedPaths,
    pathsSaving,
    toggleProtectedPath,
  } = useFileBaselineProtectionContext();
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pendingPath, setPendingPath] = useState<string | null>(null);

  const protectedSet = useMemo(() => new Set(protectedPaths), [protectedPaths]);

  const customPaths = useMemo(
    () => protectedPaths.filter((path) => !FILE_BASELINE_PRESET_PATH_SET.has(path)),
    [protectedPaths],
  );

  const handleToggle = (path: string, next: boolean) => {
    setPendingPath(path);
    void toggleProtectedPath(path, next).finally(() => {
      setPendingPath(null);
    });
  };

  return (
    <div className={styles.panel}>
      <h4 className={styles.sectionTitle}>
        {t("security.integrityProtection.protectedPathsLabel")}
      </h4>
      <p className={styles.infoText}>
        {t("security.integrityProtection.protectedFilesDesc")}
      </p>
      <div className={styles.divider} />
      <div className={styles.fileList}>
        {FILE_BASELINE_PRESET_PATHS.map((candidate) => (
          <FileBaselinePathRow
            key={candidate.path}
            path={candidate.path}
            title={t(candidate.labelKey)}
            description={t(candidate.descriptionKey)}
            protected={protectedSet.has(candidate.path)}
            loading={pathsSaving && pendingPath === candidate.path}
            onToggle={handleToggle}
          />
        ))}
      </div>

      <div className={styles.customSection}>
        <h4 className={styles.customTitle}>
          {t("security.integrityProtection.customPathsTitle")}
        </h4>
        {customPaths.length === 0 ? (
          <p className={styles.emptyCustom}>
            {t("security.integrityProtection.customPathsEmpty")}
          </p>
        ) : (
          <div className={styles.fileList}>
            {customPaths.map((path) => (
              <FileBaselinePathRow
                key={path}
                path={path}
                title={path}
                description={t("security.integrityProtection.customPathDescription")}
                protected
                loading={pathsSaving && pendingPath === path}
                onToggle={handleToggle}
              />
            ))}
          </div>
        )}
        <div className={styles.customAddRow}>
          <Button
            size="small"
            loading={pathsSaving}
            onClick={() => setPickerOpen(true)}
          >
            {t("security.integrityProtection.pickWorkspaceFile")}
          </Button>
        </div>
      </div>

      <WorkspaceProtectableFilePickerModal
        open={pickerOpen}
        protectedPaths={protectedPaths}
        onClose={() => setPickerOpen(false)}
        onAdd={async (relPath) => {
          await toggleProtectedPath(relPath, true);
        }}
      />
    </div>
  );
}
