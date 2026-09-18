import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  App,
  Button,
  Form,
  Grid,
  Input,
  InputNumber,
  Modal,
  Pagination,
  Progress,
  Radio,
  Select,
  Skeleton,
  Switch,
  Tag,
  Tabs,
} from "antd";
import type { FormInstance } from "antd";
import {
  Box,
  BrainCircuit,
  Boxes,
  CircleStop,
  Gauge,
  HardDrive,
  KeyRound,
  ListFilter,
  Play,
  Plus,
  RefreshCw,
  Save,
  ScrollText,
  Search,
  Settings2,
  ShieldAlert,
  ShieldBan,
  Trash2,
  Users,
} from "lucide-react";
import { clearAuthToken } from "../../api/config";
import HubShell from "./components/HubShell";
import OverviewPanel from "./components/OverviewPanel";
import { useTheme } from "../../contexts/ThemeContext";
import {
  hubApi,
  type HubAuditEvent,
  type HubCredential,
  type HubDockerImageCatalog,
  type HubDockerImagePull,
  type HubHealth,
  type HubOverview,
  type HubRuntime,
  type HubSettings,
  type HubUser,
} from "../../api/modules/hub";
import styles from "./index.module.less";
import UserManagement from "./governance/UserManagement";
import OrganizationBudget from "./governance/OrganizationBudget";
import OrganizationModels from "./governance/OrganizationModels";
import {
  dockerReferenceParts,
  dockerReferenceKey,
  emptyPage,
  formatDate,
  formatImageSize,
  PAGE_SIZE,
  type PageData,
  type Section,
  type SettingsFormValues,
  STATE_COLORS,
} from "./pageUtils";

