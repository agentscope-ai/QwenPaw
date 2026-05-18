import { useTranslation } from "react-i18next";
import { Button, Modal, Input, Form, Divider, Typography, Space } from "antd";
import { Package, Link, FolderOpen, FileArchive, X } from "lucide-react";
import type { useInstallModal } from "../hooks/useInstallModal";
import styles from "../index.module.less";

const { Text } = Typography;

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

      <Modal
        open={installOpen}
        title={
          <Space>
            <Package size={18} />
            {t("pluginManager.installTitle")}
          </Space>
        }
        onCancel={closeModal}
        footer={null}
        destroyOnHidden
        centered
        width={480}
      >
        <div style={{ paddingTop: 16 }}>
          {localSel ? (
            <div className={styles.selectionCard}>
              {localSel.kind === "folder" ? (
                <FolderOpen size={18} />
              ) : (
                <FileArchive size={18} />
              )}
              <Text className={styles.selectionName}>{localSel.name}</Text>
              <Button
                type="text"
                size="small"
                icon={<X size={14} />}
                onClick={clearSelection}
              />
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
              <Text className={styles.dropPrimary}>
                {t("pluginManager.dropPrimary")}
              </Text>
              <Text type="secondary" className={styles.dropSecondary}>
                {t("pluginManager.dropSecondary")}
              </Text>
            </div>
          )}

          <Button
            type="primary"
            block
            style={{ marginTop: 12 }}
            disabled={!localSel}
            loading={localInstalling}
            onClick={handleInstallLocal}
          >
            {localInstalling
              ? t("pluginManager.installing")
              : t("pluginManager.installBtn")}
          </Button>

          <Divider style={{ margin: "20px 0 16px" }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t("pluginManager.orFromUrl")}
            </Text>
          </Divider>

          <Form form={form} layout="vertical">
            <Form.Item
              name="source"
              style={{ marginBottom: 8 }}
              rules={[{ required: true, message: " " }]}
            >
              <Input
                prefix={
                  <Link
                    size={14}
                    style={{ color: "var(--ant-color-text-quaternary)" }}
                  />
                }
                placeholder={t("pluginManager.urlPlaceholder")}
                allowClear
                onPressEnter={handleInstallUrl}
              />
            </Form.Item>
            <Button block loading={urlInstalling} onClick={handleInstallUrl}>
              {urlInstalling
                ? t("pluginManager.installing")
                : t("pluginManager.installFromUrl")}
            </Button>
          </Form>

          <Text
            type="secondary"
            style={{ fontSize: 11, display: "block", marginTop: 14 }}
          >
            {t("pluginManager.restartHint")}
          </Text>
        </div>
      </Modal>
    </>
  );
}
