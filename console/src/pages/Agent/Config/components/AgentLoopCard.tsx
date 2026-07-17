import { useState } from "react";
import {
  Alert,
  Card,
  Form,
  InputNumber,
  Select,
  Switch,
  Input,
  Button,
  Tabs,
  Tag,
  Modal,
} from "@agentscope-ai/design";
import {
  Plus,
  Trash2,
  ChevronDown,
  ChevronRight,
  Repeat,
  Shield,
  CheckCircle,
  Info,
  Target,
  Rocket,
  Gauge,
  Wallet,
  Lock,
  GripVertical,
  Clock3,
  Wrench,
  ListChecks,
  Copy,
  Sparkles,
} from "lucide-react";
import {
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useTranslation } from "react-i18next";
import type {
  CustomGateType,
  CustomLoopModeConfig,
  GateInstanceConfig,
} from "@/api/types";
import styles from "../index.module.less";
import loopStyles from "./AgentLoopCard.module.less";

const ACTION_OPTIONS = [
  { value: "modify_prompt", label: "Send Reminder" },
  { value: "stop", label: "Pause & Ask for Help" },
];

function SectionHeader({
  icon,
  title,
}: {
  icon: React.ReactNode;
  title: string;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        marginBottom: 16,
        paddingBottom: 8,
        borderBottom: "1px solid var(--border-color, #f0f0f0)",
      }}
    >
      {icon}
      <span style={{ fontWeight: 600, fontSize: 14 }}>{title}</span>
    </div>
  );
}

function IterationSection() {
  const { t } = useTranslation();
  const form = Form.useFormInstance();
  const enabled = Form.useWatch(["loop", "iteration", "enabled"], form);

  return (
    <div>
      <SectionHeader
        icon={<Repeat size={16} style={{ opacity: 0.7 }} />}
        title={t("agentConfig.iterationTitle", "Iteration Limit")}
      />
      <Form.Item
        name={["loop", "iteration", "enabled"]}
        label={t("agentConfig.iterationEnabled", "Enable Iteration Limit")}
        valuePropName="checked"
        tooltip={t(
          "agentConfig.iterationEnabledTooltip",
          "Stop the agent after a fixed number of loop turns",
        )}
      >
        <Switch />
      </Form.Item>
      {enabled && (
        <Form.Item
          name={["loop", "iteration", "max_iterations"]}
          label={t("agentConfig.iterationMaxIterations", "Maximum Iterations")}
          tooltip={t(
            "agentConfig.iterationMaxIterationsTooltip",
            "Maximum number of loop turns before stopping",
          )}
        >
          <InputNumber min={1} max={500} style={{ width: 200 }} />
        </Form.Item>
      )}
    </div>
  );
}

