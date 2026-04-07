import { useState, useEffect, useMemo } from "react";
import {
  Modal,
  Form,
  Input,
  Select,
  InputNumber,
  Button,
  Space,
  Radio,
  Steps,
  Card,
  Typography,
  Divider,
  message,
} from "antd";
import { Sparkles, User, Users } from "lucide-react";
import { useTranslation } from "react-i18next";
import type {
  CreateMeetingRequest,
  MeetingParticipant,
  MeetingType,
} from "@/api/types/meetings";
import { agentSACPApi } from "@/api/modules/agent_sacp";
import type { AgentSACPConfig } from "@/api/modules/agent_sacp";

const { TextArea } = Input;
const { Text } = Typography;

interface CreateMeetingModalProps {
  open: boolean;
  onCancel: () => void;
  onSubmit: (data: CreateMeetingRequest) => Promise<void>;
  submitting: boolean;
}

interface Step1Values {
  topic_title: string;
  topic_description: string;
  participant_ids: string[];
  host_id: string;
  decider_id: string;
}

interface Step2Values {
  meeting_type: MeetingType;
  fixed_interval_minutes?: number;
  fixed_time_daily?: string;
  topic_context: string;
  decision_principles: string;
}

// Placeholder for LLM auto-generate functionality
async function generateFlowDescription(
  _topicName: string,
  _topicDesc: string,
  _participantNames: string[],
): Promise<string> {
  // TODO: Replace with actual LLM API call
  await new Promise((resolve) => setTimeout(resolve, 1000));
  return `基于${_participantNames.join("、")}的讨论，就${_topicName}达成共识。`;
}

// Placeholder for LLM auto-generate background and principles
async function generateBackgroundAndPrinciples(
  _topicName: string,
  _topicDesc: string,
  _participantNames: string[],
): Promise<{ background: string; principles: string }> {
  // TODO: Replace with actual LLM API call
  await new Promise((resolve) => setTimeout(resolve, 1000));
  return {
    background: `本次会议${_topicName}背景说明：${_topicDesc}\n参会人员包括${_participantNames.join(
      "、",
    )}，各位将围绕主题展开深入讨论。`,
    principles: `决策原则：\n1. 充分讨论后达成共识\n2. 尊重各方意见\n3. 决策结果需得到多数认可`,
  };
}

