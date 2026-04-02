import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Drawer,
  Flex,
  Modal,
  Progress,
  Tooltip,
  Typography,
  Form,
  Input,
  Button as AntButton,
  message,
  Popconfirm,
} from "antd";
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  DeleteOutlined,
  EditOutlined,
  HistoryOutlined,
  MinusCircleOutlined,
  PlusOutlined,
} from "@ant-design/icons";
import { IconButton, Button } from "@agentscope-ai/design";
import { SparkOperateRightLine } from "@agentscope-ai/icons";
import { useTranslation } from "react-i18next";
import api from "../../api";
import { subscribePlanUpdates } from "../../api/modules/plan";
import type { Plan, PlanSummary, SubTask } from "../../api/types";
import styles from "./index.module.less";

const { Text, Title, Paragraph } = Typography;

const stateIcon = (state: SubTask["state"]) => {
  switch (state) {
    case "done":
      return <CheckCircleOutlined style={{ color: "#52c41a" }} />;
    case "in_progress":
      return (
        <ClockCircleOutlined
          style={{ color: "#faad14" }}
          className={styles.pulse}
        />
      );
    case "abandoned":
      return <CloseCircleOutlined style={{ color: "#ff4d4f" }} />;
    default:
      return <MinusCircleOutlined style={{ color: "#bfbfbf" }} />;
  }
};

interface PlanPanelProps {
  open: boolean;
  onClose: () => void;
  /** After plan is confirmed via API, submit the same chat kickoff as typing in the input. */
  onStartExecution?: () => void;
}

