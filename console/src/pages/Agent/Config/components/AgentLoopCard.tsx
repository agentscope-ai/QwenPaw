import { useState } from "react";
import {
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
  Dropdown,
} from "@agentscope-ai/design";
import {
  Plus,
  Trash2,
  ChevronDown,
  ChevronRight,
  Repeat,
  Shield,
  CheckCircle,
  Target,
  Rocket,
  Gauge,
  Wallet,
  Lock,
  GripVertical,
  Wrench,
  ListChecks,
  Copy,
  Sparkles,
  Terminal,
  Clock3,
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

function IterationSection() {
  const { t } = useTranslation();
  const form = Form.useFormInstance();
  const enabled = Form.useWatch(["loop", "iteration", "enabled"], form);

  return (
    <div className={loopStyles.gateForm}>
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
  const enabled = Form.useWatch(["loop", "doom_loop", "enabled"], form);
  const stages = Form.useWatch(["loop", "doom_loop", "stages"], form) || [];
  const actionOptions = [
    {
      value: "modify_prompt",
      label: t("agentConfig.doomLoopWarnAction", "Send Reminder"),
    },
    {
      value: "stop",
      label: t("agentConfig.doomLoopStopAction", "Pause & Ask for Help"),
    },
  ];

  return (
    <div className={loopStyles.gateForm}>
      <Form.Item
        name={["loop", "doom_loop", "enabled"]}
        label={t(
          "agentConfig.loopMode.enableRepetitionProtection",
          "Enable repetition protection",
        )}
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
          <div className={loopStyles.fieldGrid}>
            <Form.Item
              name={["loop", "doom_loop", "window_size"]}
              label={t("agentConfig.doomLoopWindowSize", "Detection Range")}
              tooltip={t(
                "agentConfig.doomLoopWindowSizeTooltip",
                "How many recent actions to check for repetition",
              )}
            >
              <InputNumber min={2} max={20} style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item
              name={["loop", "doom_loop", "similarity_threshold"]}
              label={t("agentConfig.doomLoopSimilarity", "Match Sensitivity")}
              tooltip={t(
                "agentConfig.doomLoopSimilarityTooltip",
                "How similar actions must be to count as repetition (lower = stricter)",
              )}
            >
              <InputNumber
                min={0}
                max={1}
                step={0.05}
                style={{ width: "100%" }}
              />
            </Form.Item>
          </div>
          <div className={loopStyles.subsectionTitle}>
            {t("agentConfig.doomLoopStages", "Intervention Rules")}
          </div>
          <Form.List name={["loop", "doom_loop", "stages"]}>
            {(fields, { add, remove }) => (
              <div className={loopStyles.ruleList}>
                {fields.map(({ key, name, ...rest }) => (
                  <div key={key} className={loopStyles.ruleRow}>
                    <Form.Item
                      {...rest}
                      name={[name, "after"]}
                      label={
                        name === 0
                          ? t("agentConfig.doomLoopAfter", "After")
                          : undefined
                      }
                      rules={[{ required: true }]}
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
                    >
                      <Select options={actionOptions} />
                    </Form.Item>

                    <Form.Item
                      {...rest}
                      name={[name, "prompt"]}
                      label={
                        name === 0
                          ? t("agentConfig.doomLoopPrompt", "Message")
                          : undefined
                      }
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
                      aria-label={t(
                        "agentConfig.loopMode.removeRule",
                        "Remove rule",
                      )}
                      onClick={() => remove(name)}
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
                >
                  {t("agentConfig.doomLoopAddStage", "Add Rule")}
                </Button>
              </div>
            )}
          </Form.List>
        </>
      )}
    </div>
  );
}

function RubricSection() {
  const { t } = useTranslation();
  const form = Form.useFormInstance();
  const enabled = Form.useWatch(["loop", "rubric", "enabled"], form);

  return (
    <div className={loopStyles.gateForm}>
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
          "When the agent produces a text response without tool calls, apply natural-language completion criteria and ask it to continue when work remains.",
        )}
      </p>
      <Form.Item
        name={["loop", "rubric", "enabled"]}
        label={t(
          "agentConfig.rubricEnabled",
          "Enable qualitative completion check",
        )}
        valuePropName="checked"
        tooltip={t(
          "agentConfig.rubricEnabledTooltip",
          "Triggered only when the agent produces a text response without tool calls.",
        )}
      >
        <Switch />
      </Form.Item>
      {enabled && (
        <>
          <Form.Item
            name={["loop", "rubric", "prompt"]}
            label={t(
              "agentConfig.rubricPrompt",
              "Natural-language completion criteria",
            )}
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

          <Form.Item
            name={["loop", "rubric", "max_interventions"]}
            label={t(
              "agentConfig.rubricMaxInterventions",
              "Maximum evaluation rounds",
            )}
            tooltip={t(
              "agentConfig.rubricMaxInterventionsTooltip",
              "Maximum completion checks for text responses without tool calls during one turn.",
            )}
          >
            <InputNumber min={1} max={10} style={{ width: 200 }} />
          </Form.Item>
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

function BuiltInIntro({ description }: { description: string }) {
  const { t } = useTranslation();
  return (
    <div className={loopStyles.builtInIntro}>
      <div className={loopStyles.builtInIntroMain}>
        <Tag className={loopStyles.builtInTag}>
          <Lock size={11} />
          {t("agentConfig.loopMode.builtIn", "Built-in")}
        </Tag>
        <p>{description}</p>
      </div>
      <span className={loopStyles.builtInNote}>
        <Lock size={12} />
        {t(
          "agentConfig.loopMode.builtInNote",
          "Pipeline locked · Values editable",
        )}
      </span>
    </div>
  );
}

function DefaultModeTab() {
  const { t } = useTranslation();
  return (
    <div className={loopStyles.modeEditor}>
      <BuiltInIntro
        description={t(
          "agentConfig.loopMode.defaultDescription",
          "The standard guarded ReAct loop used outside an explicit mode.",
        )}
      />
      <div className={loopStyles.pipelineHeader}>
        {t("agentConfig.loopMode.gatePipeline", "Gate pipeline")}
      </div>
      <LockedGateCard
        icon={<Shield size={15} />}
        title={t(
          "agentConfig.loopMode.repetitionTitle",
          "Repetition protection",
        )}
        description={t(
          "agentConfig.loopMode.repetitionDescription",
          "Detect repeated tool calls and intervene.",
        )}
      >
        <DoomLoopSection />
      </LockedGateCard>
      <LockedGateCard
        icon={<Repeat size={15} />}
        title={t("agentConfig.loopMode.iterationTitle", "Iteration limit")}
        description={t(
          "agentConfig.loopMode.iterationDescription",
          "Bound the number of ReAct iterations.",
        )}
      >
        <IterationSection />
      </LockedGateCard>
      <LockedGateCard
        icon={<CheckCircle size={15} />}
        title={t(
          "agentConfig.loopMode.retryTitle",
          "Qualitative completion check",
        )}
        description={t(
          "agentConfig.loopMode.retryDescription",
          "Triggered when the agent produces a text response without tool calls.",
        )}
      >
        <RubricSection />
      </LockedGateCard>
    </div>
  );
}

function GoalModeTab() {
  const { t } = useTranslation();
  return (
    <div className={loopStyles.modeEditor}>
      <BuiltInIntro
        description={t(
          "agentConfig.loopMode.goalDescription",
          "A bounded persistent loop for concrete, verifiable goals.",
        )}
      />
      <div className={loopStyles.pipelineHeader}>
        {t("agentConfig.loopMode.gatePipeline", "Gate pipeline")}
      </div>
      <LockedGateCard
        icon={<Target size={15} />}
        title={t("agentConfig.loopMode.goalTurnTitle", "Goal turn limit")}
        description={t(
          "agentConfig.loopMode.goalTurnDescription",
          "Limit turns within one active goal.",
        )}
      >
        <Form.Item
          name={["loop", "goal", "max_iterations"]}
          label={t("agentConfig.loopMode.maxGoalTurns", "Maximum goal turns")}
        >
          <InputNumber min={1} max={500} style={{ width: 220 }} />
        </Form.Item>
      </LockedGateCard>
      <LockedGateCard
        icon={<Wallet size={15} />}
        title={t("agentConfig.loopMode.goalBudgetTitle", "Goal token budget")}
        description={t(
          "agentConfig.loopMode.goalBudgetDescription",
          "Stop when the complete goal reaches its budget.",
        )}
      >
        <Form.Item
          name={["loop", "goal", "max_tokens"]}
          label={t("agentConfig.loopMode.maxGoalTokens", "Maximum goal tokens")}
        >
          <InputNumber min={1} style={{ width: 220 }} />
        </Form.Item>
      </LockedGateCard>
      <LockedGateCard
        icon={<CheckCircle size={15} />}
        title={t(
          "agentConfig.loopMode.goalCompletionTitle",
          "Goal completion check",
        )}
        description={t(
          "agentConfig.loopMode.goalCompletionDescription",
          "Read the explicit goal status before stopping.",
        )}
      >
        <p className={loopStyles.readOnlyCopy}>
          {t(
            "agentConfig.loopMode.goalCompletionReadOnly",
            "Completion is controlled by the built-in goal status protocol.",
          )}
        </p>
      </LockedGateCard>
    </div>
  );
}

function MissionModeTab() {
  const { t } = useTranslation();
  return (
    <div className={loopStyles.modeEditor}>
      <BuiltInIntro
        description={t(
          "agentConfig.loopMode.missionDescription",
          "A persistent pipeline for longer-running, multi-step missions.",
        )}
      />
      <div className={loopStyles.pipelineHeader}>
        {t("agentConfig.loopMode.gatePipeline", "Gate pipeline")}
      </div>
      <LockedGateCard
        icon={<Rocket size={15} />}
        title={t(
          "agentConfig.loopMode.missionProgressTitle",
          "Mission progress check",
        )}
        description={t(
          "agentConfig.loopMode.missionProgressDescription",
          "Continue until mission stories pass or the limit is reached.",
        )}
      >
        <p className={loopStyles.readOnlyCopy}>
          {t(
            "agentConfig.loopMode.missionProgressReadOnly",
            "Completion is controlled by the built-in Mission story status.",
          )}
        </p>
      </LockedGateCard>
      <LockedGateCard
        icon={<Gauge size={15} />}
        title={t(
          "agentConfig.loopMode.missionIterationTitle",
          "Mission iteration limit",
        )}
        description={t(
          "agentConfig.loopMode.missionIterationDescription",
          "Set the default execution limit for new Missions.",
        )}
      >
        <Form.Item
          name={["loop", "mission", "max_iterations"]}
          label={t(
            "agentConfig.loopMode.defaultMaxMissionIterations",
            "Default maximum execution rounds",
          )}
          tooltip={t(
            "agentConfig.loopMode.defaultMaxMissionIterationsTooltip",
            "Used when /mission does not specify --max-iterations.",
          )}
        >
          <InputNumber min={1} max={100} style={{ width: 220 }} />
        </Form.Item>
      </LockedGateCard>
      <LockedGateCard
        icon={<Wrench size={15} />}
        title={t("agentConfig.loopMode.workerAttemptsTitle", "Worker attempts")}
        description={t(
          "agentConfig.loopMode.workerAttemptsDescription",
          "Limit Worker retries after a Story fails verification.",
        )}
      >
        <Form.Item
          name={["loop", "mission", "max_retries_per_story"]}
          label={t(
            "agentConfig.loopMode.maxRetriesPerStory",
            "Maximum retries per Story",
          )}
          tooltip={t(
            "agentConfig.loopMode.maxRetriesPerStoryTooltip",
            "Worker retries after a failed or partial Verifier result.",
          )}
        >
          <InputNumber min={0} max={10} style={{ width: 220 }} />
        </Form.Item>
      </LockedGateCard>
      <LockedGateCard
        icon={<ListChecks size={15} />}
        title={t(
          "agentConfig.loopMode.missionVerificationTitle",
          "Mission verification policy",
        )}
        description={t(
          "agentConfig.loopMode.missionVerificationDescription",
          "Define the default verification guidance and test command.",
        )}
      >
        <Form.Item
          name={["loop", "mission", "default_verification_instructions"]}
          label={t(
            "agentConfig.loopMode.defaultVerificationInstructions",
            "Verification guidance (optional)",
          )}
          extra={t(
            "agentConfig.loopMode.defaultVerificationInstructionsHelp",
            "Natural-language guidance applied to every Mission verifier.",
          )}
        >
          <Input.TextArea
            autoSize={{ minRows: 3, maxRows: 6 }}
            maxLength={4000}
            placeholder={t(
              "agentConfig.loopMode.defaultVerificationInstructionsPlaceholder",
              "For example: Check Windows path handling and inspect the rendered UI.",
            )}
          />
        </Form.Item>
        <Form.Item
          name={["loop", "mission", "default_verify_command"]}
          label={t(
            "agentConfig.loopMode.defaultVerifyCommand",
            "Default test command (optional)",
          )}
          extra={t(
            "agentConfig.loopMode.defaultVerifyCommandHelp",
            "The verifier attempts this through normal tools and permissions. /mission --verify overrides it.",
          )}
        >
          <Input
            allowClear
            prefix={<Terminal size={14} />}
            placeholder={t(
              "agentConfig.loopMode.defaultVerifyCommandPlaceholder",
              "For example: pytest -q",
            )}
          />
        </Form.Item>
      </LockedGateCard>
    </div>
  );
}

type GateDefinition = {
  type: CustomGateType;
  title: string;
  titleKey: string;
  description: string;
  descriptionKey: string;
  icon: React.ReactNode;
  defaults: Record<string, unknown>;
  exclusiveGroup?: string;
};

function PerToolLimits({
  value = {},
  onChange,
}: {
  value?: Record<string, number>;
  onChange?: (value: Record<string, number>) => void;
}) {
  const { t } = useTranslation();
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
            aria-label={t("agentConfig.loopMode.toolName", "Tool name")}
            onBlur={(event) => updateName(name, event.target.value)}
            onPressEnter={(event) =>
              updateName(name, event.currentTarget.value)
            }
          />
          <InputNumber
            min={1}
            max={10000}
            value={limit}
            aria-label={t(
              "agentConfig.loopMode.callLimitAria",
              "{{name}} call limit",
              { name },
            )}
            onChange={(next) => updateLimit(name, next)}
          />
          <Button
            type="text"
            icon={<Trash2 size={14} />}
            aria-label={t(
              "agentConfig.loopMode.removeToolLimitAria",
              "Remove {{name}} limit",
              { name },
            )}
            onClick={() => {
              const next = { ...value };
              delete next[name];
              onChange?.(next);
            }}
          />
        </div>
      ))}
      <Button icon={<Plus size={14} />} onClick={addLimit}>
        {t("agentConfig.loopMode.addToolLimit", "Add per-tool limit")}
      </Button>
    </div>
  );
}

const GATE_DEFINITIONS: GateDefinition[] = [
  {
    type: "iteration",
    title: "Iteration limit",
    titleKey: "agentConfig.loopMode.iterationGateTitle",
    description: "Stop after a fixed number of loop iterations.",
    descriptionKey: "agentConfig.loopMode.iterationGateDescription",
    icon: <Repeat size={15} />,
    defaults: { max_iterations: 40 },
  },
  {
    type: "doom_loop",
    title: "Repetition protection",
    titleKey: "agentConfig.loopMode.doomGateTitle",
    description: "Detect repeated tool calls and change strategy.",
    descriptionKey: "agentConfig.loopMode.doomGateDescription",
    icon: <Shield size={15} />,
    defaults: {
      window_size: 3,
      similarity_threshold: 1,
      stages: [
        {
          after: 3,
          action: "modify_prompt",
          prompt: "Change strategy instead of repeating the same action.",
        },
        {
          after: 5,
          action: "stop",
          prompt: "Stopped after repeated actions did not make progress.",
        },
      ],
    },
  },
  {
    type: "token_budget",
    title: "Token budget",
    titleKey: "agentConfig.loopMode.tokenGateTitle",
    description: "Limit prompt and completion token usage.",
    descriptionKey: "agentConfig.loopMode.tokenGateDescription",
    icon: <Gauge size={15} />,
    defaults: { max_total_tokens: 120000 },
  },
  {
    type: "timeout",
    title: "Loop time limit",
    titleKey: "agentConfig.loopMode.timeoutGateTitle",
    description: "Stop at the next loop boundary after elapsed time.",
    descriptionKey: "agentConfig.loopMode.timeoutGateDescription",
    icon: <Clock3 size={15} />,
    defaults: { max_seconds: 1800 },
  },
  {
    type: "tool_call_budget",
    title: "Tool-call budget",
    titleKey: "agentConfig.loopMode.toolBudgetGateTitle",
    description: "Limit all calls and selected tools.",
    descriptionKey: "agentConfig.loopMode.toolBudgetGateDescription",
    icon: <Wrench size={15} />,
    defaults: { max_calls: 30, per_tool: {} },
  },
  {
    type: "qualitative_rubric",
    title: "Qualitative completion check",
    titleKey: "agentConfig.loopMode.qualitativeRubricTitle",
    description: "Check text responses without tool calls before ending.",
    descriptionKey: "agentConfig.loopMode.qualitativeRubricDescription",
    icon: <CheckCircle size={15} />,
    defaults: {
      rubric: "Every explicit user requirement must be addressed.",
      max_evaluations: 1,
    },
    exclusiveGroup: "completion_rubric",
  },
  {
    type: "completion_rubric",
    title: "Completion signal check",
    titleKey: "agentConfig.loopMode.completionRubricTitle",
    description:
      "Check text responses without tool calls for a completion signal.",
    descriptionKey: "agentConfig.loopMode.completionRubricDescription",
    icon: <ListChecks size={15} />,
    defaults: {
      prompt:
        "Treat the task as complete only when every explicit user requirement has been addressed. If any requirement remains, the task is incomplete and work must continue until it is addressed.",
      completion_signal: "COMPLETED",
      max_evaluations: 3,
    },
    exclusiveGroup: "completion_rubric",
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
  const { t } = useTranslation();
  const form = Form.useFormInstance();
  const base = [
    "loop",
    "custom_modes",
    modeIndex,
    "gates",
    gateIndex,
    "params",
  ];
  const stages =
    (Form.useWatch([...base, "stages"], {
      form,
      preserve: true,
    }) as Array<{ after?: number }> | undefined) || [];
  if (type === "iteration") {
    return (
      <Form.Item
        name={[...base, "max_iterations"]}
        label={t("agentConfig.loopMode.maxIterations", "Maximum iterations")}
      >
        <InputNumber min={1} max={500} style={{ width: "100%" }} />
      </Form.Item>
    );
  }
  if (type === "doom_loop") {
    return (
      <>
        <div className={loopStyles.fieldGrid}>
          <Form.Item
            name={[...base, "window_size"]}
            label={t("agentConfig.loopMode.historyWindow", "History window")}
          >
            <InputNumber min={2} max={20} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item
            name={[...base, "similarity_threshold"]}
            label={t(
              "agentConfig.loopMode.similarityThreshold",
              "Similarity threshold",
            )}
          >
            <InputNumber
              min={0}
              max={1}
              step={0.05}
              style={{ width: "100%" }}
            />
          </Form.Item>
        </div>
        <div className={loopStyles.subsectionTitle}>
          {t("agentConfig.doomLoopStages", "Intervention Rules")}
        </div>
        <Form.List name={[...base, "stages"]}>
          {(fields, { add, remove }) => (
            <div className={loopStyles.ruleList}>
              {fields.map(({ key, name, ...rest }) => (
                <div key={key} className={loopStyles.ruleRow}>
                  <Form.Item
                    {...rest}
                    name={[name, "after"]}
                    label={
                      name === 0
                        ? t("agentConfig.doomLoopAfter", "After")
                        : undefined
                    }
                    rules={[{ required: true }]}
                  >
                    <InputNumber min={1} style={{ width: "100%" }} />
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
                  >
                    <Select
                      options={[
                        {
                          value: "modify_prompt",
                          label: t(
                            "agentConfig.doomLoopWarnAction",
                            "Send Reminder",
                          ),
                        },
                        {
                          value: "stop",
                          label: t(
                            "agentConfig.doomLoopStopAction",
                            "Stop Loop",
                          ),
                        },
                      ]}
                    />
                  </Form.Item>
                  <Form.Item
                    {...rest}
                    name={[name, "prompt"]}
                    label={
                      name === 0
                        ? t("agentConfig.doomLoopPrompt", "Message")
                        : undefined
                    }
                  >
                    <Input.TextArea autoSize={{ minRows: 1, maxRows: 3 }} />
                  </Form.Item>
                  <Button
                    type="text"
                    danger
                    icon={<Trash2 size={14} />}
                    aria-label={t(
                      "agentConfig.loopMode.removeRule",
                      "Remove rule",
                    )}
                    onClick={() => remove(name)}
                  />
                </div>
              ))}
              <Button
                type="dashed"
                icon={<Plus size={14} />}
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
              >
                {t("agentConfig.doomLoopAddStage", "Add Rule")}
              </Button>
            </div>
          )}
        </Form.List>
      </>
    );
  }
  if (type === "token_budget") {
    return (
      <>
        <div className={loopStyles.fieldGrid}>
          <Form.Item
            name={[...base, "max_total_tokens"]}
            label={t(
              "agentConfig.loopMode.totalTokens",
              "Maximum total tokens",
            )}
            tooltip={t(
              "agentConfig.loopMode.totalTokensHelp",
              "Maximum combined input and output tokens used by this turn.",
            )}
          >
            <InputNumber min={1} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item
            name={[...base, "max_prompt_tokens"]}
            label={t(
              "agentConfig.loopMode.promptTokens",
              "Maximum input tokens",
            )}
            tooltip={t(
              "agentConfig.loopMode.promptTokensHelp",
              "Includes system instructions, conversation context, tool schemas, and tool results.",
            )}
          >
            <InputNumber min={1} style={{ width: "100%" }} />
          </Form.Item>
        </div>
        <Form.Item
          name={[...base, "max_completion_tokens"]}
          label={t(
            "agentConfig.loopMode.completionTokens",
            "Maximum output tokens",
          )}
          tooltip={t(
            "agentConfig.loopMode.completionTokensHelp",
            "Maximum tokens generated by the model during this turn.",
          )}
        >
          <InputNumber min={1} style={{ width: "100%" }} />
        </Form.Item>
      </>
    );
  }
  if (type === "timeout") {
    return (
      <Form.Item
        name={[...base, "max_seconds"]}
        label={t("agentConfig.loopMode.maxSeconds", "Maximum seconds")}
        tooltip={t(
          "agentConfig.loopMode.maxSecondsHelp",
          "Elapsed time is checked after the current model response or tool call completes. Running work is not interrupted.",
        )}
      >
        <InputNumber min={1} max={86400} style={{ width: "100%" }} />
      </Form.Item>
    );
  }
  if (type === "tool_call_budget") {
    return (
      <>
        <Form.Item
          name={[...base, "max_calls"]}
          label={t("agentConfig.loopMode.allToolCalls", "All tool calls")}
        >
          <InputNumber min={1} max={10000} style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item
          name={[...base, "per_tool"]}
          label={t("agentConfig.loopMode.perToolLimits", "Per-tool limits")}
        >
          <PerToolLimits />
        </Form.Item>
      </>
    );
  }
  if (type === "qualitative_rubric") {
    return (
      <>
        <Form.Item
          name={[...base, "max_evaluations"]}
          label={t(
            "agentConfig.loopMode.maxEvaluations",
            "Maximum evaluation rounds",
          )}
        >
          <InputNumber min={1} max={10} style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item
          name={[...base, "rubric"]}
          label={t(
            "agentConfig.loopMode.qualitativeRubric",
            "Natural-language completion criteria",
          )}
          extra={t(
            "agentConfig.loopMode.qualitativeRubricHelp",
            "Triggered only for text responses without tool calls. The agent continues when work remains.",
          )}
        >
          <Input.TextArea autoSize={{ minRows: 2, maxRows: 5 }} />
        </Form.Item>
      </>
    );
  }
  return (
    <>
      <Form.Item
        name={[...base, "prompt"]}
        label={t(
          "agentConfig.loopMode.completionPrompt",
          "Completion check prompt",
        )}
        extra={t(
          "agentConfig.loopMode.completionPromptHelp",
          "Describe when the result is complete. QwenPaw automatically injects the completion-signal output instruction.",
        )}
      >
        <Input.TextArea autoSize={{ minRows: 3, maxRows: 7 }} />
      </Form.Item>
      <div className={loopStyles.fieldGrid}>
        <Form.Item
          name={[...base, "completion_signal"]}
          label={t(
            "agentConfig.loopMode.completionSignal",
            "Completion signal",
          )}
          tooltip={t(
            "agentConfig.loopMode.completionSignalHelp",
            "QwenPaw injects this signal into the check prompt and instructs the agent to output only it. Matching is exact after trimming whitespace and ignoring case.",
          )}
        >
          <Input maxLength={64} />
        </Form.Item>
        <Form.Item
          name={[...base, "max_evaluations"]}
          label={t(
            "agentConfig.loopMode.maxEvaluations",
            "Maximum evaluation rounds",
          )}
        >
          <InputNumber min={1} max={10} style={{ width: "100%" }} />
        </Form.Item>
      </div>
      <p className={loopStyles.editorHint}>
        {t(
          "agentConfig.loopMode.completionRubricHelp",
          "Triggered after text responses without tool calls. The agent outputs the completion signal when done; otherwise it keeps working until the maximum evaluation rounds is reached.",
        )}
      </p>
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
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(gate.type === "completion_rubric");
  const definition = gateDefinition(gate.type);
  const title = t(definition.titleKey, definition.title);
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
          aria-label={t("agentConfig.loopMode.moveGateAria", "Move {{title}}", {
            title,
          })}
        >
          <GripVertical size={15} />
        </button>
        <span className={loopStyles.gateIcon}>{definition.icon}</span>
        <button
          type="button"
          className={loopStyles.gateCopy}
          onClick={() => setExpanded((value) => !value)}
        >
          <strong>{title}</strong>
          <small>{t(definition.descriptionKey, definition.description)}</small>
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
            aria-label={t("agentConfig.loopMode.removeGate", "Remove gate")}
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
  const { t } = useTranslation();
  const form = Form.useFormInstance();
  const gates =
    (Form.useWatch(["loop", "custom_modes", modeIndex, "gates"], {
      form,
      preserve: true,
    }) as GateInstanceConfig[]) || [];
  const sensors = useSensors(useSensor(PointerSensor));
  const path = ["loop", "custom_modes", modeIndex, "gates"];
  const updateGates = (next: GateInstanceConfig[]) => {
    form.setFieldValue(path, next);
    form.setFieldValue(
      ["loop", "custom_modes", modeIndex, "enabled"],
      next.some((gate) => gate.enabled),
    );
  };
  const usedTypes = new Set(gates.map((gate) => gate.type));
  const claimedGroups = new Set(
    gates
      .map((gate) => gateDefinition(gate.type).exclusiveGroup)
      .filter((group): group is string => Boolean(group)),
  );
  const available = GATE_DEFINITIONS.filter(
    (definition) =>
      !usedTypes.has(definition.type) &&
      !(
        definition.exclusiveGroup &&
        claimedGroups.has(definition.exclusiveGroup)
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
            <Sparkles size={11} />
            {t("agentConfig.loopMode.custom", "Custom")}
          </Tag>
          <p>
            {t(
              "agentConfig.loopMode.customDescription",
              "Build a saved pipeline from QwenPaw-owned gates.",
            )}
          </p>
        </div>
        <div>
          <Button type="text" icon={<Copy size={14} />} onClick={onDuplicate}>
            {t("agentConfig.loopMode.duplicate", "Duplicate")}
          </Button>
          <Button
            danger
            type="text"
            icon={<Trash2 size={14} />}
            onClick={onDelete}
          >
            {t("agentConfig.loopMode.delete", "Delete")}
          </Button>
        </div>
      </div>
      <div className={loopStyles.fieldGrid}>
        <Form.Item
          name={["loop", "custom_modes", modeIndex, "name"]}
          label={t("agentConfig.loopMode.displayName", "Display name")}
          rules={[
            { required: true, whitespace: true },
            {
              validator: (_, value: string) => {
                const modes = form.getFieldValue([
                  "loop",
                  "custom_modes",
                ]) as CustomLoopModeConfig[];
                if (hasDuplicateLoopModeName(modes || [], value, modeIndex)) {
                  return Promise.reject(
                    new Error(
                      t(
                        "agentConfig.loopMode.duplicateModeName",
                        "A loop mode with this name already exists.",
                      ),
                    ),
                  );
                }
                return Promise.resolve();
              },
            },
          ]}
        >
          <Input maxLength={80} />
        </Form.Item>
        <Form.Item
          name={["loop", "custom_modes", modeIndex, "slash_command"]}
          label={t("agentConfig.loopMode.slashCommand", "Slash command")}
          rules={[{ required: true }, { pattern: /^[a-z0-9][a-z0-9_-]*$/ }]}
        >
          <Input prefix="/" maxLength={64} />
        </Form.Item>
      </div>
      <Form.Item
        name={["loop", "custom_modes", modeIndex, "description"]}
        label={t("agentConfig.loopMode.description", "Description")}
      >
        <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} maxLength={500} />
      </Form.Item>
      <div className={loopStyles.pipelineToolbar}>
        <div>
          <strong>
            {t("agentConfig.loopMode.gatePipeline", "Gate pipeline")}
          </strong>
          <small>
            {t(
              "agentConfig.loopMode.runsTopToBottom",
              "Runs from top to bottom",
            )}
          </small>
        </div>
        <Dropdown
          trigger={["click"]}
          disabled={!available.length}
          menu={{
            items: available.map((definition) => ({
              key: definition.type,
              icon: definition.icon,
              label: t(definition.titleKey, definition.title),
            })),
            onClick: ({ key }: { key: string }) =>
              addGate(key as CustomGateType),
          }}
        >
          <Button
            className={loopStyles.addGateButton}
            icon={<Plus size={16} />}
            aria-label={t("agentConfig.loopMode.addGate", "Add gate")}
            title={t("agentConfig.loopMode.addGate", "Add gate")}
          />
        </Dropdown>
      </div>
      {!gates.length ? (
        <div className={loopStyles.emptyPipeline}>
          {t(
            "agentConfig.loopMode.emptyPipeline",
            "Add at least one gate before enabling this mode.",
          )}
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
  safe: ["iteration", "token_budget", "doom_loop", "qualitative_rubric"],
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
  description = "A custom gate pipeline.",
): CustomLoopModeConfig {
  const baseCommand = command || "custom-mode";
  const slashCommand = uniqueValue(
    baseCommand,
    new Set(existing.map((mode) => mode.slash_command)),
    64,
  );
  const id = uniqueValue(
    baseCommand,
    new Set(existing.map((mode) => mode.id)),
    64,
  );
  return {
    id,
    name,
    slash_command: slashCommand,
    description,
    enabled: template !== "blank",
    gates: TEMPLATES[template].map((type, index) =>
      makeGate(type, `${nonce}-${index}`),
    ),
  };
}

function uniqueValue(
  base: string,
  existing: Set<string>,
  maxLength: number,
  normalize: (value: string) => string = (value) => value,
): string {
  let candidate = base.slice(0, maxLength);
  let suffix = 2;
  while (existing.has(normalize(candidate))) {
    const suffixText = `-${suffix}`;
    candidate = `${base.slice(0, maxLength - suffixText.length)}${suffixText}`;
    suffix += 1;
  }
  return candidate;
}

function normalizeLoopModeName(name: string | undefined): string {
  return (name || "").trim().toUpperCase().toLowerCase();
}

export function hasDuplicateLoopModeName(
  modes: CustomLoopModeConfig[],
  name: string | undefined,
  ignoredIndex = -1,
): boolean {
  const normalized = normalizeLoopModeName(name);
  if (!normalized) return false;
  return modes.some(
    (mode, index) =>
      index !== ignoredIndex && normalizeLoopModeName(mode.name) === normalized,
  );
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
    (Form.useWatch(["loop", "custom_modes"], {
      form,
      preserve: true,
    }) as CustomLoopModeConfig[]) || [];
  const [activeKey, setActiveKey] = useState("default");
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState(() =>
    t("agentConfig.loopMode.newModeName", "New Loop Mode"),
  );
  const [newCommand, setNewCommand] = useState("new-mode");
  const [template, setTemplate] = useState("safe");
  const duplicateNewName = hasDuplicateLoopModeName(customModes, newName);

  const setModes = (modes: CustomLoopModeConfig[]) =>
    form.setFieldValue(["loop", "custom_modes"], modes);
  const createMode = () => {
    const mode = buildCustomLoopMode(
      customModes,
      newName.trim(),
      newCommand.trim(),
      template,
      Date.now(),
      t(
        "agentConfig.loopMode.defaultCustomDescription",
        "A custom gate pipeline.",
      ),
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
      id: uniqueValue(baseId, new Set(customModes.map((mode) => mode.id)), 64),
      name: uniqueValue(
        t("agentConfig.loopMode.copyName", "{{name}} Copy", {
          name: source.name,
        }),
        new Set(customModes.map((mode) => normalizeLoopModeName(mode.name))),
        80,
        normalizeLoopModeName,
      ),
      slash_command: uniqueValue(
        baseCommand,
        new Set(customModes.map((mode) => mode.slash_command)),
        64,
      ),
      enabled: source.gates.some((gate) => gate.enabled),
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
          {t("agentConfig.loopMode.defaultTab", "Default")}
        </span>
      ),
      children: <DefaultModeTab />,
    },
    {
      key: "goal",
      label: (
        <span className={loopStyles.builtInTab}>
          <Lock size={12} />
          {t("agentConfig.loopMode.goalTab", "Goal")}
        </span>
      ),
      children: <GoalModeTab />,
    },
    {
      key: "mission",
      label: (
        <span className={loopStyles.builtInTab}>
          <Lock size={12} />
          {t("agentConfig.loopMode.missionTab", "Mission")}
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
    {
      key: "add-mode",
      disabled: customModes.length >= 20,
      label: (
        <span
          className={loopStyles.addModeTab}
          aria-label={t(
            "agentConfig.loopMode.createModeAria",
            "Create custom loop mode",
          )}
        >
          <Plus size={15} />
        </span>
      ),
      children: null,
    },
  ];

  const handleTabChange = (key: string) => {
    if (key === "add-mode") {
      setCreating(true);
      return;
    }
    setActiveKey(key);
  };

  return (
    <Card
      className={`${styles.formCard} ${loopStyles.loopCard}`}
      title={t("agentConfig.agentLoopTitle", "Agent Loop Settings")}
    >
      <div className={loopStyles.templateIntro}>
        <strong>
          {t("agentConfig.loopMode.templateSectionTitle", "Loop templates")}
        </strong>
        <span>
          {t(
            "agentConfig.loopMode.templateSectionDescription",
            "Choose a built-in template or add your own.",
          )}
        </span>
      </div>
      <Tabs
        activeKey={activeKey}
        onChange={handleTabChange}
        items={tabItems}
        size="small"
      />
      <Modal
        width={520}
        title={t(
          "agentConfig.loopMode.createModeTitle",
          "Create custom loop mode",
        )}
        open={creating}
        onCancel={() => setCreating(false)}
        onOk={createMode}
        okButtonProps={{
          disabled: !newName.trim() || !newCommand.trim() || duplicateNewName,
        }}
      >
        <div className={loopStyles.createForm}>
          <label>{t("agentConfig.loopMode.displayName", "Display name")}</label>
          <Input
            maxLength={80}
            value={newName}
            status={duplicateNewName ? "error" : undefined}
            onChange={(event) => setNewName(event.target.value)}
          />
          {duplicateNewName && (
            <small className={loopStyles.fieldError}>
              {t(
                "agentConfig.loopMode.duplicateModeName",
                "A loop mode with this name already exists.",
              )}
            </small>
          )}
          <label>
            {t("agentConfig.loopMode.slashCommand", "Slash command")}
          </label>
          <Input
            maxLength={64}
            prefix="/"
            value={newCommand}
            onChange={(event) =>
              setNewCommand(
                event.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ""),
              )
            }
          />
          <label>
            {t("agentConfig.loopMode.startingTemplate", "Starting template")}
          </label>
          <Select
            value={template}
            onChange={setTemplate}
            options={[
              {
                value: "safe",
                label: t("agentConfig.loopMode.safeTemplate", "Safe run"),
              },
              {
                value: "research",
                label: t(
                  "agentConfig.loopMode.researchTemplate",
                  "Budgeted research",
                ),
              },
              {
                value: "quality",
                label: t(
                  "agentConfig.loopMode.qualityTemplate",
                  "Quality first",
                ),
              },
              {
                value: "blank",
                label: t(
                  "agentConfig.loopMode.blankTemplate",
                  "Blank pipeline",
                ),
              },
            ]}
          />
          <div className={loopStyles.templatePreview} aria-live="polite">
            <span>
              {t("agentConfig.loopMode.startingPipeline", "Starting pipeline")}
            </span>
            <div>
              {TEMPLATES[template].length ? (
                TEMPLATES[template].map((type) => {
                  const definition = gateDefinition(type);
                  return (
                    <small key={type}>
                      {t(definition.titleKey, definition.title)}
                    </small>
                  );
                })
              ) : (
                <small>
                  {t(
                    "agentConfig.loopMode.blankPipelineHint",
                    "Start empty and add gates later",
                  )}
                </small>
              )}
            </div>
          </div>
        </div>
      </Modal>
    </Card>
  );
}
