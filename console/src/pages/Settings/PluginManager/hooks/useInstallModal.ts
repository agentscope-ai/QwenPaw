import { useState, useCallback, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Form } from "antd";
import { useAppMessage } from "@/hooks/useAppMessage";
import { installPlugin, uploadPlugin } from "@/api/modules/plugin";
import { readDirEntry, type LocalSelection } from "../utils";

export function useInstallModal(onSuccess: () => void) {
  const { t } = useTranslation();
  const { message } = useAppMessage();

  const [installOpen, setInstallOpen] = useState(false);
  const [localInstalling, setLocalInstalling] = useState(false);
  const [urlInstalling, setUrlInstalling] = useState(false);
  const [localSel, setLocalSel] = useState<LocalSelection | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [form] = Form.useForm<{ source: string }>();

  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const cancel = () => setDragOver(false);
    window.addEventListener("dragend", cancel);
    window.addEventListener("drop", cancel);
    return () => {
      window.removeEventListener("dragend", cancel);
      window.removeEventListener("drop", cancel);
    };
  }, []);

  const openModal = useCallback(() => setInstallOpen(true), []);

  const closeModal = useCallback(() => {
    if (localInstalling || urlInstalling) return;
    setInstallOpen(false);
    setLocalSel(null);
    setDragOver(false);
    form.resetFields();
  }, [localInstalling, urlInstalling, form]);

  const handleZipPicked = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) setLocalSel({ kind: "zip", name: file.name, file });
      e.target.value = "";
    },
    [],
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
  }, []);

  const handleDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDragOver(false);

      const items = Array.from(e.dataTransfer.items);
      if (items.length === 0) return;

      const entry = items[0].webkitGetAsEntry();
      if (!entry) return;

      if (entry.isDirectory) {
        try {
          const entries = await readDirEntry(entry as FileSystemDirectoryEntry);
          setLocalSel({ kind: "folder", name: entry.name, entries });
        } catch {
          message.error(t("pluginManager.dropFailed"));
        }
      } else if (entry.isFile) {
        const file = e.dataTransfer.files[0];
        if (!file.name.endsWith(".zip")) {
          message.warning(t("pluginManager.zipOnly"));
          return;
        }
        setLocalSel({ kind: "zip", name: file.name, file });
      }
    },
    [message, t],
  );

  const handleInstallLocal = useCallback(async () => {
    if (!localSel) return;
    setLocalInstalling(true);
    try {
      let uploadFile: File;

      if (localSel.kind === "zip") {
        uploadFile = localSel.file;
      } else {
        const { default: JSZip } = await import("jszip");
        const zip = new JSZip();
        for (const { path, file } of localSel.entries) {
          zip.file(path, file);
        }
        const blob = await zip.generateAsync({ type: "blob" });
        uploadFile = new File([blob], `${localSel.name}.zip`, {
          type: "application/zip",
        });
      }

      const result = await uploadPlugin(uploadFile);
      message.success(`${t("pluginManager.installSuccess")}: ${result.name}`);
      setInstallOpen(false);
      setLocalSel(null);
      onSuccess();
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : t("pluginManager.installFailed");
      message.error(msg);
    } finally {
      setLocalInstalling(false);
    }
  }, [localSel, message, t, onSuccess]);

  const handleInstallUrl = useCallback(async () => {
    let values: { source: string };
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    const source = values.source.trim();
    setUrlInstalling(true);
    try {
      const result = await installPlugin(source);
      message.success(`${t("pluginManager.installSuccess")}: ${result.name}`);
      setInstallOpen(false);
      form.resetFields();
      onSuccess();
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : t("pluginManager.installFailed");
      message.error(msg);
    } finally {
      setUrlInstalling(false);
    }
  }, [form, message, t, onSuccess]);

  const clearSelection = useCallback(() => setLocalSel(null), []);
  const browseZip = useCallback(() => fileInputRef.current?.click(), []);

  return {
    installOpen,
    openModal,
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
  };
}
