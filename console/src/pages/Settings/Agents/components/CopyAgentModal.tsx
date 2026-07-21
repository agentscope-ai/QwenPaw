import { useEffect, useState } from "react";
import { Modal, Input, Checkbox, Space, Typography } from "antd";
import { useTranslation } from "react-i18next";
import type { AgentSummary, CopyAgentRequest } from "@/api/types/agents";
import { getAgentDisplayName } from "@/utils/agentDisplayName";

const { Text } = Typography;

interface CopyAgentModalProps {
  open: boolean;
  sourceAgent: AgentSummary | null;
  confirmLoading?: boolean;
  onOk: (body: CopyAgentRequest) => Promise<void> | void;
  onCancel: () => void;
}

type CopyOptions = Required<Omit<CopyAgentRequest, "name">>;

const DEFAULT_OPTIONS: CopyOptions = {
  copy_agent_json: true,
  copy_md_files: true,
  copy_skills: false,
  copy_jobs: false,
};

export function CopyAgentModal({
  open,
  sourceAgent,
  confirmLoading = false,
  onOk,
  onCancel,
}: CopyAgentModalProps) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [options, setOptions] = useState<CopyOptions>(DEFAULT_OPTIONS);

  useEffect(() => {
    if (!open || !sourceAgent) {
      return;
    }
    const displayName = getAgentDisplayName(sourceAgent, t);
    setName(`${displayName} Copy`);
    setOptions(DEFAULT_OPTIONS);
  }, [open, sourceAgent, t]);

  const handleOk = async () => {
    const trimmed = name.trim();
    await onOk({
      name: trimmed || undefined,
      ...options,
      copy_agent_json: true,
    });
  };

  return (
    <Modal
      open={open}
      title={t("agent.copyTitle")}
      onOk={handleOk}
      onCancel={onCancel}
      confirmLoading={confirmLoading}
      okText={t("common.confirm")}
      cancelText={t("common.cancel")}
      destroyOnClose
    >
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <div>
          <Text style={{ display: "block", marginBottom: 8 }}>
            {t("agent.copyNameLabel")}
          </Text>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("agent.namePlaceholder")}
          />
        </div>
        <div>
          <Text style={{ display: "block", marginBottom: 8 }}>
            {t("agent.copyOptionsLabel")}
          </Text>
          <Space direction="vertical">
            <div>
              <Checkbox checked disabled>
                {t("agent.copyOptionAgentJson")}
              </Checkbox>
              <Text
                type="secondary"
                style={{
                  display: "block",
                  fontSize: 12,
                  marginLeft: 24,
                  marginTop: 4,
                }}
              >
                {t("agent.copyOptionAgentJsonHint")}
              </Text>
            </div>
            <Checkbox
              checked={options.copy_md_files}
              onChange={(e) =>
                setOptions((prev) => ({
                  ...prev,
                  copy_md_files: e.target.checked,
                }))
              }
            >
              {t("agent.copyOptionMdFiles")}
            </Checkbox>
            <Checkbox
              checked={options.copy_skills}
              onChange={(e) =>
                setOptions((prev) => ({
                  ...prev,
                  copy_skills: e.target.checked,
                }))
              }
            >
              {t("agent.copyOptionSkills")}
            </Checkbox>
            <div>
              <Checkbox
                checked={options.copy_jobs}
                onChange={(e) =>
                  setOptions((prev) => ({
                    ...prev,
                    copy_jobs: e.target.checked,
                  }))
                }
              >
                {t("agent.copyOptionJobs")}
              </Checkbox>
              <Text
                type="secondary"
                style={{
                  display: "block",
                  fontSize: 12,
                  marginLeft: 24,
                  marginTop: 4,
                }}
              >
                {t("agent.copyOptionJobsHint")}
              </Text>
            </div>
          </Space>
        </div>
      </Space>
    </Modal>
  );
}
