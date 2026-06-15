import { useCallback, useRef, type ChangeEvent } from "react";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "@/hooks/useAppMessage";
import { invalidateSkillCache } from "@/api/modules/skill";
import { parseErrorDetail } from "@/utils/error";
import { handleScanError } from "@/utils/scanError";
import { useUploadLimitStore } from "@/stores/uploadLimitStore";
import { uploadSkillPoolSecureImport } from "../api/client";

export type SecureImportConflict = {
  skill_name?: string;
  suggested_name?: string;
};

export type UseSkillPoolSecureImportOptions = {
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

export function useSkillPoolSecureImport(
  options: UseSkillPoolSecureImportOptions,
) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const inputRef = useRef<HTMLInputElement>(null);

  const openFilePicker = useCallback(() => {
    inputRef.current?.click();
  }, []);

  const handleChange = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(event.target.files ?? []);
      event.target.value = "";
      if (files.length === 0) return;

      const zipFile = files.find((file) =>
        file.name.toLowerCase().endsWith(".zip"),
      );
      const sigFile = files.find((file) =>
        file.name.toLowerCase().endsWith(".sig"),
      );

      if (!zipFile) {
        message.warning(t("skills.zipOnly"));
        return;
      }
      if (!sigFile) {
        message.warning(t("skillPool.secureImportSigRequired"));
        return;
      }

      const sizeMB = zipFile.size / (1024 * 1024);
      const uploadLimit = useUploadLimitStore.getState().uploadMaxSizeMb;
      if (uploadLimit !== null && sizeMB > uploadLimit) {
        message.warning(
          t("skills.fileSizeExceeded", {
            limit: uploadLimit,
            size: sizeMB.toFixed(1),
          }),
        );
        return;
      }

      let renameMap: Record<string, string> | undefined;
      while (true) {
        try {
          const result = await uploadSkillPoolSecureImport(zipFile, sigFile, {
            rename_map: renameMap,
          });
          if (result.count > 0) {
            message.success(
              t("skillPool.secureImportSuccess", {
                names: result.imported.join(", "),
              }),
            );
          } else {
            message.info(t("skillPool.noNewImports"));
          }
          invalidateSkillCache({ pool: true });
          await options.onReload();
          if (result.count > 0 && Array.isArray(result.imported)) {
            for (const name of result.imported) {
              await options.checkScanWarningsForSkill(name);
            }
          }
          break;
        } catch (error) {
          const detail = parseErrorDetail(error);
          if (detail?.reason === "signature_verification_failed") {
            message.error(t("skillPool.secureImportFailed"));
            break;
          }
          const conflicts = Array.isArray(detail?.conflicts)
            ? (detail.conflicts as SecureImportConflict[])
            : [];
          if (conflicts.length === 0) {
            if (handleScanError(error, t)) break;
            message.error(
              error instanceof Error
                ? error.message
                : t("skillPool.secureImportFailed"),
            );
            break;
          }
          const newRenames = await options.showConflictRenameModal(
            conflicts.map((conflict) => ({
              key: conflict.skill_name || "",
              label: conflict.skill_name || "",
              suggested_name: conflict.suggested_name || "",
            })),
          );
          if (!newRenames) break;
          renameMap = { ...renameMap, ...newRenames };
        }
      }
    },
    [message, options, t],
  );

  return {
    inputRef,
    openFilePicker,
    handleChange,
  };
}