function DoomLoopSection() {
  const { t } = useTranslation();
  const form = Form.useFormInstance();
  const [advanced, setAdvanced] = useState(false);
  const enabled = Form.useWatch(["loop", "doom_loop", "enabled"], form);
  const stages = Form.useWatch(["loop", "doom_loop", "stages"], form) || [];

  return (
    <div>
      <SectionHeader
        icon={<Shield size={16} style={{ opacity: 0.7 }} />}
        title={t("agentConfig.doomLoopEnabled", "Repetition Protection")}
      />
      <Form.Item
        name={["loop", "doom_loop", "enabled"]}
        label={t("agentConfig.doomLoopEnabled", "Repetition Protection")}
        valuePropName="checked"
        tooltip={t(
          "agentConfig.doomLoopEnabledTooltip",
          "Automatically intervene when the agent gets stuck repeating the same actions",
        )}
      >
        <Switch />
      </Form.Item>

      {enabled && (
        <>
          {!advanced && (
            <div style={{ marginBottom: 16 }}>
              {stages.map(
                (
                  stage: {
                    after: number;
                    action: string;
                    prompt: string;
                  },
                  idx: number,
                ) => (
                  <div
                    key={idx}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      marginBottom: 8,
                    }}
                  >
                    <span
                      style={{
                        color: "var(--text-secondary, rgba(0,0,0,0.45))",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {t("agentConfig.doomLoopAfter", "After")}{" "}
                      <strong>{stage.after}</strong>{" "}
                      {t(
                        "agentConfig.doomLoopRepetitions",
                        "identical actions",
                      )}{" "}
                      →
                    </span>
                    <span>
                      {stage.action === "stop"
                        ? t(
                            "agentConfig.doomLoopStopAction",
                            "Pause & Ask for Help",
                          )
                        : t("agentConfig.doomLoopWarnAction", "Send Reminder")}
                    </span>
                  </div>
                ),
              )}
            </div>
          )}

          <Button
            type="link"
            size="small"
            onClick={() => setAdvanced(!advanced)}
            style={{ padding: 0, marginBottom: 16 }}
          >
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
              }}
            >
              {advanced ? (
                <ChevronDown size={14} />
              ) : (
                <ChevronRight size={14} />
              )}
              {advanced
                ? t("agentConfig.simpleMode", "Simple")
                : t("agentConfig.advancedMode", "Advanced")}
            </span>
          </Button>

          {advanced && (
            <>
              <div className={styles.reactAgentRow}>
                <Form.Item
                  name={["loop", "doom_loop", "window_size"]}
                  label={t("agentConfig.doomLoopWindowSize", "Detection Range")}
                  tooltip={t(
                    "agentConfig.doomLoopWindowSizeTooltip",
                    "How many recent actions to check for repetition",
                  )}
                  className={styles.reactAgentField}
                >
                  <InputNumber min={2} max={20} style={{ width: "100%" }} />
                </Form.Item>

                <Form.Item
                  name={["loop", "doom_loop", "similarity_threshold"]}
                  label={t(
                    "agentConfig.doomLoopSimilarity",
                    "Match Sensitivity",
                  )}
                  tooltip={t(
                    "agentConfig.doomLoopSimilarityTooltip",
                    "How similar actions must be to count as repetition (lower = stricter)",
                  )}
                  className={styles.reactAgentField}
                >
                  <InputNumber
                    min={0}
                    max={1}
                    step={0.05}
                    style={{ width: "100%" }}
                  />
                </Form.Item>
              </div>

              <hr
                style={{
                  border: "none",
                  borderTop: "1px solid var(--border-color)",
                  margin: "12px 0",
                }}
              />
              <strong style={{ display: "block", marginBottom: 12 }}>
                {t("agentConfig.doomLoopStages", "Intervention Rules")}
              </strong>

              <Form.List name={["loop", "doom_loop", "stages"]}>
                {(fields, { add, remove }) => (
                  <>
                    {fields.map(({ key, name, ...rest }) => (
                      <div
                        key={key}
                        style={{
                          display: "flex",
                          gap: 8,
                          marginBottom: 12,
                          alignItems: "flex-start",
                        }}
                      >
                        <Form.Item
                          {...rest}
                          name={[name, "after"]}
                          label={
                            name === 0
                              ? t("agentConfig.doomLoopAfter", "After")
                              : undefined
                          }
                          rules={[{ required: true }]}
                          style={{ flex: 1 }}
                        >
                          <InputNumber
                            min={1}
                            placeholder="N"
                            style={{ width: "100%" }}
                          />
                        </Form.Item>

                        <Form.Item
                          {...rest}
                          name={[name, "action"]}
                          label={
                            name === 0
                              ? t("agentConfig.doomLoopAction", "Action")
                              : undefined
                          }
                          rules={[{ required: true }]}
                          style={{ flex: 1.5 }}
                        >
                          <Select options={ACTION_OPTIONS} />
                        </Form.Item>

                        <Form.Item
                          {...rest}
                          name={[name, "prompt"]}
                          label={
                            name === 0
                              ? t("agentConfig.doomLoopPrompt", "Message")
                              : undefined
                          }
                          style={{ flex: 3 }}
                        >
                          <Input.TextArea
                            rows={1}
                            autoSize={{ minRows: 1, maxRows: 3 }}
                            placeholder={t(
                              "agentConfig.doomLoopPromptPlaceholder",
                              "Reminder message or pause reason...",
                            )}
                          />
                        </Form.Item>

                        <Button
                          type="text"
                          danger
                          icon={<Trash2 size={14} />}
                          onClick={() => remove(name)}
                          style={{ marginTop: name === 0 ? 30 : 0 }}
                        />
                      </div>
                    ))}
                    <Button
                      type="dashed"
                      onClick={() =>
                        add({
                          after:
                            stages.length === 0
                              ? 3
                              : (stages[stages.length - 1]?.after ?? 0) + 1,
                          action: "modify_prompt",
                          prompt: "",
                        })
                      }
                      icon={<Plus size={14} />}
                      style={{ width: "100%" }}
                    >
                      {t("agentConfig.doomLoopAddStage", "Add Rule")}
                    </Button>
                  </>
                )}
              </Form.List>
            </>
          )}
        </>
      )}
    </div>
  );
}