export default function HubPage() {
  const { message, modal } = App.useApp();
  const { t, i18n } = useTranslation();
  const { isDark, toggleTheme } = useTheme();
  const [refreshing, setRefreshing] = useState(false);
  const [me, setMe] = useState<HubUser | null>(null);
  const [health, setHealth] = useState<HubHealth | null>(null);
  const [overview, setOverview] = useState<HubOverview | null>(null);
  const [section, setSection] = useState<Section>("overview");
  const [sectionTarget, setSectionTarget] = useState<string>();
  const navigate = (next: Section, target?: string) => {
    setSectionTarget(target);
    if (next === "runtimes") {
      setRuntimeState(target);
      setRuntimeQuery("");
      setRuntimeOwner("");
      setRuntimeExecution(undefined);
    }
    if (next === "users") setUserQuery(target ?? "");
    if (next === "audit") {
      setAuditQuery(target ?? "");
      setAuditAction(undefined);
    }
    setSection(next);
  };
  const [runtimes, setRuntimes] = useState<PageData<HubRuntime>>(emptyPage);
  const [users, setUsers] = useState<PageData<HubUser>>(emptyPage);
  const [credentials, setCredentials] =
    useState<PageData<HubCredential>>(emptyPage);
  const [audit, setAudit] = useState<PageData<HubAuditEvent>>(emptyPage);
  const [settings, setSettings] = useState<HubSettings | null>(null);
  const [dockerImages, setDockerImages] =
    useState<HubDockerImageCatalog | null>(null);
  const [dockerPulls, setDockerPulls] = useState<HubDockerImagePull[]>([]);
  const [dockerImagesLoading, setDockerImagesLoading] = useState(false);
  const [dockerPulling, setDockerPulling] = useState(false);
  const [runtimeQuery, setRuntimeQuery] = useState("");
  const [runtimeState, setRuntimeState] = useState<string>();
  const [runtimeOwner, setRuntimeOwner] = useState("");
  const [runtimeExecution, setRuntimeExecution] = useState<string>();
  const [userQuery, setUserQuery] = useState("");
  const [userRole, setUserRole] = useState<string>();
  const [userDisabled, setUserDisabled] = useState<string>();
  const [credentialQuery, setCredentialQuery] = useState("");
  const [credentialScope, setCredentialScope] = useState<string>();
  const [auditQuery, setAuditQuery] = useState("");
  const [auditAction, setAuditAction] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [runtimeModalOpen, setRuntimeModalOpen] = useState(false);
  const [userModalOpen, setUserModalOpen] = useState(false);
  const [credentialModalOpen, setCredentialModalOpen] = useState(false);
  const [runtimeForm] = Form.useForm();
  const [userForm] = Form.useForm();
  const [credentialForm] = Form.useForm();
  const [settingsForm] = Form.useForm<SettingsFormValues>();
  const dockerDataRequest = useRef<Promise<void> | null>(null);

  const loadOverview = useCallback(async () => {
    setOverview(await hubApi.getOverview());
  }, []);

  const loadRuntimes = useCallback(
    async (page = 1) => {
      const result = await hubApi.listRuntimes({
        page,
        pageSize: PAGE_SIZE,
        query: runtimeQuery,
        state: runtimeState as HubRuntime["state"] | undefined,
        owner: runtimeOwner,
        provisioner: runtimeExecution,
      });
      setRuntimes({
        items: result.items,
        page: result.page,
        pageSize: result.page_size,
        total: result.total,
      });
    },
    [runtimeExecution, runtimeOwner, runtimeQuery, runtimeState],
  );

  const loadUsers = useCallback(
    async (page = 1) => {
      const result = await hubApi.listUsers({
        page,
        pageSize: PAGE_SIZE,
        query: userQuery,
        role: userRole as HubUser["role"] | undefined,
        disabled:
          userDisabled === undefined ? undefined : userDisabled === "disabled",
      });
      setUsers({
        items: result.items,
        page: result.page,
        pageSize: result.page_size,
        total: result.total,
      });
    },
    [userDisabled, userQuery, userRole],
  );

  const loadDockerData = useCallback(() => {
    if (dockerDataRequest.current) return dockerDataRequest.current;
    setDockerImagesLoading(true);
    const request = Promise.all([
      hubApi.getDockerImages(),
      hubApi.listDockerImagePulls(),
    ])
      .then(([imageResult, pullResult]) => {
        setDockerImages(imageResult);
        setDockerPulls(pullResult);
        const configuredImage = settingsForm.getFieldValue("dockerImage");
        const configuredSource = settingsForm.getFieldValue("dockerSource");
        if (
          configuredSource === "custom" &&
          imageResult.local_images.some(
            (image) =>
              dockerReferenceKey(image.reference) ===
              dockerReferenceKey(configuredImage || ""),
          )
        ) {
          settingsForm.setFieldValue("dockerSource", "local");
        }
      })
      .catch((error) => {
        message.error(
          error instanceof Error ? error.message : t("hub.errors.loadFailed"),
        );
      })
      .finally(() => {
        setDockerImagesLoading(false);
        dockerDataRequest.current = null;
      });
    dockerDataRequest.current = request;
    return request;
  }, [message, settingsForm, t]);

  const loadSettings = useCallback(async () => {
    const result = await hubApi.getSettings();
    setSettings(result);
    settingsForm.setFieldsValue({
      publicBaseUrl: result.config.control_plane.public_base_url || undefined,
      registrationMode:
        result.config.control_plane.registration.mode ?? "closed",
      runtimeProvisioner: result.config.runtime.provisioner,
      dockerSource: result.config.runtime.docker.source,
      dockerImage: result.config.runtime.docker.image,
      dockerPullPolicy: result.config.runtime.docker.pull_policy,
      dockerCpuLimit: result.config.runtime.docker.cpu_limit ?? undefined,
      dockerMemoryLimitMb:
        result.config.runtime.docker.memory_limit_mb ?? undefined,
      dockerPidsLimit: result.config.runtime.docker.pids_limit ?? undefined,
      dockerShmSizeMb: result.config.runtime.docker.shm_size_mb,
      maxRunningRuntimes:
        result.config.capacity.max_running_runtimes ?? undefined,
      ipBlacklist: result.config.control_plane.security.ip_blacklist,
      trustedProxyIps: result.config.control_plane.security.trusted_proxy_ips,
      loginRateEnabled:
        result.config.control_plane.security.login_rate_limit.enabled,
      loginMaxAttempts:
        result.config.control_plane.security.login_rate_limit.max_attempts,
      loginWindowSeconds:
        result.config.control_plane.security.login_rate_limit.window_seconds,
      loginBlockSeconds:
        result.config.control_plane.security.login_rate_limit.block_seconds,
      registrationRateEnabled:
        result.config.control_plane.security.registration_rate_limit.enabled,
      registrationMaxAttempts:
        result.config.control_plane.security.registration_rate_limit
          .max_attempts,
      registrationWindowSeconds:
        result.config.control_plane.security.registration_rate_limit
          .window_seconds,
      registrationBlockSeconds:
        result.config.control_plane.security.registration_rate_limit
          .block_seconds,
    });
    if (result.config.runtime.provisioner === "docker") {
      void loadDockerData();
    }
  }, [loadDockerData, settingsForm]);

  const loadCredentials = useCallback(
    async (page = 1) => {
      const result = await hubApi.listCredentials({
        page,
        pageSize: PAGE_SIZE,
        query: credentialQuery,
        scope: credentialScope,
      });
      setCredentials({
        items: result.items,
        page: result.page,
        pageSize: result.page_size,
        total: result.total,
      });
    },
    [credentialQuery, credentialScope],
  );

  const loadAudit = useCallback(
    async (page = 1) => {
      const result = await hubApi.listAuditEvents({
        page,
        pageSize: PAGE_SIZE,
        query: auditQuery,
        action: auditAction,
      });
      setAudit({
        items: result.items,
        page: result.page,
        pageSize: result.page_size,
        total: result.total,
      });
    },
    [auditAction, auditQuery],
  );

  useEffect(() => {
    let cancelled = false;
    Promise.all([hubApi.me(), hubApi.getHealth()])
      .then(async ([identity, runtimeHealth]) => {
        if (cancelled) return;
        setMe(identity);
        setHealth(runtimeHealth);
        if (identity.role !== "admin") {
          setSection("runtimes");
        }
      })
      .catch((error) => message.error(error.message))
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [message]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const request =
        section === "overview" && me?.role === "admin"
          ? loadOverview()
          : section === "runtimes"
          ? loadRuntimes(1)
          : section === "users" && me?.role === "admin"
          ? loadUsers(1)
          : section === "credentials"
          ? loadCredentials(1)
          : section === "audit" && me?.role === "admin"
          ? loadAudit(1)
          : section === "settings" && me?.role === "admin"
          ? loadSettings()
          : Promise.resolve();
      request.catch((error) => message.error(error.message));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [
    credentialQuery,
    credentialScope,
    auditAction,
    loadAudit,
    loadOverview,
    loadCredentials,
    loadRuntimes,
    loadSettings,
    loadUsers,
    me?.role,
    message,
    runtimeQuery,
    runtimeOwner,
    runtimeExecution,
    runtimeState,
    section,
    userQuery,
    userDisabled,
    userRole,
  ]);

  const runtimeOptions = useMemo(
    () =>
      runtimes.items.map((runtime) => ({
        label: runtime.runtime_id,
        value: `runtime:${runtime.runtime_id}`,
      })),
    [runtimes.items],
  );

  const refreshSection = async () => {
    setRefreshing(true);
    try {
      if (section === "overview") await loadOverview();
      if (section === "runtimes") await loadRuntimes(runtimes.page);
      if (section === "users") await loadUsers(users.page);
      if (section === "credentials") await loadCredentials(credentials.page);
      if (section === "audit") await loadAudit(audit.page);
      if (section === "settings") await loadSettings();
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setRefreshing(false);
    }
  };

  const saveSettings = async (values: SettingsFormValues) => {
    if (!settings) return;
    setSettingsSaving(true);
    try {
      const updated = await hubApi.updateSettings(settings.revision, {
        ...settings.config,
        control_plane: {
          ...settings.config.control_plane,
          public_base_url: values.publicBaseUrl?.trim() || null,
          registration: {
            mode: values.registrationMode,
            default_role: "user",
          },
          security: {
            ip_blacklist: values.ipBlacklist,
            trusted_proxy_ips: values.trustedProxyIps,
            login_rate_limit: {
              enabled: values.loginRateEnabled,
              max_attempts: values.loginMaxAttempts,
              window_seconds: values.loginWindowSeconds,
              block_seconds: values.loginBlockSeconds,
            },
            registration_rate_limit: {
              enabled: values.registrationRateEnabled,
              max_attempts: values.registrationMaxAttempts,
              window_seconds: values.registrationWindowSeconds,
              block_seconds: values.registrationBlockSeconds,
            },
          },
        },
        runtime: {
          provisioner: values.runtimeProvisioner,
          docker: {
            source:
              values.dockerSource === "local" ? "custom" : values.dockerSource,
            image: values.dockerImage.trim(),
            pull_policy: values.dockerPullPolicy,
            cpu_limit: values.dockerCpuLimit ?? null,
            memory_limit_mb: values.dockerMemoryLimitMb ?? null,
            pids_limit: values.dockerPidsLimit ?? null,
            shm_size_mb: values.dockerShmSizeMb,
          },
        },
        capacity: {
          max_running_runtimes: values.maxRunningRuntimes ?? null,
        },
      });
      setSettings(updated);
      message.success(t("hub.messages.settingsSaved"));
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("hub.errors.saveFailed"),
      );
      await loadSettings();
    } finally {
      setSettingsSaving(false);
    }
  };

  const pullDockerImage = async (reference: string) => {
    setDockerPulling(true);
    try {
      await hubApi.pullDockerImage(reference);
      const deadline = Date.now() + 15 * 60 * 1000;
      while (Date.now() < deadline) {
        const pulls = await hubApi.listDockerImagePulls();
        setDockerPulls(pulls);
        const current = pulls.find((pull) => pull.reference === reference);
        if (current?.status === "completed") {
          setDockerImages(await hubApi.getDockerImages());
          message.success(t("hub.messages.imagePulled"));
          return;
        }
        if (current?.status === "failed") {
          throw new Error(current.error || current.message);
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
      }
      throw new Error(t("hub.errors.pullTimedOut"));
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("hub.errors.actionFailed"),
      );
    } finally {
      setDockerPulling(false);
    }
  };

  const runRuntimeAction = async (
    runtimeId: string,
    action: "start" | "stop" | "disable" | "rebuild" | "delete",
  ) => {
    setBusyId(runtimeId);
    try {
      if (action === "start") await hubApi.startRuntime(runtimeId);
      if (action === "stop") await hubApi.stopRuntime(runtimeId);
      if (action === "disable") await hubApi.disableRuntime(runtimeId);
      if (action === "rebuild") await hubApi.rebuildRuntime(runtimeId);
      if (action === "delete") await hubApi.deleteRuntime(runtimeId);
      await loadRuntimes(runtimes.page);
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("hub.errors.actionFailed"),
      );
    } finally {
      setBusyId(null);
    }
  };

  const createRuntime = async (values: {
    runtimeId: string;
    autoStart: boolean;
  }) => {
    try {
      await hubApi.createRuntime(values.runtimeId, values.autoStart);
      setRuntimeModalOpen(false);
      runtimeForm.resetFields();
      await loadRuntimes(1);
      message.success(t("hub.messages.runtimeCreated"));
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("hub.errors.createFailed"),
      );
    }
  };

  const createUser = async (values: {
    username: string;
    password: string;
    role: HubUser["role"];
  }) => {
    try {
      await hubApi.createUser(values.username, values.password, values.role);
      setUserModalOpen(false);
      userForm.resetFields();
      await loadUsers(1);
      message.success(t("hub.messages.accountCreated"));
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("hub.errors.createFailed"),
      );
    }
  };

  const updateUser = async (
    user: HubUser,
    patch: Partial<Pick<HubUser, "role" | "disabled">>,
  ) => {
    setBusyId(user.user_id);
    try {
      await hubApi.updateUser(user.user_id, patch);
      await loadUsers(users.page);
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("hub.errors.updateFailed"),
      );
    } finally {
      setBusyId(null);
    }
  };

  const saveCredential = async (values: {
    scope: string;
    name: string;
    value: string;
  }) => {
    try {
      await hubApi.putCredential(values.scope, values.name, values.value);
      setCredentialModalOpen(false);
      credentialForm.resetFields();
      await loadCredentials(1);
      message.success(t("hub.messages.credentialStored"));
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("hub.errors.saveFailed"),
      );
    }
  };

  const navigation = [
    ...(me?.role === "admin"
      ? [
          {
            id: "overview" as const,
            label: t("hub.navigation.overview"),
            icon: Gauge,
          },
          {
            id: "users" as const,
            label: t("hub.navigation.users"),
            icon: Users,
          },
          {
            id: "models" as const,
            label: t("hub.governance.models.title"),
            icon: BrainCircuit,
          },
        ]
      : []),
    {
      id: "runtimes" as const,
      label: t("hub.navigation.runtimes"),
      icon: Boxes,
    },
    {
      id: "credentials" as const,
      label: t("hub.navigation.credentials"),
      icon: KeyRound,
    },
    ...(me?.role === "admin"
      ? [
          {
            id: "settings" as const,
            label: t("hub.navigation.settings"),
            icon: Settings2,
          },
          {
            id: "audit" as const,
            label: t("hub.navigation.audit"),
            icon: ScrollText,
          },
        ]
      : []),
  ];

  const runtimeAvailable = health?.runtime_available === true;
  const defaultProvisioner = health?.default_provisioner;
  const defaultProvisionerStatus = defaultProvisioner
    ? health?.provisioner_statuses[defaultProvisioner]
    : undefined;
  const runtimeUnavailableReason =
    defaultProvisionerStatus?.reason || t("hub.runtimes.preflightFailed");
  const logout = () => {
    clearAuthToken();
    window.location.assign("/login");
  };

  return (
    <>
      <HubShell
        navigation={navigation}
        section={section}
        onNavigate={navigate}
        username={me?.username}
        role={me?.role}
        runtimeCount={overview?.total_runtimes}
        healthy={runtimeAvailable}
        isDark={isDark}
        onToggleTheme={toggleTheme}
        onLogout={logout}
        onRefresh={refreshSection}
        refreshing={refreshing}
        loading={loading}
      >
        {loading ? (
          <Skeleton active />
        ) : (
          <>
            {health && !runtimeAvailable && (
              <div className={styles.runtimeUnavailable} role="alert">
                <ShieldAlert size={20} />
                <div>
                  <strong>{t("hub.runtimes.unavailableTitle")}</strong>
                  <span>
                    {me?.role === "admin"
                      ? t("hub.runtimes.unavailableDescription", {
                          provisioner: defaultProvisioner,
                          reason: runtimeUnavailableReason,
                        })
                      : t("hub.runtimes.unavailableUserDescription")}
                  </span>
                </div>
              </div>
            )}
            {section === "overview" && overview && (
              <OverviewPanel overview={overview} onNavigate={navigate} />
            )}
            {section === "runtimes" && (
              <section>
                <PageHeader
                  title={t("hub.runtimes.title")}
                  description={t("hub.runtimes.description")}
                  action={
                    <Button
                      type="primary"
                      icon={<Plus size={15} />}
                      disabled={!runtimeAvailable}
                      onClick={() => setRuntimeModalOpen(true)}
                    >
                      {t("hub.runtimes.newRuntime")}
                    </Button>
                  }
                />
                <DataPanel
                  search={runtimeQuery}
                  onSearch={setRuntimeQuery}
                  searchPlaceholder={t("hub.table.searchRuntimes")}
                  filter={
                    <>
                      {me?.role === "admin" && (
                        <Input
                          allowClear
                          value={runtimeOwner}
                          placeholder={t("hub.table.allOwners")}
                          className={styles.filterInput}
                          onChange={(event) =>
                            setRuntimeOwner(event.target.value)
                          }
                        />
                      )}
                      <Select
                        allowClear
                        value={runtimeState ?? ""}
                        placeholder={t("hub.table.allStates")}
                        className={styles.filterSelect}
                        onChange={(value) =>
                          setRuntimeState(value || undefined)
                        }
                        options={[
                          { value: "", label: t("hub.table.allStates") },
                          ...Object.keys(STATE_COLORS).map((state) => ({
                            value: state,
                            label: t(`hub.runtimeStates.${state}`),
                          })),
                        ]}
                      />
                      <Select
                        allowClear
                        value={runtimeExecution ?? ""}
                        placeholder={t("hub.table.allExecutions")}
                        className={styles.filterSelect}
                        onChange={(value) =>
                          setRuntimeExecution(value || undefined)
                        }
                        options={[
                          { value: "", label: t("hub.table.allExecutions") },
                          ...Object.keys(
                            health?.provisioner_statuses || {},
                          ).map((name) => ({
                            value: name,
                            label: t(`hub.runtimes.${name}Execution`),
                          })),
                        ]}
                      />
                    </>
                  }
                >
                  <div className={styles.tableWrap}>
                    <table>
                      <thead>
                        <tr>
                          <th>{t("hub.table.runtime")}</th>
                          <th>{t("hub.table.status")}</th>
                          <th>{t("hub.table.owner")}</th>
                          <th>{t("hub.table.endpoint")}</th>
                          <th>{t("hub.table.execution")}</th>
                          <th>{t("hub.table.updated")}</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {runtimes.items.map((runtime) => (
                          <tr key={runtime.runtime_id}>
                            <td>
                              <EntityCell
                                icon={<Box size={16} />}
                                title={runtime.runtime_id}
                                detail={runtime.tenant_id}
                              />
                            </td>
                            <td>
                              <div className={styles.runtimeStateStack}>
                                <Tag color={STATE_COLORS[runtime.state]}>
                                  {t(`hub.runtimeStates.${runtime.state}`)}
                                </Tag>
                                {runtime.desired_state === "stopped" && (
                                  <Tag
                                    color={
                                      runtime.start_policy === "admin_only"
                                        ? "error"
                                        : "warning"
                                    }
                                  >
                                    {t(
                                      `hub.runtimePolicies.${runtime.start_policy}`,
                                    )}
                                  </Tag>
                                )}
                              </div>
                            </td>
                            <td>
                              <EntityCell
                                icon={<Users size={16} />}
                                title={
                                  <>
                                    {runtime.owner_username ||
                                      runtime.owner_user_id}
                                    {runtime.owner_role === "admin" && (
                                      <>
                                        {" "}
                                        <Tag>{t("hub.roles.admin")}</Tag>
                                      </>
                                    )}
                                  </>
                                }
                                detail={runtime.owner_user_id}
                              />
                            </td>
                            <td className={styles.mono}>{runtime.endpoint}</td>
                            <td>
                              <strong>
                                {t(
                                  `hub.runtimes.${runtime.provisioner}Execution`,
                                )}
                              </strong>
                              <small>
                                {runtime.metadata?.docker?.image ||
                                  runtime.security_level}
                              </small>
                            </td>
                            <td>
                              {formatDate(runtime.updated_at, i18n.language)}
                            </td>
                            <td>
                              <div className={styles.rowActions}>
                                {me?.role === "admin" &&
                                  (runtime.state === "running" ? (
                                    <Button
                                      size="small"
                                      icon={<CircleStop size={14} />}
                                      loading={busyId === runtime.runtime_id}
                                      onClick={() =>
                                        runRuntimeAction(
                                          runtime.runtime_id,
                                          "stop",
                                        )
                                      }
                                    >
                                      {t("hub.actions.stop")}
                                    </Button>
                                  ) : (
                                    <Button
                                      size="small"
                                      icon={<Play size={14} />}
                                      disabled={!runtimeAvailable}
                                      loading={busyId === runtime.runtime_id}
                                      onClick={() =>
                                        runRuntimeAction(
                                          runtime.runtime_id,
                                          "start",
                                        )
                                      }
                                    >
                                      {t(
                                        runtime.start_policy === "admin_only"
                                          ? "hub.actions.enableAndStart"
                                          : "hub.actions.start",
                                      )}
                                    </Button>
                                  ))}
                                {me?.role === "admin" &&
                                  runtime.start_policy !== "admin_only" && (
                                    <Button
                                      size="small"
                                      danger
                                      icon={<ShieldBan size={14} />}
                                      loading={busyId === runtime.runtime_id}
                                      onClick={() =>
                                        modal.confirm({
                                          title: t(
                                            "hub.runtimes.disableTitle",
                                            { id: runtime.runtime_id },
                                          ),
                                          content: t(
                                            "hub.runtimes.disableDescription",
                                          ),
                                          okButtonProps: { danger: true },
                                          okText: t("hub.actions.disable"),
                                          onOk: () =>
                                            runRuntimeAction(
                                              runtime.runtime_id,
                                              "disable",
                                            ),
                                        })
                                      }
                                    >
                                      {t("hub.actions.disable")}
                                    </Button>
                                  )}
                                {me?.role === "admin" &&
                                  runtime.provisioner === "docker" && (
                                    <Button
                                      size="small"
                                      icon={<RefreshCw size={14} />}
                                      loading={busyId === runtime.runtime_id}
                                      onClick={() =>
                                        modal.confirm({
                                          title: t(
                                            "hub.runtimes.rebuildTitle",
                                            { id: runtime.runtime_id },
                                          ),
                                          content: t(
                                            "hub.runtimes.rebuildDescription",
                                          ),
                                          onOk: () =>
                                            runRuntimeAction(
                                              runtime.runtime_id,
                                              "rebuild",
                                            ),
                                        })
                                      }
                                    >
                                      {t("hub.actions.rebuild")}
                                    </Button>
                                  )}
                                {me?.role === "admin" && (
                                  <Button
                                    size="small"
                                    danger
                                    disabled={runtime.state === "running"}
                                    aria-label={t("hub.runtimes.removeTitle", {
                                      id: runtime.runtime_id,
                                    })}
                                    icon={<Trash2 size={14} />}
                                    onClick={() =>
                                      modal.confirm({
                                        title: t("hub.runtimes.removeTitle", {
                                          id: runtime.runtime_id,
                                        }),
                                        content: t(
                                          "hub.runtimes.removeDescription",
                                        ),
                                        okButtonProps: { danger: true },
                                        onOk: () =>
                                          runRuntimeAction(
                                            runtime.runtime_id,
                                            "delete",
                                          ),
                                      })
                                    }
                                  />
                                )}
                              </div>
                            </td>
                          </tr>
                        ))}
                        {runtimes.items.length === 0 && (
                          <EmptyRow
                            colSpan={7}
                            message={t("hub.runtimes.emptyTitle")}
                          />
                        )}
                      </tbody>
                    </table>
                  </div>
                  <PageFooter
                    page={runtimes}
                    onChange={(page) => loadRuntimes(page)}
                  />
                </DataPanel>
              </section>
            )}
            {section === "models" && me?.role === "admin" && (
              <OrganizationModels initialModel={sectionTarget} />
            )}
            {section === "users" && me?.role === "admin" && (
              <UserManagement
                initialUser={sectionTarget}
                users={users.items}
                me={me}
                total={users.total}
                page={users.page}
                pageSize={users.pageSize}
                query={userQuery}
                onQuery={setUserQuery}
                role={userRole}
                onRole={setUserRole}
                state={userDisabled}
                onState={setUserDisabled}
                onPage={loadUsers}
                onCreate={() => setUserModalOpen(true)}
                onUpdate={updateUser}
              />
            )}
            {section === "credentials" && (
              <section>
                <PageHeader
                  title={t("hub.credentials.title")}
                  description={t("hub.credentials.description")}
                  action={
                    <Button
                      type="primary"
                      icon={<Plus size={15} />}
                      onClick={() => setCredentialModalOpen(true)}
                    >
                      {t("hub.credentials.storeCredential")}
                    </Button>
                  }
                />
                <DataPanel
                  search={credentialQuery}
                  onSearch={setCredentialQuery}
                  searchPlaceholder={t("hub.table.searchCredentials")}
                  filter={
                    <Select
                      allowClear
                      value={credentialScope}
                      placeholder={t("hub.table.allScopes")}
                      className={styles.filterSelect}
                      onChange={setCredentialScope}
                      options={[
                        {
                          value: "tenant",
                          label: t("hub.credentialForm.allRuntimes"),
                        },
                        ...runtimeOptions,
                      ]}
                    />
                  }
                >
                  <div className={styles.tableWrap}>
                    <table>
                      <thead>
                        <tr>
                          <th>{t("hub.table.credential")}</th>
                          <th>{t("hub.table.scope")}</th>
                          <th>{t("hub.table.updated")}</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {credentials.items.map((credential) => (
                          <tr key={`${credential.scope}:${credential.name}`}>
                            <td>
                              <EntityCell
                                icon={<KeyRound size={16} />}
                                title={credential.name}
                                detail={t("hub.credentials.encrypted")}
                              />
                            </td>
                            <td className={styles.mono}>{credential.scope}</td>
                            <td>
                              {formatDate(credential.updated_at, i18n.language)}
                            </td>
                            <td>
                              <div className={styles.rowActions}>
                                <Button
                                  size="small"
                                  danger
                                  aria-label={t("hub.credentials.deleteTitle", {
                                    name: credential.name,
                                  })}
                                  icon={<Trash2 size={14} />}
                                  onClick={() =>
                                    modal.confirm({
                                      title: t("hub.credentials.deleteTitle", {
                                        name: credential.name,
                                      }),
                                      content: t(
                                        "hub.credentials.deleteDescription",
                                      ),
                                      okButtonProps: { danger: true },
                                      onOk: async () => {
                                        await hubApi.deleteCredential(
                                          credential.scope,
                                          credential.name,
                                        );
                                        await loadCredentials(credentials.page);
                                      },
                                    })
                                  }
                                />
                              </div>
                            </td>
                          </tr>
                        ))}
                        {credentials.items.length === 0 && (
                          <EmptyRow
                            colSpan={4}
                            message={t("hub.credentials.emptyTitle")}
                          />
                        )}
                      </tbody>
                    </table>
                  </div>
                  <PageFooter page={credentials} onChange={loadCredentials} />
                </DataPanel>
              </section>
            )}
            {section === "audit" && me?.role === "admin" && (
              <section>
                <PageHeader
                  title={t("hub.audit.title")}
                  description={t("hub.audit.description")}
                />
                <DataPanel
                  search={auditQuery}
                  onSearch={setAuditQuery}
                  searchPlaceholder={t("hub.table.searchAudit")}
                  filter={
                    <Select
                      allowClear
                      value={auditAction}
                      placeholder={t("hub.table.allActions")}
                      className={styles.filterSelect}
                      onChange={setAuditAction}
                      options={[
                        "runtime.create",
                        "runtime.start",
                        "runtime.stop",
                        "runtime.disable",
                        "runtime.rebuild",
                        "runtime.delete",
                        "image.pull",
                        "user.create",
                        "user.update",
                        "credential.store",
                        "credential.delete",
                        "settings.update",
                        "auth.register",
                        "model.policy_update",
                        "model.connection_create",
                        "model.connection_update",
                        "model.publish",
                        "model.create",
                        "model.update",
                        "model.test",
                        "invitation.create",
                        "invitation.revoke",
                        "budget.update",
                        "user.password_reset",
                      ].map((action) => ({
                        value: action,
                        label: t(`hub.auditActions.${action}`),
                      }))}
                    />
                  }
                >
                  <AuditTable
                    events={audit.items}
                    language={i18n.language}
                    t={t}
                  />
                  <PageFooter page={audit} onChange={loadAudit} />
                </DataPanel>
              </section>
            )}
            {section === "settings" &&
              me?.role === "admin" &&
              (settings ? (
                <SettingsPanel
                  initialTab={sectionTarget}
                  form={settingsForm}
                  settings={settings}
                  dockerImages={dockerImages}
                  dockerImagesLoading={dockerImagesLoading}
                  dockerPulls={dockerPulls}
                  dockerPulling={dockerPulling}
                  saving={settingsSaving}
                  onLoadDockerData={loadDockerData}
                  onPullImage={pullDockerImage}
                  onSave={saveSettings}
                  t={t}
                />
              ) : (
                <SettingsLoadingPanel t={t} />
              ))}
          </>
        )}
      </HubShell>

      <Modal
        title={t("hub.runtimeForm.title")}
        open={runtimeModalOpen}
        onCancel={() => setRuntimeModalOpen(false)}
        footer={null}
        destroyOnHidden
      >
        <Form
          form={runtimeForm}
          layout="vertical"
          initialValues={{ autoStart: true }}
          onFinish={createRuntime}
        >
          <Form.Item
            label={t("hub.runtimeForm.runtimeId")}
            name="runtimeId"
            rules={[
              { required: true, message: t("hub.validation.required") },
              {
                pattern: /^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$/,
                message: t("hub.validation.runtimeIdInvalid"),
              },
            ]}
          >
            <Input placeholder="research-runtime" autoFocus />
          </Form.Item>
          <Form.Item
            label={t("hub.runtimeForm.startImmediately")}
            name="autoStart"
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>
            {t("hub.runtimeForm.submit")}
          </Button>
        </Form>
      </Modal>

      <Modal
        title={t("hub.userForm.title")}
        open={userModalOpen}
        onCancel={() => setUserModalOpen(false)}
        footer={null}
        destroyOnHidden
      >
        <Form
          form={userForm}
          layout="vertical"
          initialValues={{ role: "user" }}
          onFinish={createUser}
        >
          <Form.Item
            label={t("hub.userForm.username")}
            name="username"
            rules={[{ required: true, message: t("hub.validation.required") }]}
          >
            <Input autoFocus />
          </Form.Item>
          <Form.Item
            label={t("hub.userForm.temporaryPassword")}
            name="password"
            rules={[
              { required: true, message: t("hub.validation.required") },
              { min: 8, message: t("hub.validation.passwordMin") },
            ]}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item label={t("hub.userForm.role")} name="role">
            <Select
              options={[
                { value: "user", label: t("hub.roles.user") },
                { value: "admin", label: t("hub.roles.admin") },
              ]}
            />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>
            {t("hub.userForm.submit")}
          </Button>
        </Form>
      </Modal>

      <Modal
        title={t("hub.credentialForm.title")}
        open={credentialModalOpen}
        onCancel={() => setCredentialModalOpen(false)}
        footer={null}
        destroyOnHidden
      >
        <Form
          form={credentialForm}
          layout="vertical"
          initialValues={{ scope: "tenant" }}
          onFinish={saveCredential}
        >
          <Form.Item label={t("hub.credentialForm.scope")} name="scope">
            <Select
              options={[
                {
                  value: "tenant",
                  label: t("hub.credentialForm.allRuntimes"),
                },
                ...runtimeOptions,
              ]}
            />
          </Form.Item>
          <Form.Item
            label={t("hub.credentialForm.environmentName")}
            name="name"
            rules={[
              { required: true, message: t("hub.validation.required") },
              {
                pattern: /^[A-Z][A-Z0-9_]{0,127}$/,
                message: t("hub.validation.credentialNameInvalid"),
              },
            ]}
          >
            <Input placeholder="OPENAI_API_KEY" />
          </Form.Item>
          <Form.Item
            label={t("hub.credentialForm.secretValue")}
            name="value"
            rules={[{ required: true, message: t("hub.validation.required") }]}
          >
            <Input.Password />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>
            {t("hub.credentialForm.submit")}
          </Button>
        </Form>
      </Modal>
    </>
  );
}

