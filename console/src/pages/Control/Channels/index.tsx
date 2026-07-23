import { useCallback, useEffect, useMemo, useState } from "react";
import { Form } from "@agentscope-ai/design";
import { Badge, Button, Input, Modal, Select, Space, Tooltip } from "antd";
import {
  AuditOutlined,
  CloudDownloadOutlined,
  SafetyOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import type { ChannelDependencyInstallSource } from "../../../api/modules/channel";
import {
  ChannelCard,
  ChannelDrawer,
  AccessControlDrawer,
  PendingApprovalsDrawer,
  useChannels,
  getChannelLabel,
  ChannelAvailableItem,
  type ChannelKey,
} from "./components";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { createDependencyInstallRequest } from "./dependencyInstall";
import styles from "./index.module.less";

type FilterType = "all" | "builtin" | "custom";

function DependencyInstallOptions({
  onChange,
}: {
  onChange: (values: {
    source: ChannelDependencyInstallSource;
    customIndexUrl: string;
  }) => void;
}) {
  const { t } = useTranslation();
  const [source, setSource] =
    useState<ChannelDependencyInstallSource>("aliyun");
  const [customIndexUrl, setCustomIndexUrl] = useState("");
  const sourceDescriptions: Record<ChannelDependencyInstallSource, string> = {
    pypi: t("channels.installSourcePypiDescription"),
    aliyun: t("channels.installSourceAliyunDescription"),
    custom: t("channels.installSourceCustomDescription"),
  };

  const update = (
    nextSource: ChannelDependencyInstallSource = source,
    nextUrl: string = customIndexUrl,
  ) => onChange({ source: nextSource, customIndexUrl: nextUrl });

  return (
    <div className={styles.dependencySourceFields}>
      <label
        className={styles.dependencySourceLabel}
        htmlFor="channel-dependency-source"
      >
        {t("channels.installSourceLabel")}
      </label>
      <Select
        id="channel-dependency-source"
        className={styles.dependencySourceSelect}
        value={source}
        options={[
          { value: "aliyun", label: t("channels.installSourceAliyun") },
          { value: "pypi", label: t("channels.installSourcePypi") },
          { value: "custom", label: t("channels.installSourceCustom") },
        ]}
        optionRender={(option) => (
          <Tooltip
            title={
              sourceDescriptions[option.value as ChannelDependencyInstallSource]
            }
            {...{ alignPoint: true }}
            mouseEnterDelay={0.3}
          >
            <div className={styles.dependencySourceOption}>{option.label}</div>
          </Tooltip>
        )}
        onChange={(value: ChannelDependencyInstallSource) => {
          setSource(value);
          update(value);
        }}
      />
      {source === "custom" && (
        <Input
          placeholder={t("channels.installCustomSourcePlaceholder")}
          value={customIndexUrl}
          onChange={(event) => {
            setCustomIndexUrl(event.target.value);
            update(source, event.target.value);
          }}
        />
      )}
    </div>
  );
}

function ChannelsPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const {
    channels,
    orderedKeys,
    channelSchemas,
    dependencyStatuses,
    dependencyStatusesLoaded,
    dependencyStatusError,
    setChannelDependencyStatus,
    isBuiltin,
    loading,
    fetchChannels,
  } = useChannels();
  const [filter, setFilter] = useState<FilterType>("all");
  const [saving, setSaving] = useState(false);
  const [activeKey, setActiveKey] = useState<ChannelKey | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [aclDrawerOpen, setAclDrawerOpen] = useState(false);
  const [pendingDrawerOpen, setPendingDrawerOpen] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [form] = Form.useForm<any>();

  const fetchPendingCount = useCallback(async () => {
    try {
      const data = await api.getAclAllPending();
      setPendingCount(data.length);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    fetchPendingCount();
  }, [fetchPendingCount]);

  // Sort cards: enabled first, then disabled (preserve orderedKeys order within each group)
  const { enabledCards, disabledCards } = useMemo(() => {
    const enabledCards: { key: ChannelKey; config: Record<string, unknown> }[] =
      [];
    const disabledCards: {
      key: ChannelKey;
      config: Record<string, unknown>;
    }[] = [];

    orderedKeys.forEach((key) => {
      const config = channels[key] || { enabled: false, bot_prefix: "" };
      const builtin = isBuiltin(key);
      if (filter === "builtin" && !builtin) return;
      if (filter === "custom" && builtin) return;
      const dependencyReady =
        !builtin ||
        (!dependencyStatusError && dependencyStatuses[key]?.status === "ready");
      if (config.enabled && dependencyReady) {
        enabledCards.push({ key, config });
      } else {
        disabledCards.push({ key, config });
      }
    });

    return { enabledCards, disabledCards };
  }, [
    channels,
    dependencyStatuses,
    dependencyStatusError,
    orderedKeys,
    filter,
    isBuiltin,
  ]);

  const handleCardClick = useCallback(
    (key: ChannelKey) => {
      const dependency = dependencyStatuses[key];
      if (isBuiltin(key) && !dependency) return;
      if (
        dependency?.status === "missing" ||
        dependency?.status === "failed" ||
        (dependency?.status === "load_error" &&
          dependency.requirements.length > 0)
      ) {
        const reinstall = dependency.status === "load_error";
        const displayedRequirements = reinstall
          ? dependency.requirements
          : dependency.missing_requirements;
        let source: ChannelDependencyInstallSource = "aliyun";
        let customIndexUrl = "";
        Modal.confirm({
          title: (
            <Space size={8}>
              <CloudDownloadOutlined />
              {t(
                reinstall
                  ? "channels.reinstallDependenciesTitle"
                  : "channels.installDependenciesTitle",
                {
                  channel: getChannelLabel(key, t),
                },
              )}
            </Space>
          ),
          icon: null,
          centered: true,
          width: 480,
          className: styles.dependencyInstallModal,
          content: (
            <div className={styles.dependencyInstallContent}>
              <p className={styles.dependencyInstallDescription}>
                {t(
                  reinstall
                    ? "channels.reinstallDependenciesDescription"
                    : "channels.installDependenciesDescription",
                )}
              </p>
              <ul className={styles.dependencyList}>
                {displayedRequirements.map((requirement) => (
                  <li key={requirement}>{requirement}</li>
                ))}
              </ul>
              <DependencyInstallOptions
                onChange={(values) => {
                  source = values.source;
                  customIndexUrl = values.customIndexUrl;
                }}
              />
            </div>
          ),
          okText: t("channels.installConfirm"),
          cancelText: t("common.cancel"),
          onOk: async () => {
            try {
              let request;
              try {
                request = createDependencyInstallRequest(
                  source,
                  customIndexUrl,
                );
              } catch {
                throw new Error(t("channels.installCustomSourceInvalid"));
              }
              const job = await api.installChannelDependencies(key, {
                ...request,
                reinstall,
              });
              if (job.status === "failed") {
                throw new Error(job.error || t("channels.installFailed"));
              }
              setChannelDependencyStatus({
                channel: key,
                status: "installing",
                requirements: dependency.requirements,
                missing_requirements: job.requirements,
                job_id: job.id,
              });
            } catch (error) {
              console.error("Failed to install channel dependencies", error);
              message.error(
                error instanceof Error
                  ? error.message
                  : t("channels.installFailed"),
              );
              throw error;
            }
          },
        });
        return;
      }
      if (dependency?.status === "installing") {
        Modal.confirm({
          title: t("channels.stopInstallTitle", {
            channel: getChannelLabel(key, t),
          }),
          content: t("channels.stopInstallDescription"),
          centered: true,
          okText: t("channels.stopInstallConfirm"),
          okButtonProps: { danger: true },
          cancelText: t("common.cancel"),
          onOk: async () => {
            try {
              await api.cancelChannelDependencyInstall(key);
            } catch (error) {
              console.error("Failed to stop channel dependency install", error);
              message.error(t("channels.stopInstallFailed"));
              throw error;
            }
          },
        });
        return;
      }
      if (
        dependency?.status === "platform_unsupported" ||
        dependency?.status === "load_error"
      ) {
        return;
      }
      setActiveKey(key);
      setDrawerOpen(true);
      const channelConfig = channels[key] || { enabled: false, bot_prefix: "" };
      // Migrate legacy allowlist policy to new access control fields
      const accessControlDm =
        channelConfig.access_control_dm ||
        channelConfig.dm_policy === "allowlist";
      const accessControlGroup =
        channelConfig.access_control_group ||
        channelConfig.group_policy === "allowlist";
      form.setFieldsValue({
        ...channelConfig,
        access_control_dm: accessControlDm,
        access_control_group: accessControlGroup,
        show_tool_calls: channelConfig.show_tool_calls ?? true,
        show_tool_results: channelConfig.show_tool_results ?? true,
        tool_call_max_length: channelConfig.tool_call_max_length ?? 200,
        tool_result_max_length: channelConfig.tool_result_max_length ?? 500,
        show_thinking: channelConfig.show_thinking ?? true,
      });
    },
    [
      channels,
      dependencyStatuses,
      form,
      message,
      isBuiltin,
      setChannelDependencyStatus,
      t,
    ],
  );

  const handleDrawerClose = () => {
    setDrawerOpen(false);
    setActiveKey(null);
  };

  const handleSubmit = async (values: Record<string, unknown>) => {
    if (!activeKey) return;

    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { isBuiltin: _isBuiltin, ...savedConfig } = channels[activeKey] || {};
    const updatedChannel: Record<string, unknown> = {
      ...savedConfig,
      ...values,
    };

    setSaving(true);
    try {
      await api.updateChannelConfig(
        activeKey,
        updatedChannel as unknown as Parameters<
          typeof api.updateChannelConfig
        >[1],
      );
      await fetchChannels();

      setDrawerOpen(false);
      message.success(t("channels.configSaved"));
    } catch (error) {
      console.error("❌ Failed to update channel config:", error);
      message.error(t("channels.configFailed"));
    } finally {
      setSaving(false);
    }
  };

  const activeLabel = activeKey ? getChannelLabel(activeKey, t) : "";

  const FILTER_TABS: { key: FilterType; label: string }[] = [
    { key: "all", label: t("channels.filterAll") },
    { key: "builtin", label: t("channels.builtin") },
    { key: "custom", label: t("channels.custom") },
  ];

  return (
    <div className={styles.channelsPage}>
      <PageHeader
        className={styles.pageHeader}
        items={[{ title: t("nav.control") }, { title: t("channels.title") }]}
        center={
          <div className={styles.filterTabs}>
            {FILTER_TABS.map(({ key, label }) => (
              <button
                key={key}
                className={`${styles.filterTab} ${
                  filter === key ? styles.filterTabActive : ""
                }`}
                onClick={() => setFilter(key)}
              >
                {label}
              </button>
            ))}
          </div>
        }
        extra={
          <Space size={8}>
            <Badge dot={pendingCount > 0} offset={[-4, 4]}>
              <Button
                icon={<AuditOutlined />}
                onClick={() => setPendingDrawerOpen(true)}
              >
                {t("channels.pendingApprovals")}
              </Button>
            </Badge>
            <Button
              icon={<SafetyOutlined />}
              onClick={() => setAclDrawerOpen(true)}
            >
              {t("channels.manageAccessControl")}
            </Button>
          </Space>
        }
      />
      <div className={styles.channelsContainer}>
        {loading ? (
          <div className={styles.loading}>
            <span className={styles.loadingText}>{t("channels.loading")}</span>
          </div>
        ) : (
          <>
            {/* Enabled Channels Section */}
            <div className={styles.panelSection}>
              <div className={styles.panelTitle}>
                <span className={styles.panelDotGreen} />
                {t("channels.enabledSection")}
                <span className={styles.panelCount}>
                  {t("channels.enabledCount", { count: enabledCards.length })}
                </span>
              </div>

              {enabledCards.length > 0 ? (
                <div className={styles.channelsGrid}>
                  {enabledCards.map(({ key, config }) => (
                    <ChannelCard
                      key={key}
                      channelKey={key}
                      config={config}
                      iconUrl={channelSchemas[key]?.icon}
                      onClick={() => handleCardClick(key)}
                    />
                  ))}
                </div>
              ) : (
                <div className={styles.emptyConfigured}>
                  <p>{t("channels.noEnabledChannels")}</p>
                  {disabledCards.length > 0 && (
                    <Button
                      type="primary"
                      onClick={() => {
                        document
                          .getElementById("available-channels")
                          ?.scrollIntoView({ behavior: "smooth" });
                      }}
                    >
                      {t("channels.goEnableChannels")}
                    </Button>
                  )}
                </div>
              )}
            </div>

            {/* Available Channels Section */}
            {disabledCards.length > 0 && (
              <div
                id="available-channels"
                className={styles.panelSectionDashed}
              >
                <div className={styles.panelTitle}>
                  <span className={styles.panelDotGray} />
                  {t("channels.availableSection")}
                </div>
                <div className={styles.availableGrid}>
                  {disabledCards.map(({ key }) => (
                    <ChannelAvailableItem
                      key={key}
                      channelKey={key}
                      iconUrl={channelSchemas[key]?.icon}
                      dependencyStatus={dependencyStatuses[key]}
                      dependencyCheckState={
                        !isBuiltin(key)
                          ? "ready"
                          : !dependencyStatusesLoaded
                          ? "checking"
                          : dependencyStatusError || !dependencyStatuses[key]
                          ? "failed"
                          : "ready"
                      }
                      onClick={() => handleCardClick(key)}
                    />
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
      <ChannelDrawer
        open={drawerOpen}
        activeKey={activeKey}
        activeLabel={activeLabel}
        form={form}
        saving={saving}
        initialValues={activeKey ? channels[activeKey] : undefined}
        isBuiltin={activeKey ? isBuiltin(activeKey) : true}
        channelSchema={activeKey ? channelSchemas[activeKey] : undefined}
        onClose={handleDrawerClose}
        onSubmit={handleSubmit}
      />
      <AccessControlDrawer
        open={aclDrawerOpen}
        onClose={() => setAclDrawerOpen(false)}
      />
      <PendingApprovalsDrawer
        open={pendingDrawerOpen}
        onClose={() => {
          setPendingDrawerOpen(false);
          fetchPendingCount();
        }}
      />
    </div>
  );
}

export default ChannelsPage;
