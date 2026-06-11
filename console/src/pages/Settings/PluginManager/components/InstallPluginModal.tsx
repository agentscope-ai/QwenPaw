import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Package, Link, FolderOpen, FileArchive, X } from "lucide-react";
import type { useInstallModal } from "../hooks/useInstallModal";
import styles from "./InstallPluginModal.module.less";

type InstallModalProps = ReturnType<typeof useInstallModal>;

export function InstallPluginModal({
  installOpen,
  closeModal,
  localInstalling,
  urlInstalling,
  localSel,
  clearSelection,
  dragOver,
  form,
  fileInputRef,
  browseZip,
  handleZipPicked,
  handleDragOver,
  handleDragLeave,
  handleDrop,
  handleInstallLocal,
  handleInstallUrl,
}: Omit<InstallModalProps, "openModal">) {
  const { t } = useTranslation();

  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        accept=".zip"
        style={{ display: "none" }}
        onChange={handleZipPicked}
      />

      <Dialog
        open={installOpen}
        onOpenChange={(v) => {
          if (!v) closeModal();
        }}
      >
        <DialogContent className="max-w-[480px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Package size={18} />
              {t("pluginManager.installTitle")}
            </DialogTitle>
          </DialogHeader>

          <div className="flex flex-col gap-3 pt-2">
            {localSel ? (
              <div className={styles.selectionCard}>
                {localSel.kind === "folder" ? (
                  <FolderOpen size={18} />
                ) : (
                  <FileArchive size={18} />
                )}
                <span className={styles.selectionName}>{localSel.name}</span>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 w-6 p-0"
                  onClick={clearSelection}
                >
                  <X size={14} />
                </Button>
              </div>
            ) : (
              <div
                className={`${styles.dropZone} ${
                  dragOver ? styles.dropZoneActive : ""
                }`}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onClick={browseZip}
              >
                <Package
                  size={36}
                  strokeWidth={1.2}
                  className={styles.dropIcon}
                />
                <span className={styles.dropPrimary}>
                  {t("pluginManager.dropPrimary")}
                </span>
                <span
                  className={`${styles.dropSecondary} text-muted-foreground`}
                >
                  {t("pluginManager.dropSecondary")}
                </span>
              </div>
            )}

            <Button
              className="w-full"
              disabled={!localSel || localInstalling}
              onClick={handleInstallLocal}
            >
              {localInstalling
                ? t("pluginManager.installing")
                : t("pluginManager.installBtn")}
            </Button>

            <div className="flex items-center gap-2 my-1">
              <div className="flex-1 border-t" />
              <span className="text-xs text-muted-foreground px-2">
                {t("pluginManager.orFromUrl")}
              </span>
              <div className="flex-1 border-t" />
            </div>

            <div className="flex flex-col gap-2">
              <div className="relative">
                <Link
                  size={14}
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
                />
                <Input
                  className="pl-8"
                  placeholder={t("pluginManager.urlPlaceholder")}
                  {...form.register("source")}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void handleInstallUrl();
                  }}
                />
              </div>
              <Button
                variant="outline"
                className="w-full"
                disabled={urlInstalling}
                onClick={handleInstallUrl}
              >
                {urlInstalling
                  ? t("pluginManager.installing")
                  : t("pluginManager.installFromUrl")}
              </Button>
            </div>

            <span className="text-xs text-muted-foreground">
              {t("pluginManager.restartHint")}
            </span>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