function SettingsLoadingPanel({
  t,
}: {
  t: (key: string, options?: Record<string, unknown>) => string;
}) {
  return (
    <section>
      <PageHeader
        title={t("hub.settings.title")}
        description={t("hub.settings.description")}
      />
      <div className={styles.settingsLoadingCard}>
        <Skeleton active paragraph={{ rows: 5 }} />
      </div>
    </section>
  );
}

function SettingsPanel({
  initialTab,
  form,
  settings,
  dockerImages,
  dockerImagesLoading,
  dockerPulls,
  dockerPulling,
  saving,
  onLoadDockerData,
  onPullImage,
  onSave,
  t,
}: {
  initialTab?: string;
  form: FormInstance<SettingsFormValues>;
  settings: HubSettings;
  dockerImages: HubDockerImageCatalog | null;
  dockerImagesLoading: boolean;
  dockerPulls: HubDockerImagePull[];
  dockerPulling: boolean;
  saving: boolean;
  onLoadDockerData: () => Promise<void>;
  onPullImage: (reference: string) => Promise<void>;
  onSave: (values: SettingsFormValues) => Promise<void>;
  t: (key: string, options?: Record<string, unknown>) => string;
}) {
  const screens = Grid.useBreakpoint();
  const [activeTab, setActiveTab] = useState(initialTab ?? "access");
  const runtimeProvisioner = Form.useWatch("runtimeProvisioner", form);
  const dockerSource = Form.useWatch("dockerSource", form);
  const dockerImage = Form.useWatch("dockerImage", form);
  const findLocalImage = (reference: string) => {
    const key = dockerReferenceKey(reference);
    return dockerImages?.local_images.find((image) =>
      [image.reference, ...image.digests].some(
        (name) => dockerReferenceKey(name) === key,
      ),
    );
  };
  const officialOptions = (dockerImages?.official_images || [])
    .filter((image) => image.source === dockerSource)
    .map((image) => ({
      value: image.reference,
      label: `${image.tag} · ${t(
        findLocalImage(image.reference)
          ? "hub.settings.docker.downloaded"
          : "hub.settings.docker.notDownloaded",
      )}`,
    }));
  const localImageOptions = (dockerImages?.local_images || [])
    .filter((image) => !image.reference.endsWith("@untagged"))
    .map((image) => ({
      value: image.reference,
      label: `${image.reference} · ${image.short_id} · ${formatImageSize(
        image.size,
      )}`,
    }));
  const selectedLocalImage = findLocalImage(dockerImage || "");
  const imageParts = dockerReferenceParts(dockerImage || "");
  const imageOrigin =
    dockerSource === "docker_hub"
      ? t("hub.settings.docker.dockerHub")
      : dockerSource === "aliyun_acr"
      ? t("hub.settings.docker.aliyunAcr")
      : dockerSource === "local"
      ? t("hub.settings.docker.localHost")
      : t("hub.settings.docker.customRegistry");
  const currentPull = dockerPulls.find(
    (pull) =>
      pull.reference === dockerImage &&
      (pull.status === "queued" || pull.status === "pulling"),
  );
  return (
    <section>
      <PageHeader
        title={t("hub.settings.title")}
        description={t("hub.settings.description")}
        action={
          activeTab !== "budget" && (
            <Button
              type="primary"
              icon={<Save size={15} />}
              loading={saving}
              onClick={() => form.submit()}
            >
              {t("hub.settings.save")}
            </Button>
          )
        }
      />
      <Form
        form={form}
        layout="vertical"
        requiredMark={false}
        onFinish={() => onSave(form.getFieldsValue(true))}
      >
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          className={styles.settingsTabs}
          tabPosition={screens.lg ? "left" : "top"}
          items={[
            {
              key: "access",
              label: t("hub.settings.access.title"),
              forceRender: true,
              children: (
                <div className={styles.accessSettings}>
                  <article className={styles.settingsCard}>
                    <div className={styles.settingsCardHeader}>
                      <div>
                        <strong>{t("hub.settings.access.title")}</strong>
                      </div>
                      <Settings2 size={18} />
                    </div>
                    <Form.Item
                      name="publicBaseUrl"
                      label={t("hub.settings.access.publicBaseUrl")}
                      rules={[{ type: "url" }]}
                    >
                      <Input placeholder="https://hub.example.com" />
                    </Form.Item>
                    <Form.Item
                      name="registrationMode"
                      label={t("hub.governance.settings.registration")}
                    >
                      <Radio.Group className={styles.registrationChoices}>
                        {(["open", "invite", "closed"] as const).map((mode) => (
                          <Radio key={mode} value={mode}>
                            <strong>
                              {t(`hub.governance.settings.${mode}`)}
                            </strong>
                          </Radio>
                        ))}
                      </Radio.Group>
                    </Form.Item>
                  </article>
                </div>
              ),
            },
            {
              key: "security",
              label: t("hub.governance.settings.security"),
              forceRender: true,
              children: (
                <div className={styles.settingsGrid}>
                  <article
                    className={`${styles.settingsCard} ${styles.wideSettingsCard}`}
                  >
                    <div className={styles.settingsCardHeader}>
                      <div>
                        <strong>{t("hub.settings.security.title")}</strong>
                      </div>
                      <ShieldBan size={18} />
                    </div>
                    <div className={styles.securityNetworkGrid}>
                      <Form.Item
                        name="ipBlacklist"
                        label={t("hub.settings.security.ipBlacklist")}
                      >
                        <Select mode="tags" tokenSeparators={[","]} />
                      </Form.Item>
                      <Form.Item
                        name="trustedProxyIps"
                        label={t("hub.settings.security.trustedProxyIps")}
                      >
                        <Select mode="tags" tokenSeparators={[","]} />
                      </Form.Item>
                    </div>
                    <div className={styles.rateLimitGrid}>
                      <RateLimitFields
                        prefix="login"
                        title={t("hub.settings.security.loginRateLimit")}
                        form={form}
                        t={t}
                      />
                      <RateLimitFields
                        prefix="registration"
                        title={t("hub.settings.security.registrationRateLimit")}
                        form={form}
                        t={t}
                      />
                    </div>
                  </article>
                </div>
              ),
            },
            {
              key: "budget",
              label: t("hub.governance.settings.budget"),
              children: <OrganizationBudget />,
            },
            {
              key: "runtime",
              label: t("hub.settings.tabs.runtime"),
              forceRender: true,
              children: (
                <div className={styles.settingsGrid}>
                  <article className={styles.settingsCard}>
                    <div className={styles.settingsCardHeader}>
                      <div>
                        <strong>{t("hub.settings.runtime.title")}</strong>
                      </div>
                      <Boxes size={18} />
                    </div>
                    <Form.Item
                      name="runtimeProvisioner"
                      label={t("hub.settings.runtime.provisioner")}
                      rules={[
                        {
                          required: true,
                          message: t("hub.validation.required"),
                        },
                      ]}
                    >
                      <BackendSelector
                        available={settings.available_provisioners}
                        onBackendChange={(backend) => {
                          if (backend === "docker") {
                            void onLoadDockerData();
                          }
                        }}
                        t={t}
                      />
                    </Form.Item>
                  </article>

                  <article className={styles.settingsCard}>
                    <div className={styles.settingsCardHeader}>
                      <div>
                        <strong>{t("hub.settings.quotas.title")}</strong>
                      </div>
                      <Gauge size={18} />
                    </div>
                    <div className={styles.quotaFields}>
                      <Form.Item
                        name="maxRunningRuntimes"
                        label={t("hub.settings.quotas.maxRunningRuntimes")}
                        extra={t("hub.settings.quotas.unlimitedHint")}
                      >
                        <InputNumber min={0} precision={0} />
                      </Form.Item>
                    </div>
                  </article>

                  {runtimeProvisioner === "docker" && (
                    <article
                      className={`${styles.settingsCard} ${styles.wideSettingsCard}`}
                    >
                      <div className={styles.settingsCardHeader}>
                        <div>
                          <strong>{t("hub.settings.docker.title")}</strong>
                        </div>
                        <Box size={18} />
                      </div>
                      {dockerImagesLoading && !dockerImages && (
                        <div className={styles.dockerDataLoading}>
                          <Skeleton
                            active
                            title={false}
                            paragraph={{ rows: 2 }}
                          />
                        </div>
                      )}
                      {dockerImages && !dockerImages.available && (
                        <div className={styles.dockerWarning}>
                          {dockerImages?.reason ||
                            t("hub.settings.docker.unavailable")}
                        </div>
                      )}
                      <div className={styles.imagePolicySection}>
                        <Form.Item
                          name="dockerSource"
                          label={t("hub.settings.docker.source")}
                          rules={[{ required: true }]}
                        >
                          <ImageSourceSelector
                            hasLocalImages={localImageOptions.length > 0}
                            onSourceChange={(source) => {
                              if (
                                source === "docker_hub" ||
                                source === "aliyun_acr"
                              ) {
                                const repository =
                                  dockerImages?.sources[source];
                                if (repository) {
                                  form.setFieldValue(
                                    "dockerImage",
                                    `${repository}:latest`,
                                  );
                                }
                              }
                              if (source === "local" && localImageOptions[0]) {
                                form.setFieldValue(
                                  "dockerImage",
                                  localImageOptions[0].value,
                                );
                                form.setFieldValue("dockerPullPolicy", "never");
                              }
                            }}
                            t={t}
                          />
                        </Form.Item>
                        <div className={styles.imageSelectionGrid}>
                          <Form.Item
                            name="dockerImage"
                            label={t("hub.settings.docker.image")}
                            rules={[{ required: true }]}
                          >
                            {dockerSource === "custom" ? (
                              <Input placeholder="registry.example.com/qwenpaw:v1" />
                            ) : dockerSource === "local" ? (
                              <Select
                                options={localImageOptions}
                                placeholder={t(
                                  "hub.settings.docker.selectLocalImage",
                                )}
                                showSearch
                                optionFilterProp="label"
                              />
                            ) : (
                              <Select
                                options={officialOptions}
                                showSearch
                                optionFilterProp="label"
                              />
                            )}
                          </Form.Item>
                          <Form.Item
                            name="dockerPullPolicy"
                            label={t("hub.settings.docker.pullPolicy")}
                            rules={[{ required: true }]}
                          >
                            <Select
                              options={[
                                {
                                  value: "if_not_present",
                                  label: t("hub.settings.docker.ifNotPresent"),
                                },
                                {
                                  value: "always",
                                  label: t("hub.settings.docker.always"),
                                },
                                {
                                  value: "never",
                                  label: t("hub.settings.docker.never"),
                                },
                              ]}
                            />
                          </Form.Item>
                        </div>
                        <div className={styles.imageIdentityCard}>
                          <div className={styles.imageIdentityIcon}>
                            <Box size={18} />
                          </div>
                          <div className={styles.imageIdentityMain}>
                            <span>
                              {t("hub.settings.docker.selectedImage")}
                            </span>
                            <strong>{dockerImage || "—"}</strong>
                            <small>{imageOrigin}</small>
                          </div>
                          <dl>
                            <div>
                              <dt>{t("hub.settings.docker.repository")}</dt>
                              <dd>{imageParts.repository || "—"}</dd>
                            </div>
                            <div>
                              <dt>Tag</dt>
                              <dd>{imageParts.tag}</dd>
                            </div>
                            <div>
                              <dt>{t("hub.settings.docker.localStatus")}</dt>
                              <dd>
                                {selectedLocalImage
                                  ? t("hub.settings.docker.downloaded")
                                  : t("hub.settings.docker.notDownloaded")}
                              </dd>
                            </div>
                            <div>
                              <dt>Digest / ID</dt>
                              <dd>
                                {selectedLocalImage?.digests[0] ||
                                  selectedLocalImage?.short_id ||
                                  "—"}
                              </dd>
                            </div>
                          </dl>
                          <div className={styles.imageIdentityActions}>
                            {dockerSource !== "local" && (
                              <Button
                                icon={<RefreshCw size={14} />}
                                loading={dockerPulling}
                                disabled={
                                  !dockerImages?.available || !dockerImage
                                }
                                onClick={() => onPullImage(dockerImage)}
                              >
                                {t("hub.settings.docker.pullImage")}
                              </Button>
                            )}
                            <span>
                              {t("hub.settings.docker.localImages", {
                                count: dockerImages?.local_images.length || 0,
                              })}
                            </span>
                          </div>
                          {currentPull && (
                            <div className={styles.imageIdentityProgress}>
                              <Progress
                                percent={currentPull.progress}
                                status="active"
                                size="small"
                              />
                            </div>
                          )}
                        </div>
                      </div>
                      <div className={styles.resourceTitle}>
                        {t("hub.settings.docker.resources")}
                      </div>
                      <div className={styles.resourceFields}>
                        <Form.Item
                          name="dockerCpuLimit"
                          label={t("hub.settings.docker.cpuLimit")}
                        >
                          <InputNumber min={0.1} max={128} step={0.1} />
                        </Form.Item>
                        <Form.Item
                          name="dockerMemoryLimitMb"
                          label={t("hub.settings.docker.memoryLimit")}
                        >
                          <InputNumber min={256} precision={0} />
                        </Form.Item>
                        <Form.Item
                          name="dockerPidsLimit"
                          label={t("hub.settings.docker.pidsLimit")}
                        >
                          <InputNumber min={64} precision={0} />
                        </Form.Item>
                        <Form.Item
                          name="dockerShmSizeMb"
                          label={t("hub.settings.docker.shmSize")}
                          rules={[{ required: true }]}
                        >
                          <InputNumber min={64} precision={0} />
                        </Form.Item>
                      </div>
                    </article>
                  )}
                </div>
              ),
            },
          ]}
        />
      </Form>
    </section>
  );
}