function RubricSection() {
  const { t } = useTranslation();
  const form = Form.useFormInstance();
  const [advanced, setAdvanced] = useState(false);
  const enabled = Form.useWatch(["loop", "rubric", "enabled"], form);

  return (
    <div>
      <SectionHeader
        icon={<CheckCircle size={16} style={{ opacity: 0.7 }} />}
        title={t("agentConfig.rubricTitle", "Completion Check")}
      />
      <p
        style={{
          fontSize: 12,
          color: "var(--text-secondary, rgba(0,0,0,0.45))",
          marginBottom: 12,
          lineHeight: 1.6,
        }}
      >
        {t(
          "agentConfig.rubricDesc",
          "Some LLMs may stop with a text-only response without calling any tool, causing the agent to end prematurely. Enable this to re-prompt the agent and improve task completion.",
        )}
      </p>
      <Form.Item
        name={["loop", "rubric", "enabled"]}
        label={t("agentConfig.rubricEnabled", "Enable Completion Check")}
        valuePropName="checked"
        tooltip={t(
          "agentConfig.rubricEnabledTooltip",
          "Re-prompt the agent when it produces a text-only response without tool calls",
        )}
      >
        <Switch />
      </Form.Item>
      {enabled && (
        <>
          <Form.Item
            name={["loop", "rubric", "prompt"]}
            label={t("agentConfig.rubricPrompt", "Re-prompt Message")}
            tooltip={t(
              "agentConfig.rubricPromptTooltip",
              "The prompt injected when the agent outputs text without tool calls",
            )}
          >
            <Input.TextArea
              autoSize={{ minRows: 2, maxRows: 5 }}
              placeholder={t(
                "agentConfig.rubricPromptPlaceholder",
                "You did not call any tool. If the task is complete, confirm. Otherwise, continue with tool calls.",
              )}
            />
          </Form.Item>

          <Button
            type="link"
            size="small"
            onClick={() => setAdvanced(!advanced)}
            style={{ padding: 0, marginBottom: 12 }}
          >
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
              }}
            >
              {advanced ? (
                <ChevronDown size={14} />
              ) : (
                <ChevronRight size={14} />
              )}
              {advanced
                ? t("agentConfig.simpleMode", "Simple")
                : t("agentConfig.advancedMode", "Advanced")}
            </span>
          </Button>

          {advanced && (
            <Form.Item
              name={["loop", "rubric", "max_interventions"]}
              label={t(
                "agentConfig.rubricMaxInterventions",
                "Max Interventions per Turn",
              )}
              tooltip={t(
                "agentConfig.rubricMaxInterventionsTooltip",
                "Maximum times to re-prompt per turn. Prevents infinite re-prompting if the LLM keeps producing text-only responses.",
              )}
            >
              <InputNumber min={1} max={10} style={{ width: 200 }} />
            </Form.Item>
          )}
        </>
      )}
    </div>
  );
}

