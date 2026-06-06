import React from "react";
import { Button, Modal, Result } from "antd";
import { ExclamationCircleOutlined, SettingOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";

export interface ModelPromptModalProps {
  open: boolean;
  isDark?: boolean;
  onSkip: () => void;
  onConfigure: () => void;
}

const ModelPromptModal: React.FC<ModelPromptModalProps> = ({
  open,
  isDark = false,
  onSkip,
  onConfigure,
}) => {
  const { t } = useTranslation();

  return (
    <Modal
      open={open}
      closable={false}
      footer={null}
      width={480}
      styles={{
        content: isDark
          ? { background: "#1f1f1f", boxShadow: "0 8px 32px rgba(0,0,0,0.5)" }
          : undefined,
      }}
    >
      <Result
        icon={<ExclamationCircleOutlined style={{ color: "#faad14" }} />}
        title={
          <span
            style={{ color: isDark ? "rgba(255,255,255,0.88)" : undefined }}
          >
            {t("modelConfig.promptTitle")}
          </span>
        }
        subTitle={
          <span
            style={{ color: isDark ? "rgba(255,255,255,0.55)" : undefined }}
          >
            {t("modelConfig.promptMessage")}
          </span>
        }
        extra={[
          <Button key="skip" onClick={onSkip}>
            {t("modelConfig.skipButton")}
          </Button>,
          <Button
            key="configure"
            type="primary"
            icon={<SettingOutlined />}
            onClick={onConfigure}
          >
            {t("modelConfig.configureButton")}
          </Button>,
        ]}
      />
    </Modal>
  );
};

export default ModelPromptModal;