function RateLimitFields({
  prefix,
  title,
  form,
  t,
}: {
  prefix: "login" | "registration";
  title: string;
  initialTab?: string;
  form: FormInstance<SettingsFormValues>;
  t: (key: string, options?: Record<string, unknown>) => string;
}) {
  const enabledName = `${prefix}RateEnabled` as keyof SettingsFormValues;
  const enabled = Form.useWatch(enabledName, form);
  return (
    <div className={styles.rateLimitGroup}>
      <div className={styles.rateLimitHeader}>
        <div>
          <strong>{title}</strong>
        </div>
        <Form.Item name={enabledName} valuePropName="checked" noStyle>
          <Switch />
        </Form.Item>
      </div>
      <div className={styles.rateLimitFields}>
        <Form.Item
          name={`${prefix}MaxAttempts`}
          label={t("hub.settings.security.maxAttempts")}
          rules={[{ required: true }]}
        >
          <InputNumber min={1} max={10000} disabled={!enabled} />
        </Form.Item>
        <Form.Item
          name={`${prefix}WindowSeconds`}
          label={t("hub.settings.security.windowSeconds")}
          rules={[{ required: true }]}
        >
          <InputNumber min={1} max={86400} disabled={!enabled} />
        </Form.Item>
        <Form.Item
          name={`${prefix}BlockSeconds`}
          label={t("hub.settings.security.blockSeconds")}
          rules={[{ required: true }]}
        >
          <InputNumber min={1} max={604800} disabled={!enabled} />
        </Form.Item>
      </div>
    </div>
  );
}