export function CreateMeetingModal({
  open,
  onCancel,
  onSubmit,
  submitting,
}: CreateMeetingModalProps) {
  const { t } = useTranslation();
  const [form1] = Form.useForm<Step1Values>();
  const [form2] = Form.useForm<Step2Values>();

  const [currentStep, setCurrentStep] = useState(0);
  const [agents, setAgents] = useState<AgentSACPConfig[]>([]);
  const [loadingAgents, setLoadingAgents] = useState(false);
  const [generatingFlow, setGeneratingFlow] = useState(false);
  const [generatingDetails, setGeneratingDetails] = useState(false);
  const [rounds, setRounds] = useState<string[]>(["raw", "raw"]);

  // Watch meeting_type at component top level (this is a hook call, must be here)
  const watchedMeetingType =
    Form.useWatch("meeting_type", form2) ?? "TEMPORARY";

  // Load agents on modal open
  useEffect(() => {
    if (open) {
      setLoadingAgents(true);
      agentSACPApi
        .getAgents()
        .then((res) => {
          setAgents(res);
        })
        .catch(() => {
          message.error(t("meetings.errors.loadAgentsFailed"));
        })
        .finally(() => {
          setLoadingAgents(false);
        });
    }
  }, [open, t]);

  // Auto-set host and decider when participants change
  const selectedParticipantIds = Form.useWatch("participant_ids", form1);
  const selectedAgents = useMemo(() => {
    if (!selectedParticipantIds || selectedParticipantIds.length === 0)
      return [];
    return agents.filter((a) => selectedParticipantIds.includes(a.id));
  }, [agents, selectedParticipantIds]);

  // Set default host (first) and decider (last) when participants change
  useEffect(() => {
    if (selectedParticipantIds && selectedParticipantIds.length > 0) {
      const currentHost = form1.getFieldValue("host_id");
      const currentDecider = form1.getFieldValue("decider_id");

      // Update host if current host is not in selection or empty
      if (!currentHost || !selectedParticipantIds.includes(currentHost)) {
        form1.setFieldValue("host_id", selectedParticipantIds[0]);
      }
      // Update decider if current decider is not in selection or empty
      if (!currentDecider || !selectedParticipantIds.includes(currentDecider)) {
        form1.setFieldValue(
          "decider_id",
          selectedParticipantIds[selectedParticipantIds.length - 1],
        );
      }
    }
  }, [selectedParticipantIds, form1]);

  const handleGenerateFlowDescription = async () => {
    const values = form1.getFieldsValue();
    if (!values.topic_title) {
      message.warning(t("meetings.form.topicTitleRequired"));
      return;
    }

    setGeneratingFlow(true);
    try {
      const participantNames = selectedAgents.map((a) => a.name || a.id);
      const generated = await generateFlowDescription(
        values.topic_title,
        values.topic_description || "",
        participantNames,
      );
      form1.setFieldValue("topic_description", generated);
      message.success(t("meetings.form.autoGenerateSuccess"));
    } catch {
      message.error(t("meetings.errors.generateFailed"));
    } finally {
      setGeneratingFlow(false);
    }
  };

  const handleGenerateDetails = async () => {
    const values1 = form1.getFieldsValue();

    setGeneratingDetails(true);
    try {
      const participantNames = selectedAgents.map((a) => a.name || a.id);
      const generated = await generateBackgroundAndPrinciples(
        values1.topic_title,
        values1.topic_description || "",
        participantNames,
      );
      form2.setFieldsValue({
        topic_context: generated.background,
        decision_principles: generated.principles,
      });
      message.success(t("meetings.form.autoGenerateSuccess"));
    } catch {
      message.error(t("meetings.errors.generateFailed"));
    } finally {
      setGeneratingDetails(false);
    }
  };

  const handleStep1Confirm = async () => {
    try {
      const values = await form1.validateFields();

      // Explicitly check participants not empty (antd Select multiple with [] passes required validation)
      if (!values.participant_ids || values.participant_ids.length === 0) {
        message.error(t("meetings.form.participantsRequired"));
        return;
      }

      // Extra validation: if participants selected, host and decider must be set
      if (!values.host_id || !values.decider_id) {
        message.error(t("meetings.form.hostDeciderRequired"));
        return;
      }

      setCurrentStep(1);
    } catch {
      // Validation error handled by Form
    }
  };

  const handleStep2Confirm = async () => {
    try {
      const step1Values = form1.getFieldsValue();
      const step2Values = await form2.validateFields();

      // Validate participants selected - compute from form values directly
      const participantIds = step1Values.participant_ids || [];
      if (participantIds.length === 0) {
        message.error(t("meetings.form.participantsRequired"));
        return;
      }

      // Get selected agents directly from agents list using form values
      const selectedAgentsList = agents.filter((a) =>
        participantIds.includes(a.id),
      );

      // Build participants array
      const participants: MeetingParticipant[] = selectedAgentsList.map(
        (agent) => {
          const authKey = agent.auth_key;
          const url = agent.is_internal
            ? `/agents/${agent.internal_agent_id}`
            : agent.url;

          return {
            id: agent.id,
            name: agent.name || agent.id,
            intent: agent.description || undefined,
            endpoint: { url, auth_key: authKey },
          };
        },
      );

      const payload: CreateMeetingRequest = {
        meeting_name: step1Values.topic_title || "未命名会议",
        meeting_type: step2Values.meeting_type,
        topic: {
          title: step1Values.topic_title || "未命名议题",
          description: step1Values.topic_description || undefined,
          context: step2Values.topic_context || undefined,
        },
        participants,
        host_id: step1Values.host_id,
        decider_id: step1Values.decider_id,
        rounds,
      };

      // Add regular meeting specific fields if needed
      if (step2Values.meeting_type === "REGULAR") {
        // These could be added to the payload if the API supports them
        // For now, the API doesn't seem to have these fields in CreateMeetingRequest
      }

      await onSubmit(payload);
      form1.resetFields();
      form2.resetFields();
      setCurrentStep(0);
    } catch {
      // Validation error or submit error handled upstream
    }
  };

  const handleCancel = () => {
    form1.resetFields();
    form2.resetFields();
    setCurrentStep(0);
    onCancel();
  };

  const renderStep0 = () => (
    <Form
      form={form1}
      layout="vertical"
      initialValues={{
        participant_ids: [],
        host_id: undefined,
        decider_id: undefined,
      }}
    >
      <Form.Item
        name="topic_title"
        label={t("meetings.form.topicTitle")}
        rules={[
          { required: true, message: t("meetings.form.topicTitleRequired") },
        ]}
      >
        <Input placeholder={t("meetings.form.topicTitlePlaceholder")} />
      </Form.Item>

      <Form.Item
        name="participant_ids"
        label={t("meetings.form.participants")}
        rules={[
          { required: true, message: t("meetings.form.participantsRequired") },
        ]}
      >
        <Select
          mode="multiple"
          placeholder={t("meetings.form.participantsPlaceholder")}
          loading={loadingAgents}
          allowClear
          showSearch
          optionFilterProp="label"
          options={agents.map((a) => ({
            value: a.id,
            label: a.name || a.id,
          }))}
          maxTagCount={3}
        />
      </Form.Item>

      {selectedAgents.length > 0 && (
        <>
          <Form.Item
            name="host_id"
            label={t("meetings.form.host")}
            rules={[{ required: true }]}
          >
            <Select placeholder={t("meetings.form.hostPlaceholder")}>
              {selectedAgents.map((a) => (
                <Select.Option key={a.id} value={a.id}>
                  <Space>
                    <User size={14} />
                    {a.name || a.id}
                  </Space>
                </Select.Option>
              ))}
            </Select>
          </Form.Item>

          <Form.Item
            name="decider_id"
            label={t("meetings.form.decider")}
            rules={[{ required: true }]}
          >
            <Select placeholder={t("meetings.form.deciderPlaceholder")}>
              {selectedAgents.map((a) => (
                <Select.Option key={a.id} value={a.id}>
                  <Space>
                    <Users size={14} />
                    {a.name || a.id}
                  </Space>
                </Select.Option>
              ))}
            </Select>
          </Form.Item>
        </>
      )}

      <Form.Item
        name="topic_description"
        label={t("meetings.form.flowDescription")}
        tooltip={t("meetings.form.flowDescriptionTip")}
      >
        <TextArea
          rows={4}
          placeholder={t("meetings.form.flowDescriptionPlaceholder")}
        />
      </Form.Item>

      <Form.Item label=" ">
        <Button
          icon={<Sparkles size={16} />}
          onClick={handleGenerateFlowDescription}
          loading={generatingFlow}
        >
          {t("meetings.form.autoGenerate")}
        </Button>
      </Form.Item>
    </Form>
  );

  const renderStep1 = () => {
    const step1Values = form1.getFieldsValue();
    const participantIds = step1Values.participant_ids || [];
    const selectedAgentsList = agents.filter((a) =>
      participantIds.includes(a.id),
    );

    return (
      <>
        {/* Topic Card */}
        <Card size="small" style={{ marginBottom: 16, background: "#fafafa" }}>
          <Text strong style={{ fontSize: 16 }}>
            {step1Values.topic_title || "-"}
          </Text>
          {step1Values.topic_description && (
            <Text type="secondary" style={{ display: "block", marginTop: 4 }}>
              {step1Values.topic_description}
            </Text>
          )}
        </Card>

        {/* Participants Info */}
        <div style={{ marginBottom: 16 }}>
          <Text type="secondary">
            <Users size={14} style={{ marginRight: 4 }} />
            {t("meetings.form.participants")}:{" "}
            {selectedAgentsList.map((a) => a.name || a.id).join(", ") ||
              t("meetings.form.noParticipants")}
          </Text>
        </div>

        <Form
          form={form2}
          layout="vertical"
          initialValues={{
            meeting_type: "TEMPORARY",
            topic_context: "",
            decision_principles: "",
          }}
        >
          <Form.Item name="meeting_type" label={t("meetings.form.meetingType")}>
            <Radio.Group>
              <Radio.Button value="TEMPORARY">
                {t("meetings.type.temporary")}
              </Radio.Button>
              <Radio.Button value="REGULAR">
                {t("meetings.type.regular")}
              </Radio.Button>
            </Radio.Group>
          </Form.Item>

          {watchedMeetingType === "REGULAR" && (
            <>
              <Divider orientation="left" orientationMargin={0}>
                {t("meetings.form.regularMeetingOptions")}
              </Divider>
              <Space direction="vertical" style={{ width: "100%" }}>
                <Form.Item
                  name="fixed_interval_minutes"
                  label={t("meetings.form.fixedInterval")}
                  style={{ marginBottom: 8 }}
                >
                  <InputNumber
                    min={1}
                    max={1440}
                    addonAfter={t("meetings.form.minutes")}
                    placeholder={t("meetings.form.fixedIntervalPlaceholder")}
                    style={{ width: 200 }}
                  />
                </Form.Item>
                <Text type="secondary" style={{ marginBottom: 8 }}>
                  {t("meetings.form.or")}
                </Text>
                <Form.Item
                  name="fixed_time_daily"
                  label={t("meetings.form.fixedTimeDaily")}
                  style={{ marginBottom: 8 }}
                >
                  <Input placeholder="HH:mm" style={{ width: 120 }} />
                </Form.Item>
              </Space>
            </>
          )}

          <Divider orientation="left" orientationMargin={0}>
            {t("meetings.form.topicDetails")}
          </Divider>

          <Form.Item
            name="topic_context"
            label={t("meetings.form.topicBackground")}
          >
            <TextArea
              rows={3}
              placeholder={t("meetings.form.topicBackgroundPlaceholder")}
            />
          </Form.Item>

          <Form.Item
            name="decision_principles"
            label={t("meetings.form.decisionPrinciples")}
          >
            <TextArea
              rows={3}
              placeholder={t("meetings.form.decisionPrinciplesPlaceholder")}
            />
          </Form.Item>

          <Divider orientation="left" orientationMargin={0}>
            {t("meetings.form.roundsAndOrder")}
          </Divider>

          <Form.Item label={t("meetings.form.roundsAndOrder")}>
            {rounds.map((round, idx) => (
              <Radio.Group
                key={idx}
                value={round}
                onChange={(e) => {
                  const newRounds = [...rounds];
                  newRounds[idx] = e.target.value;
                  setRounds(newRounds);
                }}
                style={{ marginBottom: 8, display: "block" }}
              >
                <Space>
                  <Text>第 {idx + 1} 轮：</Text>
                  <Radio.Button value="raw">
                    {t("meetings.round.raw")}
                  </Radio.Button>
                  <Radio.Button value="reverse">
                    {t("meetings.round.reverse")}
                  </Radio.Button>
                  <Radio.Button value="random">
                    {t("meetings.round.random")}
                  </Radio.Button>
                  <Radio.Button value="alphabet">
                    {t("meetings.round.alphabet")}
                  </Radio.Button>
                  {rounds.length > 1 && (
                    <Button
                      type="text"
                      danger
                      size="small"
                      onClick={() =>
                        setRounds(rounds.filter((_, i) => i !== idx))
                      }
                    >
                      删除
                    </Button>
                  )}
                </Space>
              </Radio.Group>
            ))}
            <Button
              type="dashed"
              onClick={() => setRounds([...rounds, "raw"])}
              style={{ marginTop: 8 }}
            >
              + 添加轮次
            </Button>
          </Form.Item>

          <Form.Item label=" ">
            <Button
              icon={<Sparkles size={16} />}
              onClick={handleGenerateDetails}
              loading={generatingDetails}
            >
              {t("meetings.form.generateDetails")}
            </Button>
          </Form.Item>
        </Form>
      </>
    );
  };

  const steps = [
    {
      title: t("meetings.steps.basicInfo"),
    },
    {
      title: t("meetings.steps.meetingDetails"),
    },
  ];

  return (
    <Modal
      open={open}
      title={t("meetings.createTitle")}
      onCancel={handleCancel}
      width={680}
      destroyOnClose
      footer={
        currentStep === 0 ? (
          <Space>
            <Button onClick={handleCancel}>{t("common.cancel")}</Button>
            <Button
              type="primary"
              onClick={handleStep1Confirm}
              disabled={loadingAgents}
            >
              {loadingAgents ? t("common.loading") : t("common.next")}
            </Button>
          </Space>
        ) : (
          <Space>
            <Button onClick={() => setCurrentStep(0)}>
              {t("common.back")}
            </Button>
            <Button onClick={handleCancel}>{t("common.cancel")}</Button>
            <Button
              type="primary"
              onClick={handleStep2Confirm}
              loading={submitting}
            >
              {t("common.create")}
            </Button>
          </Space>
        )
      }
    >
      <Steps current={currentStep} items={steps} style={{ marginBottom: 24 }} />

      {/* Keep both forms mounted to preserve values across steps */}
      <div style={{ display: currentStep === 0 ? "block" : "none" }}>
        {renderStep0()}
      </div>
      <div style={{ display: currentStep === 1 ? "block" : "none" }}>
        {renderStep1()}
      </div>
    </Modal>
  );
}
