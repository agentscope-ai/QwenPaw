import { Button, Tooltip } from "@agentscope-ai/design";
import { SafetyCertificateOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { useSkillPoolSecureImport } from "../hooks/useSkillPoolSecureImport";

export type SkillPoolSecureImportButtonProps = {
  onReload: () => Promise<void>;
  showConflictRenameModal: (
    conflicts: Array<{
      key: string;
      label: string;
      suggested_name: string;
    }>,
  ) => Promise<Record<string, string> | null>;
  checkScanWarningsForSkill: (skillName: string) => Promise<void>;
};

export function SkillPoolSecureImportButton({
  onReload,
  showConflictRenameModal,
  checkScanWarningsForSkill,
}: SkillPoolSecureImportButtonProps) {
  const { t } = useTranslation();
  const secureImport = useSkillPoolSecureImport({
    onReload,
    showConflictRenameModal,
    checkScanWarningsForSkill,
  });

  return (
    <>
      <input
        type="file"
        accept=".zip,.sig"
        multiple
        ref={secureImport.inputRef}
        onChange={secureImport.handleChange}
        style={{ display: "none" }}
      />
      <Tooltip title={t("skillPool.secureImportHint")}>
        <Button
          type="default"
          icon={<SafetyCertificateOutlined />}
          onClick={secureImport.openFilePicker}
        >
          {t("skillPool.secureImport")}
        </Button>
      </Tooltip>
    </>
  );
}