function LockedGateCard({
  icon,
  title,
  description,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className={loopStyles.gateCard}>
      <button
        type="button"
        className={loopStyles.gateSummary}
        onClick={() => setExpanded((value) => !value)}
      >
        <span className={loopStyles.lockSlot}>
          <Lock size={14} />
        </span>
        <span className={loopStyles.gateIcon}>{icon}</span>
        <span className={loopStyles.gateCopy}>
          <strong>{title}</strong>
          <small>{description}</small>
        </span>
        {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
      </button>
      {expanded && <div className={loopStyles.gateDetails}>{children}</div>}
    </div>
  );
}

function BuiltInHeader({
  name,
  description,
}: {
  name: string;
  description: string;
}) {
  return (
    <div className={loopStyles.modeHeader}>
      <Tag className={loopStyles.builtInTag}>
        <Lock size={11} /> Built-in
      </Tag>
      <h3>{name}</h3>
      <p>{description}</p>
      <Alert
        type="info"
        showIcon
        icon={<Info size={14} />}
        message="Components and order are locked. Gate values remain editable."
      />
    </div>
  );
}

function DefaultModeTab() {
  return (
    <div className={loopStyles.modeEditor}>
      <BuiltInHeader
        name="Default"
        description="The standard guarded ReAct loop used outside an explicit mode."
      />
      <div className={loopStyles.pipelineHeader}>Gate pipeline</div>
      <LockedGateCard
        icon={<Shield size={15} />}
        title="Repetition protection"
        description="Detect repeated tool calls and intervene."
      >
        <DoomLoopSection />
      </LockedGateCard>
      <LockedGateCard
        icon={<Repeat size={15} />}
        title="Iteration limit"
        description="Bound the number of ReAct iterations."
      >
        <IterationSection />
      </LockedGateCard>
      <LockedGateCard
        icon={<CheckCircle size={15} />}
        title="Early-stop retry"
        description="Verify text-only completion before stopping."
      >
        <RubricSection />
      </LockedGateCard>
    </div>
  );
}

function GoalModeTab() {
  return (
    <div className={loopStyles.modeEditor}>
      <BuiltInHeader
        name="Goal"
        description="A bounded persistent loop for concrete, verifiable goals."
      />
      <div className={loopStyles.pipelineHeader}>Gate pipeline</div>
      <LockedGateCard
        icon={<Target size={15} />}
        title="Goal turn limit"
        description="Limit turns within one active goal."
      >
        <Form.Item
          name={["loop", "goal", "max_iterations"]}
          label="Maximum goal turns"
        >
          <InputNumber min={1} max={500} style={{ width: 220 }} />
        </Form.Item>
      </LockedGateCard>
      <LockedGateCard
        icon={<Wallet size={15} />}
        title="Goal token budget"
        description="Stop when the complete goal reaches its budget."
      >
        <Form.Item
          name={["loop", "goal", "max_tokens"]}
          label="Maximum goal tokens"
        >
          <InputNumber min={1} style={{ width: 220 }} />
        </Form.Item>
      </LockedGateCard>
      <LockedGateCard
        icon={<CheckCircle size={15} />}
        title="Goal completion check"
        description="Read the explicit goal status before stopping."
      >
        <p className={loopStyles.readOnlyCopy}>
          Completion is controlled by the built-in goal status protocol.
        </p>
      </LockedGateCard>
    </div>
  );
}

function MissionModeTab() {
  return (
    <div className={loopStyles.modeEditor}>
      <BuiltInHeader
        name="Mission"
        description="A persistent pipeline for longer-running, multi-step missions."
      />
      <div className={loopStyles.pipelineHeader}>Gate pipeline</div>
      <LockedGateCard
        icon={<Rocket size={15} />}
        title="Mission progress check"
        description="Continue until mission stories pass or the limit is reached."
      >
        <Form.Item
          name={["loop", "mission", "max_iterations"]}
          label="Default mission iterations"
        >
          <InputNumber min={1} max={100} style={{ width: 220 }} />
        </Form.Item>
      </LockedGateCard>
    </div>
  );
}

type GateDefinition = {
  type: CustomGateType;
  title: string;
  description: string;
  icon: React.ReactNode;
  defaults: Record<string, unknown>;
};

function PerToolLimits({
  value = {},
  onChange,
}: {
  value?: Record<string, number>;
  onChange?: (value: Record<string, number>) => void;
}) {
  const entries = Object.entries(value);
  const updateName = (oldName: string, nextName: string) => {
    const normalized = nextName.trim();
    if (!normalized || (normalized !== oldName && normalized in value)) return;
    const next = { ...value };
    const limit = next[oldName];
    delete next[oldName];
    next[normalized] = limit;
    onChange?.(next);
  };
  const updateLimit = (name: string, limit: number | null) =>
    onChange?.({ ...value, [name]: limit || 1 });
  const addLimit = () => {
    let name = "tool-name";
    let suffix = 2;
    while (name in value) {
      name = `tool-name-${suffix}`;
      suffix += 1;
    }
    onChange?.({ ...value, [name]: 3 });
  };

  return (
    <div className={loopStyles.toolLimitList}>
      {entries.map(([name, limit]) => (
        <div className={loopStyles.toolLimitRow} key={name}>
          <Input
            value={name}
            aria-label="Tool name"
            onBlur={(event) => updateName(name, event.target.value)}
            onPressEnter={(event) =>
              updateName(name, event.currentTarget.value)
            }
          />
          <InputNumber
            min={1}
            max={10000}
            value={limit}
            aria-label={`${name} call limit`}
            onChange={(next) => updateLimit(name, next)}
          />
          <Button
            type="text"
            icon={<Trash2 size={14} />}
            aria-label={`Remove ${name} limit`}
            onClick={() => {
              const next = { ...value };
              delete next[name];
              onChange?.(next);
            }}
          />
        </div>
      ))}
      <Button icon={<Plus size={14} />} onClick={addLimit}>
        Add per-tool limit
      </Button>
    </div>
  );
}

const GATE_DEFINITIONS: GateDefinition[] = [
  {
    type: "iteration",
    title: "Iteration limit",
    description: "Stop after a fixed number of loop iterations.",
    icon: <Repeat size={15} />,
    defaults: { max_iterations: 40 },
  },
  {
    type: "doom_loop",
    title: "Repetition protection",
    description: "Detect repeated tool calls and change strategy.",
    icon: <Shield size={15} />,
    defaults: { window_size: 3, similarity_threshold: 1 },
  },
  {
    type: "token_budget",
    title: "Token budget",
    description: "Limit prompt and completion token usage.",
    icon: <Gauge size={15} />,
    defaults: { max_total_tokens: 120000 },
  },
  {
    type: "timeout",
    title: "Time limit",
    description: "Stop at a loop boundary after elapsed time.",
    icon: <Clock3 size={15} />,
    defaults: { max_seconds: 1800 },
  },
  {
    type: "tool_call_budget",
    title: "Tool-call budget",
    description: "Limit all calls and selected tools.",
    icon: <Wrench size={15} />,
    defaults: { max_calls: 30, per_tool: {} },
  },
  {
    type: "text_response_retry",
    title: "Early-stop retry",
    description: "Prompt the agent to verify before ending.",
    icon: <CheckCircle size={15} />,
    defaults: {
      prompt: "Verify the task before stopping. Continue if work remains.",
      max_interventions: 1,
    },
  },
  {
    type: "completion_rubric",
    title: "Completion rubric",
    description: "Evaluate explicit criteria and revise when needed.",
    icon: <ListChecks size={15} />,
    defaults: {
      criteria: [
        {
          id: "complete-request",
          description: "Every explicit requirement is addressed.",
          required: true,
          weight: 1,
        },
      ],
      pass_threshold: 1,
      max_revisions: 2,
      evaluate_when: "text_response",
      include_last_tool_results: 5,
      on_grader_error: "stop",
    },
  },
];

function gateDefinition(type: CustomGateType) {
  return GATE_DEFINITIONS.find((item) => item.type === type)!;
}

function GateParamsEditor({
  modeIndex,
  gateIndex,
  type,
}: {
  modeIndex: number;
  gateIndex: number;
  type: CustomGateType;
}) {
  const base = [
    "loop",
    "custom_modes",
    modeIndex,
    "gates",
    gateIndex,
    "params",
  ];
  if (type === "iteration") {
    return (
      <Form.Item name={[...base, "max_iterations"]} label="Maximum iterations">
        <InputNumber min={1} max={500} style={{ width: "100%" }} />
      </Form.Item>
    );
  }
  if (type === "doom_loop") {
    return (
      <div className={loopStyles.fieldGrid}>
        <Form.Item name={[...base, "window_size"]} label="History window">
          <InputNumber min={2} max={20} style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item
          name={[...base, "similarity_threshold"]}
          label="Similarity threshold"
        >
          <InputNumber min={0} max={1} step={0.05} style={{ width: "100%" }} />
        </Form.Item>
      </div>
    );
  }
  if (type === "token_budget") {
    return (
      <>
        <div className={loopStyles.fieldGrid}>
          <Form.Item name={[...base, "max_total_tokens"]} label="Total tokens">
            <InputNumber min={1} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item
            name={[...base, "max_prompt_tokens"]}
            label="Prompt tokens"
          >
            <InputNumber min={1} style={{ width: "100%" }} />
          </Form.Item>
        </div>
        <Form.Item
          name={[...base, "max_completion_tokens"]}
          label="Completion tokens"
        >
          <InputNumber min={1} style={{ width: "100%" }} />
        </Form.Item>
      </>
    );
  }
  if (type === "timeout") {
    return (
      <Form.Item name={[...base, "max_seconds"]} label="Maximum seconds">
        <InputNumber min={1} max={86400} style={{ width: "100%" }} />
      </Form.Item>
    );
  }
  if (type === "tool_call_budget") {
    return (
      <>
        <Form.Item name={[...base, "max_calls"]} label="All tool calls">
          <InputNumber min={1} max={10000} style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item name={[...base, "per_tool"]} label="Per-tool limits">
          <PerToolLimits />
        </Form.Item>
      </>
    );
  }
  if (type === "text_response_retry") {
    return (
      <>
        <Form.Item
          name={[...base, "max_interventions"]}
          label="Maximum retries"
        >
          <InputNumber min={1} max={10} style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item name={[...base, "prompt"]} label="Retry instruction">
          <Input.TextArea autoSize={{ minRows: 2, maxRows: 5 }} />
        </Form.Item>
      </>
    );
  }
  return (
    <>
      <div className={loopStyles.fieldGrid}>
        <Form.Item name={[...base, "pass_threshold"]} label="Pass threshold">
          <InputNumber min={0} max={1} step={0.05} style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item name={[...base, "max_revisions"]} label="Maximum revisions">
          <InputNumber min={0} max={10} style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item
          name={[...base, "include_last_tool_results"]}
          label="Tool results as evidence"
        >
          <InputNumber min={0} max={20} style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item name={[...base, "on_grader_error"]} label="Grader error">
          <Select
            options={[
              { value: "stop", label: "Stop safely" },
              { value: "continue_once", label: "Verify once more" },
            ]}
          />
        </Form.Item>
      </div>
      <Form.List name={[...base, "criteria"]}>
        {(fields, { add, remove }) => (
          <div className={loopStyles.criteriaList}>
            <span className={loopStyles.fieldLabel}>Completion criteria</span>
            {fields.map((field, index) => (
              <div className={loopStyles.criterionRow} key={field.key}>
                <span>{index + 1}</span>
                <Form.Item name={[field.name, "id"]} hidden>
                  <Input />
                </Form.Item>
                <Form.Item name={[field.name, "description"]} noStyle>
                  <Input placeholder="Describe observable completion" />
                </Form.Item>
                <label className={loopStyles.inlineControl}>
                  <small>Required</small>
                  <Form.Item
                    name={[field.name, "required"]}
                    valuePropName="checked"
                    noStyle
                  >
                    <Switch size="small" />
                  </Form.Item>
                </label>
                <label className={loopStyles.inlineControl}>
                  <small>Weight</small>
                  <Form.Item name={[field.name, "weight"]} noStyle>
                    <InputNumber min={0.1} max={100} step={0.1} />
                  </Form.Item>
                </label>
                <Button
                  type="text"
                  icon={<Trash2 size={14} />}
                  onClick={() => remove(field.name)}
                />
              </div>
            ))}
            <Button
              icon={<Plus size={14} />}
              onClick={() =>
                add({
                  id: `criterion-${fields.length + 1}`,
                  description: "",
                  required: true,
                  weight: 1,
                })
              }
            >
              Add criterion
            </Button>
          </div>
        )}
      </Form.List>
    </>
  );
}

function SortableGateCard({
  modeIndex,
  gateIndex,
  gate,
  onRemove,
  onMove,
}: {
  modeIndex: number;
  gateIndex: number;
  gate: GateInstanceConfig;
  onRemove: () => void;
  onMove: (offset: number) => void;
}) {
  const [expanded, setExpanded] = useState(gate.type === "completion_rubric");
  const definition = gateDefinition(gate.type);
  const { attributes, listeners, setNodeRef, transform, transition } =
    useSortable({ id: gate.id });
  return (
    <div
      ref={setNodeRef}
      className={loopStyles.gateCard}
      style={{ transform: CSS.Transform.toString(transform), transition }}
    >
      <div className={loopStyles.gateSummary}>
        <button
          type="button"
          className={loopStyles.dragHandle}
          {...attributes}
          {...listeners}
          aria-label={`Move ${definition.title}`}
        >
          <GripVertical size={15} />
        </button>
        <span className={loopStyles.gateIcon}>{definition.icon}</span>
        <button
          type="button"
          className={loopStyles.gateCopy}
          onClick={() => setExpanded((value) => !value)}
        >
          <strong>{definition.title}</strong>
          <small>{definition.description}</small>
        </button>
        <div className={loopStyles.gateActions}>
          <Button type="text" size="small" onClick={() => onMove(-1)}>
            <ChevronDown className={loopStyles.moveUp} size={14} />
          </Button>
          <Button type="text" size="small" onClick={() => onMove(1)}>
            <ChevronDown size={14} />
          </Button>
          <Button
            type="text"
            size="small"
            icon={<Trash2 size={14} />}
            onClick={onRemove}
          />
          <Button
            type="text"
            size="small"
            icon={
              expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />
            }
            onClick={() => setExpanded((value) => !value)}
          />
        </div>
      </div>
      {expanded && (
        <div className={loopStyles.gateDetails}>
          <GateParamsEditor
            modeIndex={modeIndex}
            gateIndex={gateIndex}
            type={gate.type}
          />
        </div>
      )}
    </div>
  );
}

function CustomModeEditor({
  modeIndex,
  onDelete,
  onDuplicate,
}: {
  modeIndex: number;
  onDelete: () => void;
  onDuplicate: () => void;
}) {
  const form = Form.useFormInstance();
  const gates =
    (Form.useWatch(
      ["loop", "custom_modes", modeIndex, "gates"],
      form,
    ) as GateInstanceConfig[]) || [];
  const sensors = useSensors(useSensor(PointerSensor));
  const path = ["loop", "custom_modes", modeIndex, "gates"];
  const updateGates = (next: GateInstanceConfig[]) =>
    form.setFieldValue(path, next);
  const usedTypes = new Set(gates.map((gate) => gate.type));
  const available = GATE_DEFINITIONS.filter(
    (definition) =>
      !usedTypes.has(definition.type) &&
      !(
        definition.type === "completion_rubric" &&
        usedTypes.has("text_response_retry")
      ) &&
      !(
        definition.type === "text_response_retry" &&
        usedTypes.has("completion_rubric")
      ),
  );

  const addGate = (type: CustomGateType) => {
    const definition = gateDefinition(type);
    updateGates([
      ...gates,
      {
        id: `${type}-${Date.now()}`,
        type,
        enabled: true,
        params: structuredClone(definition.defaults),
      },
    ]);
  };
  const moveGate = (index: number, offset: number) => {
    const target = index + offset;
    if (target < 0 || target >= gates.length) return;
    updateGates(reorderCustomGates(gates, index, target));
  };
  const removeGate = (index: number) => {
    const next = gates.filter((_, itemIndex) => itemIndex !== index);
    updateGates(next);
    if (!next.length) {
      form.setFieldValue(["loop", "custom_modes", modeIndex, "enabled"], false);
    }
  };
  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    const from = gates.findIndex((gate) => gate.id === active.id);
    const to = gates.findIndex((gate) => gate.id === over.id);
    updateGates(reorderCustomGates(gates, from, to));
  };

  return (
    <div className={loopStyles.modeEditor}>
      <div className={loopStyles.customHeader}>
        <div>
          <Tag className={loopStyles.customTag}>
            <Sparkles size={11} /> Custom
          </Tag>
          <p>Build a saved pipeline from QwenPaw-owned gates.</p>
        </div>
        <div>
          <Button type="text" icon={<Copy size={14} />} onClick={onDuplicate}>
            Duplicate
          </Button>
          <Button
            danger
            type="text"
            icon={<Trash2 size={14} />}
            onClick={onDelete}
          >
            Delete
          </Button>
        </div>
      </div>
      <div className={loopStyles.fieldGrid}>
        <Form.Item
          name={["loop", "custom_modes", modeIndex, "name"]}
          label="Display name"
          rules={[{ required: true }]}
        >
          <Input maxLength={80} />
        </Form.Item>
        <Form.Item
          name={["loop", "custom_modes", modeIndex, "slash_command"]}
          label="Slash command"
          rules={[{ required: true }, { pattern: /^[a-z0-9][a-z0-9_-]*$/ }]}
        >
          <Input prefix="/" maxLength={64} />
        </Form.Item>
      </div>
      <Form.Item
        name={["loop", "custom_modes", modeIndex, "description"]}
        label="Description"
      >
        <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} maxLength={500} />
      </Form.Item>
      <Form.Item
        name={["loop", "custom_modes", modeIndex, "enabled"]}
        label="Available to this agent"
        valuePropName="checked"
      >
        <Switch disabled={!gates.length} />
      </Form.Item>

      <div className={loopStyles.pipelineToolbar}>
        <div>
          <strong>Gate pipeline</strong>
          <small>Runs from top to bottom</small>
        </div>
        <Select<CustomGateType>
          placeholder="Add gate"
          className={loopStyles.addGateSelect}
          options={available.map((definition) => ({
            value: definition.type,
            label: definition.title,
          }))}
          onChange={addGate}
          disabled={!available.length}
        />
      </div>
      {!gates.length ? (
        <div className={loopStyles.emptyPipeline}>
          Add at least one gate before enabling this mode.
        </div>
      ) : (
        <DndContext sensors={sensors} onDragEnd={onDragEnd}>
          <SortableContext
            items={gates.map((gate) => gate.id)}
            strategy={verticalListSortingStrategy}
          >
            <div className={loopStyles.gateList}>
              {gates.map((gate, index) => (
                <SortableGateCard
                  key={gate.id}
                  modeIndex={modeIndex}
                  gateIndex={index}
                  gate={gate}
                  onRemove={() => removeGate(index)}
                  onMove={(offset) => moveGate(index, offset)}
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>
      )}
    </div>
  );
}

const TEMPLATES: Record<string, CustomGateType[]> = {
  safe: ["iteration", "token_budget", "doom_loop", "text_response_retry"],
  research: ["iteration", "timeout", "tool_call_budget", "doom_loop"],
  quality: ["iteration", "token_budget", "doom_loop", "completion_rubric"],
  blank: [],
};

function makeGate(
  type: CustomGateType,
  nonce = `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
): GateInstanceConfig {
  const definition = gateDefinition(type);
  return {
    id: `${type}-${nonce}`,
    type,
    enabled: true,
    params: structuredClone(definition.defaults),
  };
}

export function buildCustomLoopMode(
  existing: CustomLoopModeConfig[],
  name: string,
  command: string,
  template: string,
  nonce = Date.now(),
): CustomLoopModeConfig {
  const baseCommand = command || "custom-mode";
  const slashCommand = uniqueValue(
    baseCommand,
    new Set(existing.map((mode) => mode.slash_command)),
  );
  const id = uniqueValue(baseCommand, new Set(existing.map((mode) => mode.id)));
  return {
    id,
    name,
    slash_command: slashCommand,
    description: "A custom gate pipeline.",
    enabled: template !== "blank",
    gates: TEMPLATES[template].map((type, index) =>
      makeGate(type, `${nonce}-${index}`),
    ),
  };
}

function uniqueValue(base: string, existing: Set<string>): string {
  let candidate = base;
  let suffix = 2;
  while (existing.has(candidate)) {
    candidate = `${base}-${suffix}`;
    suffix += 1;
  }
  return candidate;
}

export function reorderCustomGates(
  gates: GateInstanceConfig[],
  from: number,
  to: number,
): GateInstanceConfig[] {
  if (from < 0 || to < 0 || from >= gates.length || to >= gates.length) {
    return gates;
  }
  return arrayMove(gates, from, to);
}

export function AgentLoopCard() {
  const { t } = useTranslation();
  const form = Form.useFormInstance();
  const customModes =
    (Form.useWatch(["loop", "custom_modes"], form) as CustomLoopModeConfig[]) ||
    [];
  const [activeKey, setActiveKey] = useState("default");
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("New Loop Mode");
  const [newCommand, setNewCommand] = useState("new-mode");
  const [template, setTemplate] = useState("safe");

  const setModes = (modes: CustomLoopModeConfig[]) =>
    form.setFieldValue(["loop", "custom_modes"], modes);
  const createMode = () => {
    const mode = buildCustomLoopMode(
      customModes,
      newName,
      newCommand,
      template,
    );
    setModes([...customModes, mode]);
    setActiveKey(`custom:${mode.id}`);
    setCreating(false);
  };
  const duplicateMode = (index: number) => {
    const source = customModes[index];
    const baseId = `${source.id}-copy`;
    const baseCommand = `${source.slash_command}-copy`;
    const copy: CustomLoopModeConfig = {
      ...structuredClone(source),
      id: uniqueValue(baseId, new Set(customModes.map((mode) => mode.id))),
      name: `${source.name} Copy`,
      slash_command: uniqueValue(
        baseCommand,
        new Set(customModes.map((mode) => mode.slash_command)),
      ),
      enabled: false,
    };
    setModes([...customModes, copy]);
    setActiveKey(`custom:${copy.id}`);
  };
  const deleteMode = (index: number) => {
    setModes(customModes.filter((_, itemIndex) => itemIndex !== index));
    setActiveKey("default");
  };

  const tabItems = [
    {
      key: "default",
      label: (
        <span className={loopStyles.builtInTab}>
          <Lock size={12} />
          Default
        </span>
      ),
      children: <DefaultModeTab />,
    },
    {
      key: "goal",
      label: (
        <span className={loopStyles.builtInTab}>
          <Lock size={12} />
          Goal
        </span>
      ),
      children: <GoalModeTab />,
    },
    {
      key: "mission",
      label: (
        <span className={loopStyles.builtInTab}>
          <Lock size={12} />
          Mission
        </span>
      ),
      children: <MissionModeTab />,
    },
    ...customModes.map((mode, index) => ({
      key: `custom:${mode.id}`,
      label: <span className={loopStyles.customTab}>{mode.name}</span>,
      children: (
        <CustomModeEditor
          modeIndex={index}
          onDelete={() => deleteMode(index)}
          onDuplicate={() => duplicateMode(index)}
        />
      ),
    })),
  ];

  return (
    <Card
      className={`${styles.formCard} ${loopStyles.loopCard}`}
      title={t("agentConfig.agentLoopTitle", "Agent Loop Settings")}
    >
      <Tabs
        activeKey={activeKey}
        onChange={setActiveKey}
        items={tabItems}
        size="small"
        tabBarExtraContent={
          <Button
            className={loopStyles.addModeButton}
            icon={<Plus size={15} />}
            onClick={() => setCreating(true)}
            disabled={customModes.length >= 20}
            aria-label="Create custom loop mode"
          />
        }
      />
      <Modal
        title="Create custom loop mode"
        open={creating}
        onCancel={() => setCreating(false)}
        onOk={createMode}
        okButtonProps={{ disabled: !newName.trim() || !newCommand.trim() }}
      >
        <div className={loopStyles.createForm}>
          <label>Display name</label>
          <Input
            value={newName}
            onChange={(event) => setNewName(event.target.value)}
          />
          <label>Slash command</label>
          <Input
            prefix="/"
            value={newCommand}
            onChange={(event) =>
              setNewCommand(
                event.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ""),
              )
            }
          />
          <label>Starting template</label>
          <Select
            value={template}
            onChange={setTemplate}
            options={[
              { value: "safe", label: "Safe run" },
              { value: "research", label: "Budgeted research" },
              { value: "quality", label: "Quality first" },
              { value: "blank", label: "Blank pipeline" },
            ]}
          />
        </div>
      </Modal>
    </Card>
  );
}
