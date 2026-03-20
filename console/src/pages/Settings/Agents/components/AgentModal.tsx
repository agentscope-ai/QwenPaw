import {
  Avatar,
  Button,
  Form,
  Input,
  Modal,
  Slider,
  Space,
  Typography,
  Upload,
  message,
} from "antd";
import { DeleteOutlined, UploadOutlined } from "@ant-design/icons";
import { Bot } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { AgentProfileConfig } from "@/api/types/agents";
import styles from "../index.module.less";

interface AgentModalProps {
  open: boolean;
  editingAgent: AgentProfileConfig | null;
  form: ReturnType<typeof Form.useForm>[0];
  avatarPreviewUrl?: string;
  onAvatarChange: (file: File) => void;
  onAvatarRemove: () => void;
  onSave: () => Promise<void>;
  onCancel: () => void;
}

export function AgentModal({
  open,
  editingAgent,
  form,
  avatarPreviewUrl,
  onAvatarChange,
  onAvatarRemove,
  onSave,
  onCancel,
}: AgentModalProps) {
  const { t } = useTranslation();
  const cropSize = 320;
  const [cropModalOpen, setCropModalOpen] = useState(false);
  const [cropSourceUrl, setCropSourceUrl] = useState<string>();
  const [pendingAvatarFile, setPendingAvatarFile] = useState<File | null>(null);
  const [imageNaturalSize, setImageNaturalSize] = useState<{
    width: number;
    height: number;
  } | null>(null);
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [isCropping, setIsCropping] = useState(false);
  const dragStateRef = useRef<{
    startX: number;
    startY: number;
    originX: number;
    originY: number;
  } | null>(null);
  const cropObjectUrlRef = useRef<string | null>(null);

  const clearCropObjectUrl = () => {
    if (cropObjectUrlRef.current) {
      URL.revokeObjectURL(cropObjectUrlRef.current);
      cropObjectUrlRef.current = null;
    }
  };

  useEffect(() => {
    return () => {
      clearCropObjectUrl();
    };
  }, []);

  const resetCropState = () => {
    clearCropObjectUrl();
    setCropModalOpen(false);
    setCropSourceUrl(undefined);
    setPendingAvatarFile(null);
    setImageNaturalSize(null);
    setDragOffset({ x: 0, y: 0 });
    setZoom(1);
    setIsCropping(false);
    dragStateRef.current = null;
  };

  const renderedImage = useMemo(() => {
    if (!imageNaturalSize) return null;
    const baseScale = Math.max(
      cropSize / imageNaturalSize.width,
      cropSize / imageNaturalSize.height,
    );
    const scale = baseScale * zoom;
    return {
      width: imageNaturalSize.width * scale,
      height: imageNaturalSize.height * scale,
      scale,
    };
  }, [cropSize, imageNaturalSize, zoom]);

  const clampOffset = (
    value: number,
    renderedDimension: number,
    viewportDimension: number,
  ) => {
    const maxOffset = Math.max((renderedDimension - viewportDimension) / 2, 0);
    return Math.min(Math.max(value, -maxOffset), maxOffset);
  };

  const applyOffset = (x: number, y: number) => {
    if (!renderedImage) return;
    setDragOffset({
      x: clampOffset(x, renderedImage.width, cropSize),
      y: clampOffset(y, renderedImage.height, cropSize),
    });
  };

  const loadCropImage = (file: File) => {
    clearCropObjectUrl();
    const objectUrl = URL.createObjectURL(file);
    cropObjectUrlRef.current = objectUrl;
    setCropSourceUrl(objectUrl);
    setPendingAvatarFile(file);
    setImageNaturalSize(null);
    setDragOffset({ x: 0, y: 0 });
    setZoom(1);
    setCropModalOpen(true);
  };

  const exportCroppedAvatar = async () => {
    if (
      !pendingAvatarFile ||
      !cropSourceUrl ||
      !renderedImage ||
      !imageNaturalSize
    ) {
      return;
    }

    setIsCropping(true);
    try {
      const image = await new Promise<HTMLImageElement>((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => reject(new Error("Failed to load avatar image"));
        img.src = cropSourceUrl;
      });

      const canvas = document.createElement("canvas");
      const outputSize = 512;
      canvas.width = outputSize;
      canvas.height = outputSize;
      const context = canvas.getContext("2d");
      if (!context) {
        throw new Error("Failed to initialize avatar crop canvas");
      }

      const baseX = (cropSize - renderedImage.width) / 2 + dragOffset.x;
      const baseY = (cropSize - renderedImage.height) / 2 + dragOffset.y;
      const scaleFactor = outputSize / cropSize;

      context.drawImage(
        image,
        baseX * scaleFactor,
        baseY * scaleFactor,
        renderedImage.width * scaleFactor,
        renderedImage.height * scaleFactor,
      );

      const mimeType =
        pendingAvatarFile.type === "image/webp"
          ? "image/webp"
          : pendingAvatarFile.type === "image/png"
          ? "image/png"
          : "image/jpeg";
      const extension =
        mimeType === "image/png"
          ? "png"
          : mimeType === "image/webp"
          ? "webp"
          : "jpeg";

      const blob = await new Promise<Blob | null>((resolve) => {
        canvas.toBlob(resolve, mimeType, 0.92);
      });

      if (!blob) {
        throw new Error("Failed to export cropped avatar");
      }

      const croppedFile = new File([blob], `avatar-cropped.${extension}`, {
        type: mimeType,
      });

      onAvatarChange(croppedFile);
      resetCropState();
    } catch (error) {
      console.error("Failed to crop avatar:", error);
      message.error(t("agent.avatarCropFailed"));
      setIsCropping(false);
    }
  };

  const beforeUpload = (file: File) => {
    const allowedTypes = ["image/png", "image/jpeg", "image/webp"];
    if (!allowedTypes.includes(file.type)) {
      message.error(t("agent.avatarInvalidType"));
      return Upload.LIST_IGNORE;
    }

    if (file.size > 2 * 1024 * 1024) {
      message.error(t("agent.avatarTooLarge"));
      return Upload.LIST_IGNORE;
    }

    loadCropImage(file);
    return false;
  };

  return (
    <Modal
      title={
        editingAgent
          ? t("agent.editTitle", { name: editingAgent.name })
          : t("agent.createTitle")
      }
      open={open}
      onOk={onSave}
      onCancel={onCancel}
      width={600}
      okText={t("common.save")}
      cancelText={t("common.cancel")}
    >
      <Form form={form} layout="vertical" autoComplete="off">
        {editingAgent && (
          <Form.Item name="id" label={t("agent.id")}>
            <Input disabled />
          </Form.Item>
        )}
        <Form.Item
          name="name"
          label={t("agent.name")}
          rules={[{ required: true, message: t("agent.nameRequired") }]}
        >
          <Input placeholder={t("agent.namePlaceholder")} />
        </Form.Item>
        <Form.Item name="description" label={t("agent.description")}>
          <Input.TextArea
            placeholder={t("agent.descriptionPlaceholder")}
            rows={3}
          />
        </Form.Item>
        <Form.Item
          label={t("agent.avatar")}
          extra={
            <span className={styles.agentAvatarHelp}>
              {t("agent.avatarHelp")}
            </span>
          }
        >
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            <Space size={16} align="center">
              <Avatar
                size={72}
                shape="square"
                src={avatarPreviewUrl}
                icon={<Bot size={28} strokeWidth={2} />}
                className={styles.agentAvatarPlaceholder}
              />
              <Space direction="vertical" size={4}>
                <Typography.Text className={styles.agentAvatarMeta}>
                  {t("agent.avatarRecommended")}
                </Typography.Text>
                <Space wrap>
                  <Upload
                    accept="image/png,image/jpeg,image/webp"
                    showUploadList={false}
                    beforeUpload={beforeUpload}
                  >
                    <Button icon={<UploadOutlined />}>
                      {t("common.upload")}
                    </Button>
                  </Upload>
                  {avatarPreviewUrl && (
                    <Button
                      danger
                      icon={<DeleteOutlined />}
                      onClick={onAvatarRemove}
                    >
                      {t("common.delete")}
                    </Button>
                  )}
                </Space>
              </Space>
            </Space>
          </Space>
        </Form.Item>
        <Form.Item
          name="workspace_dir"
          label={t("agent.workspace")}
          help={!editingAgent ? t("agent.workspaceHelp") : undefined}
        >
          <Input
            placeholder="~/.copaw/workspaces/my-agent"
            disabled={!!editingAgent}
          />
        </Form.Item>
      </Form>
      <Modal
        title={t("agent.avatarCropTitle")}
        open={cropModalOpen}
        onOk={() => void exportCroppedAvatar()}
        onCancel={resetCropState}
        okText={t("common.confirm")}
        cancelText={t("common.cancel")}
        confirmLoading={isCropping}
        destroyOnHidden
        width={520}
      >
        <Space direction="vertical" size={16} style={{ width: "100%" }}>
          <Typography.Text className={styles.agentAvatarMeta}>
            {t("agent.avatarCropHelp")}
          </Typography.Text>
          <div className={styles.agentAvatarCropStage}>
            <div
              className={styles.agentAvatarCropViewport}
              onMouseDown={(event) => {
                if (!renderedImage) return;
                dragStateRef.current = {
                  startX: event.clientX,
                  startY: event.clientY,
                  originX: dragOffset.x,
                  originY: dragOffset.y,
                };
              }}
              onMouseMove={(event) => {
                if (!dragStateRef.current) return;
                applyOffset(
                  dragStateRef.current.originX +
                    event.clientX -
                    dragStateRef.current.startX,
                  dragStateRef.current.originY +
                    event.clientY -
                    dragStateRef.current.startY,
                );
              }}
              onMouseUp={() => {
                dragStateRef.current = null;
              }}
              onMouseLeave={() => {
                dragStateRef.current = null;
              }}
            >
              {cropSourceUrl && (
                <img
                  src={cropSourceUrl}
                  alt={t("agent.avatar")}
                  draggable={false}
                  className={styles.agentAvatarCropImage}
                  onLoad={(event) => {
                    const image = event.currentTarget;
                    setImageNaturalSize({
                      width: image.naturalWidth,
                      height: image.naturalHeight,
                    });
                  }}
                  style={
                    renderedImage
                      ? {
                          width: renderedImage.width,
                          height: renderedImage.height,
                          left:
                            (cropSize - renderedImage.width) / 2 + dragOffset.x,
                          top:
                            (cropSize - renderedImage.height) / 2 +
                            dragOffset.y,
                        }
                      : undefined
                  }
                />
              )}
              <div className={styles.agentAvatarCropMask} />
            </div>
          </div>
          <div className={styles.agentAvatarCropControls}>
            <Typography.Text className={styles.agentAvatarMeta}>
              {t("agent.avatarCropZoom")}
            </Typography.Text>
            <Slider
              min={1}
              max={3}
              step={0.01}
              value={zoom}
              onChange={(value) => {
                const nextZoom = Array.isArray(value) ? value[0] : value;
                setZoom(nextZoom);
                if (renderedImage) {
                  requestAnimationFrame(() => {
                    applyOffset(dragOffset.x, dragOffset.y);
                  });
                }
              }}
            />
          </div>
        </Space>
      </Modal>
    </Modal>
  );
}