function BackendSelector({
  value,
  onChange,
  onBackendChange,
  available,
  t,
}: {
  value?: "local" | "docker";
  onChange?: (value: "local" | "docker") => void;
  onBackendChange: (value: "local" | "docker") => void;
  available: string[];
  t: (key: string, options?: Record<string, unknown>) => string;
}) {
  const options = [
    {
      value: "local" as const,
      icon: HardDrive,
      title: t("hub.settings.runtime.localBackend"),
    },
    {
      value: "docker" as const,
      icon: Box,
      title: t("hub.settings.runtime.dockerBackend"),
    },
  ];
  return (
    <div className={styles.choiceCards}>
      {options.map((option) => {
        const Icon = option.icon;
        const disabled = !available.includes(option.value);
        return (
          <button
            key={option.value}
            type="button"
            className={
              value === option.value
                ? styles.choiceCardActive
                : styles.choiceCard
            }
            disabled={disabled}
            aria-pressed={value === option.value}
            onClick={() => {
              onChange?.(option.value);
              onBackendChange(option.value);
            }}
          >
            <Icon size={18} />
            <span>
              <strong>{option.title}</strong>
              {disabled && (
                <small>{t("hub.settings.runtime.backendUnavailable")}</small>
              )}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function ImageSourceSelector({
  value,
  onChange,
  onSourceChange,
  hasLocalImages,
  t,
}: {
  value?: SettingsFormValues["dockerSource"];
  onChange?: (value: SettingsFormValues["dockerSource"]) => void;
  onSourceChange: (value: SettingsFormValues["dockerSource"]) => void;
  hasLocalImages: boolean;
  t: (key: string, options?: Record<string, unknown>) => string;
}) {
  const options = [
    {
      value: "docker_hub" as const,
      icon: Box,
      title: t("hub.settings.docker.dockerHub"),
      description: "docker.io/agentscope/qwenpaw",
    },
    {
      value: "aliyun_acr" as const,
      icon: Boxes,
      title: t("hub.settings.docker.aliyunAcr"),
      description: "agentscope-registry.ap-southeast-1.cr.aliyuncs.com",
    },
    {
      value: "local" as const,
      icon: HardDrive,
      title: t("hub.settings.docker.localHost"),
    },
    {
      value: "custom" as const,
      icon: Settings2,
      title: t("hub.settings.docker.custom"),
    },
  ];
  return (
    <div className={styles.imageSourceCards}>
      {options.map((option) => {
        const Icon = option.icon;
        const disabled = option.value === "local" && !hasLocalImages;
        return (
          <button
            key={option.value}
            type="button"
            className={
              value === option.value
                ? styles.sourceCardActive
                : styles.sourceCard
            }
            disabled={disabled}
            aria-pressed={value === option.value}
            onClick={() => {
              onChange?.(option.value);
              onSourceChange(option.value);
            }}
          >
            <Icon size={16} />
            <span>
              <strong>{option.title}</strong>
              <small>
                {disabled
                  ? t("hub.settings.docker.noLocalImages")
                  : option.description}
              </small>
            </span>
          </button>
        );
      })}
    </div>
  );
}

function PageHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <header className={styles.pageHeader}>
      <div>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {action}
    </header>
  );
}

function DataPanel({
  search,
  onSearch,
  searchPlaceholder,
  filter,
  children,
}: {
  search: string;
  onSearch: (value: string) => void;
  searchPlaceholder: string;
  filter?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className={styles.dataPanel}>
      <div className={styles.dataToolbar}>
        <div className={styles.searchBox}>
          <Search size={15} />
          <Input
            variant="borderless"
            value={search}
            aria-label={searchPlaceholder}
            placeholder={searchPlaceholder}
            onChange={(event) => onSearch(event.target.value)}
            allowClear
          />
        </div>
        {filter && (
          <div className={styles.filterControl}>
            <ListFilter size={14} />
            {filter}
          </div>
        )}
      </div>
      {children}
    </div>
  );
}

function EntityCell({
  icon,
  title,
  detail,
}: {
  icon: React.ReactNode;
  title: React.ReactNode;
  detail: string;
}) {
  return (
    <div className={styles.entityCell}>
      <span>{icon}</span>
      <div>
        <strong>{title}</strong>
        <small>{detail}</small>
      </div>
    </div>
  );
}

function PageFooter<T>({
  page,
  onChange,
}: {
  page: PageData<T>;
  onChange: (page: number) => void;
}) {
  const { t } = useTranslation();
  return (
    <footer className={styles.pagination}>
      <span>{t("hub.table.total", { total: page.total })}</span>
      <Pagination
        current={page.page}
        pageSize={page.pageSize}
        total={page.total}
        showSizeChanger={false}
        size="small"
        onChange={onChange}
      />
    </footer>
  );
}

function AuditTable({
  events,
  language,
  t,
}: {
  events: HubAuditEvent[];
  language: string;
  t: (key: string) => string;
}) {
  return (
    <div className={styles.tableWrap}>
      <table>
        <thead>
          <tr>
            <th>{t("hub.table.event")}</th>
            <th>{t("hub.table.actor")}</th>
            <th>{t("hub.table.resource")}</th>
            <th>{t("hub.table.result")}</th>
            <th>{t("hub.table.time")}</th>
          </tr>
        </thead>
        <tbody>
          {events.map((event) => (
            <tr key={event.event_id}>
              <td>
                <EntityCell
                  icon={<ScrollText size={16} />}
                  title={t(`hub.auditActions.${event.action}`)}
                  detail={event.action}
                />
              </td>
              <td>{event.actor_username}</td>
              <td>
                <strong>{event.resource_id}</strong>
                <small>{event.resource_type}</small>
              </td>
              <td>
                <Tag color={event.outcome === "success" ? "success" : "error"}>
                  {t(`hub.auditOutcomes.${event.outcome}`)}
                </Tag>
              </td>
              <td>{formatDate(event.created_at, language)}</td>
            </tr>
          ))}
          {events.length === 0 && (
            <EmptyRow colSpan={5} message={t("hub.audit.empty")} />
          )}
        </tbody>
      </table>
    </div>
  );
}

function EmptyRow({ colSpan, message }: { colSpan: number; message: string }) {
  return (
    <tr className={styles.emptyRow}>
      <td colSpan={colSpan}>
        <Search size={20} />
        <span>{message}</span>
      </td>
    </tr>
  );
}