const PlanPanel: React.FC<PlanPanelProps> = ({
  open,
  onClose,
  onStartExecution,
}) => {
  const { t } = useTranslation();
  const [plan, setPlan] = useState<Plan | null>(null);
  const [planEnabled, setPlanEnabled] = useState<boolean | null>(null);
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<PlanSummary[]>([]);
  const [enabling, setEnabling] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [editIdx, setEditIdx] = useState<number | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [editForm] = Form.useForm();
  const [addForm] = Form.useForm();

  const fetchState = useCallback(() => {
    api
      .getPlanConfig()
      .then((cfg) => setPlanEnabled(cfg.enabled))
      .catch(() => setPlanEnabled(false));
    api
      .getCurrentPlan()
      .then(setPlan)
      .catch(() => setPlan(null));
  }, []);

  useEffect(() => {
    if (!open) return;
    fetchState();
  }, [open, fetchState]);

  useEffect(() => {
    if (!open || !planEnabled) return;
    const unsub = subscribePlanUpdates((updated) => setPlan(updated));
    return unsub;
  }, [open, planEnabled]);

  const doneCount = useMemo(
    () => plan?.subtasks.filter((s) => s.state === "done").length ?? 0,
    [plan],
  );
  const totalCount = plan?.subtasks.length ?? 0;
  const percent =
    totalCount > 0 ? Math.round((doneCount / totalCount) * 100) : 0;

  const isActive =
    plan !== null && plan.state !== "done" && plan.state !== "abandoned";

  const needsConfirmation =
    isActive && plan.subtasks.every((s) => s.state === "todo");

  // --- handlers ---

  const handleShowHistory = useCallback(async () => {
    try {
      const data = await api.getPlanHistory();
      setHistory(data);
      setHistoryOpen(true);
    } catch {
      // ignore
    }
  }, []);

  const handleRecover = useCallback(
    async (planId: string) => {
      try {
        const recovered = await api.recoverPlan(planId);
        setPlan(recovered);
        setHistoryOpen(false);
        message.success(
          t("plan.restoreSuccess", "Plan restored successfully"),
        );
      } catch {
        message.error(t("plan.restoreError", "Failed to restore plan"));
      }
    },
    [t],
  );

  const handleStopPlan = useCallback(async () => {
    setStopping(true);
    try {
      await api.finishPlan({
        state: "abandoned",
        outcome: "Manually stopped by user",
      });
      setPlan(null);
      message.success(
        t("plan.stoppedSuccess", "Plan has been stopped"),
      );
    } catch {
      message.error(
        t("plan.stoppedError", "Failed to stop plan"),
      );
    } finally {
      setStopping(false);
    }
  }, [t]);

  const handleDeleteHistoryPlan = useCallback(
    async (planId: string) => {
      try {
        await api.deletePlan(planId);
        setHistory((prev) => prev.filter((h) => h.plan_id !== planId));
        message.success(
          t("plan.deleteHistorySuccess", "Historical plan deleted"),
        );
      } catch {
        message.error(
          t("plan.deleteHistoryError", "Failed to delete plan"),
        );
      }
    },
    [t],
  );

  const handleEnablePlan = useCallback(async () => {
    setEnabling(true);
    try {
      await api.updatePlanConfig({
        enabled: true,
        max_subtasks: null,
        storage_type: "memory",
        storage_path: null,
        agent_managed: true,
      });
      setPlanEnabled(true);
      message.success(
        t("plan.enabledSuccess", "Plan mode enabled successfully"),
      );
    } catch {
      message.error(t("plan.enabledError", "Failed to enable plan mode"));
    } finally {
      setEnabling(false);
    }
  }, [t]);

  const handleConfirmPlan = useCallback(async () => {
    setConfirming(true);
    try {
      await api.confirmPlan();
      if (onStartExecution) {
        onStartExecution();
        message.success(
          t(
            "plan.confirmedAndStarted",
            "Plan confirmed. Execution started from the console.",
          ),
        );
      } else {
        message.success(
          t(
            "plan.confirmedSuccess",
            "Plan confirmed! Send a message to start execution.",
          ),
        );
      }
    } catch {
      message.error(t("plan.confirmedError", "Failed to confirm plan"));
    } finally {
      setConfirming(false);
    }
  }, [t, onStartExecution]);

  const handleAbandonPlan = useCallback(async () => {
    try {
      await api.finishPlan({
        state: "abandoned",
        outcome: "Cancelled by user",
      });
      setPlan(null);
      message.success(
        t("plan.cancelledSuccess", "Plan cancelled"),
      );
    } catch {
      message.error(t("plan.cancelledError", "Failed to cancel plan"));
    }
  }, [t]);

  // --- subtask edit / add / delete (available in confirmation state) ---

  const handleEditSubtask = useCallback(
    (idx: number) => {
      if (!plan) return;
      const st = plan.subtasks[idx];
      editForm.setFieldsValue({
        name: st.name,
        description: st.description,
        expected_outcome: st.expected_outcome,
      });
      setEditIdx(idx);
    },
    [plan, editForm],
  );

  const handleEditSubmit = useCallback(async () => {
    if (editIdx === null) return;
    try {
      const values = await editForm.validateFields();
      const updated = await api.revisePlan({
        subtask_idx: editIdx,
        action: "revise",
        subtask: {
          name: values.name,
          description: values.description,
          expected_outcome: values.expected_outcome,
        },
      });
      setPlan(updated);
      setEditIdx(null);
      editForm.resetFields();
    } catch {
      message.error(t("plan.editError", "Failed to update subtask"));
    }
  }, [editIdx, editForm, t]);

  const handleDeleteSubtask = useCallback(
    async (idx: number) => {
      try {
        const updated = await api.revisePlan({
          subtask_idx: idx,
          action: "delete",
        });
        setPlan(updated);
      } catch {
        message.error(t("plan.deleteError", "Failed to delete subtask"));
      }
    },
    [t],
  );

  const handleAddSubtask = useCallback(async () => {
    try {
      const values = await addForm.validateFields();
      const insertIdx = plan ? plan.subtasks.length : 0;
      const updated = await api.revisePlan({
        subtask_idx: insertIdx,
        action: "add",
        subtask: {
          name: values.name,
          description: values.description,
          expected_outcome: values.expected_outcome,
        },
      });
      setPlan(updated);
      setAddOpen(false);
      addForm.resetFields();
    } catch {
      message.error(t("plan.addError", "Failed to add subtask"));
    }
  }, [plan, addForm, t]);

  // --- render helpers ---

  const renderSubtaskItem = (st: SubTask, idx: number) => {
    const isExpanded = expandedIdx === idx;
    return (
      <div
        key={idx}
        className={`${styles.subtaskItem} ${
          st.state === "in_progress" ? styles.active : ""
        }`}
        onClick={() => setExpandedIdx(isExpanded ? null : idx)}
      >
        <Flex gap={8} align="center" justify="space-between">
          <Flex gap={8} align="center" style={{ minWidth: 0 }}>
            {stateIcon(st.state)}
            <Text
              strong={st.state === "in_progress"}
              delete={st.state === "abandoned"}
              ellipsis
            >
              {st.name}
            </Text>
          </Flex>
          {needsConfirmation && (
            <Flex gap={4} align="center" onClick={(e) => e.stopPropagation()}>
              <Tooltip title={t("common.edit", "Edit")}>
                <EditOutlined
                  style={{ fontSize: 13, color: "#1677ff", cursor: "pointer" }}
                  onClick={() => handleEditSubtask(idx)}
                />
              </Tooltip>
              <Popconfirm
                title={t("plan.deleteConfirm", "Delete this subtask?")}
                onConfirm={() => handleDeleteSubtask(idx)}
                okText={t("common.yes", "Yes")}
                cancelText={t("common.no", "No")}
              >
                <Tooltip title={t("common.delete", "Delete")}>
                  <DeleteOutlined
                    style={{
                      fontSize: 13,
                      color: "#ff4d4f",
                      cursor: "pointer",
                    }}
                  />
                </Tooltip>
              </Popconfirm>
            </Flex>
          )}
        </Flex>
        {isExpanded && (
          <div className={styles.subtaskDetail}>
            <Paragraph
              type="secondary"
              style={{ margin: "4px 0 0 24px", fontSize: 12 }}
            >
              {st.description}
            </Paragraph>
            <Text
              type="secondary"
              style={{
                display: "block",
                margin: "2px 0 0 24px",
                fontSize: 12,
              }}
            >
              {t("plan.expectedOutcome", "Expected")}: {st.expected_outcome}
            </Text>
          </div>
        )}
      </div>
    );
  };

  return (
    <>
      <Drawer
        open={open}
        onClose={onClose}
        placement="right"
        width={380}
        closable={false}
        title={null}
        styles={{
          header: { display: "none" },
          body: {
            padding: 0,
            display: "flex",
            flexDirection: "column",
            height: "100%",
            overflow: "hidden",
          },
          mask: { background: "transparent" },
        }}
        className={styles.drawer}
      >
        <div className={styles.header}>
          <div className={styles.headerLeft}>
            <span className={styles.headerTitle}>
              {t("plan.title", "Plan")}
            </span>
          </div>
          <Flex gap={8} align="center">
            {planEnabled && (
              <Tooltip title={t("plan.history", "History")}>
                <IconButton
                  bordered={false}
                  icon={<HistoryOutlined />}
                  onClick={handleShowHistory}
                />
              </Tooltip>
            )}
            <IconButton
              bordered={false}
              icon={<SparkOperateRightLine />}
              onClick={onClose}
            />
          </Flex>
        </div>

        <div className={styles.body}>
          {planEnabled === false ? (
            <div className={styles.empty}>
              <Alert
                type="info"
                showIcon
                message={t("plan.notEnabled", "Plan mode is not enabled")}
                description={t(
                  "plan.enableHintShort",
                  "Enable plan mode to let the agent decompose complex tasks into steps and execute them with your approval.",
                )}
                style={{ marginBottom: 16, maxWidth: 320 }}
              />
              <Button
                type="primary"
                loading={enabling}
                onClick={handleEnablePlan}
                style={{ marginTop: 8 }}
              >
                {t("plan.enableButton", "Enable Plan Mode")}
              </Button>
            </div>
          ) : isActive ? (
            <>
              <div className={styles.planHeader}>
                <Title level={5} style={{ margin: 0 }}>
                  {plan.name}
                </Title>
                {plan.description && (
                  <Paragraph
                    type="secondary"
                    style={{ margin: "4px 0 0", fontSize: 12 }}
                    ellipsis={{ rows: 2, expandable: true }}
                  >
                    {plan.description}
                  </Paragraph>
                )}
                <Progress
                  percent={percent}
                  size="small"
                  format={() => `${doneCount}/${totalCount}`}
                  style={{ marginTop: 8 }}
                />
              </div>

              <div className={styles.subtaskList}>
                {plan.subtasks.map((st, idx) => renderSubtaskItem(st, idx))}

                {needsConfirmation && (
                  <AntButton
                    type="dashed"
                    block
                    icon={<PlusOutlined />}
                    style={{ marginTop: 8 }}
                    onClick={() => setAddOpen(true)}
                  >
                    {t("plan.addSubtask", "Add Subtask")}
                  </AntButton>
                )}
              </div>

              <div className={styles.footer}>
                {needsConfirmation ? (
                  <Flex gap={8}>
                    <Popconfirm
                      title={t(
                        "plan.startExecutionConfirm",
                        "Start executing this plan now?",
                      )}
                      description={t(
                        "plan.startExecutionConfirmHint",
                        "The agent will run tools according to the plan. This matches sending a follow-up message in chat.",
                      )}
                      okText={t("plan.startExecution", "Start execution")}
                      cancelText={t("common.cancel", "Cancel")}
                      okButtonProps={{ loading: confirming }}
                      onConfirm={handleConfirmPlan}
                    >
                      <Button type="primary" size="small" disabled={confirming}>
                        {t("plan.startExecution", "Start execution")}
                      </Button>
                    </Popconfirm>
                    <Button size="small" onClick={handleAbandonPlan}>
                      {t("plan.cancel", "Cancel Plan")}
                    </Button>
                  </Flex>
                ) : (
                  <Popconfirm
                    title={t(
                      "plan.stopConfirm",
                      "Stop this plan? The plan will be marked as abandoned.",
                    )}
                    okText={t("plan.stopPlan", "Stop Plan")}
                    cancelText={t("common.cancel", "Cancel")}
                    okButtonProps={{ loading: stopping }}
                    onConfirm={handleStopPlan}
                  >
                    <Button size="small" loading={stopping}>
                      {t("plan.stopPlan", "Stop Plan")}
                    </Button>
                  </Popconfirm>
                )}
              </div>
            </>
          ) : (
            <div className={styles.empty}>
              <Text type="secondary">{t("plan.noPlan", "No active plan")}</Text>
              <Paragraph
                type="secondary"
                style={{
                  margin: "8px 0 0",
                  fontSize: 12,
                  maxWidth: 280,
                  textAlign: "center",
                }}
              >
                {t(
                  "plan.noPlanHint",
                  "Use `/plan <description>` in chat to create a plan.",
                )}
              </Paragraph>
            </div>
          )}
        </div>
      </Drawer>

      {/* History Modal */}
      <Modal
        open={historyOpen}
        onCancel={() => setHistoryOpen(false)}
        title={t("plan.historyTitle", "Plan History")}
        footer={null}
        width={500}
      >
        {history.length === 0 ? (
          <Text type="secondary">
            {t("plan.noHistory", "No historical plans")}
          </Text>
        ) : (
          history.map((h) => (
            <Flex
              key={h.plan_id}
              justify="space-between"
              align="center"
              style={{ padding: "8px 0", borderBottom: "1px solid #f0f0f0" }}
            >
              <div>
                <Text strong>{h.name}</Text>
                <br />
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {h.state} &middot; {h.completed_count}/{h.subtask_count}{" "}
                  &middot; {h.created_at}
                </Text>
              </div>
              <Flex gap={8} align="center">
                <AntButton size="small" onClick={() => handleRecover(h.plan_id)}>
                  {t("plan.restore", "Restore")}
                </AntButton>
                <Popconfirm
                  title={t(
                    "plan.deleteHistoryConfirm",
                    "Delete this historical plan?",
                  )}
                  okText={t("common.delete", "Delete")}
                  cancelText={t("common.cancel", "Cancel")}
                  okButtonProps={{ danger: true }}
                  onConfirm={() => handleDeleteHistoryPlan(h.plan_id)}
                >
                  <Tooltip title={t("common.delete", "Delete")}>
                    <AntButton
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                    />
                  </Tooltip>
                </Popconfirm>
              </Flex>
            </Flex>
          ))
        )}
      </Modal>

      {/* Edit Subtask Modal */}
      <Modal
        open={editIdx !== null}
        onCancel={() => {
          setEditIdx(null);
          editForm.resetFields();
        }}
        title={t("plan.editSubtask", "Edit Subtask")}
        onOk={handleEditSubmit}
        okText={t("common.save", "Save")}
        width={500}
      >
        <Form form={editForm} layout="vertical">
          <Form.Item
            name="name"
            label={t("plan.subtaskName", "Subtask Name")}
            rules={[{ required: true }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="description"
            label={t("plan.description", "Description")}
            rules={[{ required: true }]}
          >
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item
            name="expected_outcome"
            label={t("plan.expectedOutcome", "Expected Outcome")}
            rules={[{ required: true }]}
          >
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      {/* Add Subtask Modal */}
      <Modal
        open={addOpen}
        onCancel={() => {
          setAddOpen(false);
          addForm.resetFields();
        }}
        title={t("plan.addSubtaskTitle", "Add Subtask")}
        onOk={handleAddSubtask}
        okText={t("common.create", "Create")}
        width={500}
      >
        <Form form={addForm} layout="vertical">
          <Form.Item
            name="name"
            label={t("plan.subtaskName", "Subtask Name")}
            rules={[{ required: true }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="description"
            label={t("plan.description", "Description")}
            rules={[{ required: true }]}
          >
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item
            name="expected_outcome"
            label={t("plan.expectedOutcome", "Expected Outcome")}
            rules={[{ required: true }]}
          >
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
};

export default PlanPanel;
