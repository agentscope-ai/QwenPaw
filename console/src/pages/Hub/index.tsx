import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { App, Button, Form, Input, Modal, Select, Switch, Tag } from "antd";
import {
  Activity,
  CircleAlert,
  CircleStop,
  House,
  KeyRound,
  LogOut,
  Moon,
  Play,
  Plus,
  Server,
  ShieldCheck,
  Sun,
  Trash2,
  Users,
} from "lucide-react";
import { clearAuthToken } from "../../api/config";
import LanguageSwitcher from "../../components/LanguageSwitcher";
import { useTheme } from "../../contexts/ThemeContext";
import {
  hubApi,
  type HubCredential,
  type HubHealth,
  type HubRuntime,
  type HubUser,
} from "../../api/modules/hub";
import styles from "./index.module.less";

type Section = "runtimes" | "users" | "credentials";

const STATE_COLORS: Record<HubRuntime["state"], string> = {
  created: "default",
  starting: "processing",
  running: "success",
  stopped: "default",
  failed: "error",
};

export default function HubPage() {
  const { message, modal } = App.useApp();
  const { t, i18n } = useTranslation();
  const { isDark, toggleTheme } = useTheme();
  const [me, setMe] = useState<HubUser | null>(null);
  const [section, setSection] = useState<Section>("runtimes");
  const [runtimes, setRuntimes] = useState<HubRuntime[]>([]);
  const [users, setUsers] = useState<HubUser[]>([]);
  const [credentials, setCredentials] = useState<HubCredential[]>([]);
  const [health, setHealth] = useState<HubHealth | null>(null);
  const [registrationEnabled, setRegistrationEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [runtimeModalOpen, setRuntimeModalOpen] = useState(false);
  const [userModalOpen, setUserModalOpen] = useState(false);
  const [credentialModalOpen, setCredentialModalOpen] = useState(false);
  const [runtimeForm] = Form.useForm();
  const [userForm] = Form.useForm();
  const [credentialForm] = Form.useForm();

  const loadRuntimes = useCallback(async () => {
    setRuntimes(await hubApi.listRuntimes());
  }, []);

  const loadUsers = useCallback(async () => {
    const [nextUsers, registration] = await Promise.all([
      hubApi.listUsers(),
      hubApi.getRegistration(),
    ]);
    setUsers(nextUsers);
    setRegistrationEnabled(registration.enabled);
  }, []);

  const loadCredentials = useCallback(async () => {
    setCredentials(await hubApi.listCredentials());
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([hubApi.me(), hubApi.listRuntimes(), hubApi.getHealth()])
      .then(([identity, runtimeList, runtimeHealth]) => {
        if (cancelled) return;
        setMe(identity);
        setRuntimes(runtimeList);
        setHealth(runtimeHealth);
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
    if (section === "users" && me?.role === "admin") {
      loadUsers().catch((error) => message.error(error.message));
    }
    if (section === "credentials") {
      loadCredentials().catch((error) => message.error(error.message));
    }
  }, [loadCredentials, loadUsers, me?.role, message, section]);

  const runtimeOptions = useMemo(
    () =>
      runtimes.map((runtime) => ({
        label: runtime.runtime_id,
        value: `runtime:${runtime.runtime_id}`,
      })),
    [runtimes],
  );

  const runRuntimeAction = async (
    runtimeId: string,
    action: "start" | "stop" | "delete",
  ) => {
    setBusyId(runtimeId);
    try {
      if (action === "start") await hubApi.startRuntime(runtimeId);
      if (action === "stop") await hubApi.stopRuntime(runtimeId);
      if (action === "delete") await hubApi.deleteRuntime(runtimeId);
      await loadRuntimes();
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
      await loadRuntimes();
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
      await loadUsers();
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
      await loadUsers();
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
      await loadCredentials();
      message.success(t("hub.messages.credentialStored"));
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("hub.errors.saveFailed"),
      );
    }
  };

  const logout = () => {
    clearAuthToken();
    window.location.assign("/login");
  };

  const navigation = [
    {
      id: "runtimes" as const,
      label: t("hub.navigation.runtimes"),
      icon: Server,
    },
    ...(me?.role === "admin"
      ? [
          {
            id: "users" as const,
            label: t("hub.navigation.users"),
            icon: Users,
          },
        ]
      : []),
    {
      id: "credentials" as const,
      label: t("hub.navigation.credentials"),
      icon: KeyRound,
    },
  ];
  const runningCount = runtimes.filter(
    (runtime) => runtime.state === "running",
  ).length;
  const failedCount = runtimes.filter(
    (runtime) => runtime.state === "failed",
  ).length;
  const runtimeAvailable = health?.runtime_available === true;
  const runtimeAvailabilityKnown = health !== null;
  const defaultDriverStatus = health?.driver_statuses[health.default_driver];

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <img
            src={isDark ? "/logo-dark.svg" : "/logo-light.svg"}
            alt="QwenPaw"
          />
          <div>
            <strong>{t("hub.brand.title")}</strong>
            <span>{t("hub.brand.subtitle")}</span>
          </div>
        </div>
        <nav className={styles.navigation}>
          {navigation.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                className={section === item.id ? styles.activeNav : styles.nav}
                onClick={() => setSection(item.id)}
                type="button"
              >
                <Icon size={18} strokeWidth={1.8} />
                {item.label}
              </button>
            );
          })}
        </nav>
        <div className={styles.sidebarFooter}>
          <button
            type="button"
            onClick={() => window.location.assign("/")}
            className={styles.backButton}
          >
            <House size={17} />
            <span>{t("hub.actions.backToQwenPaw")}</span>
          </button>
          <div className={styles.account}>
            <div className={styles.avatarSmall}>
              {(me?.username || "Q").slice(0, 1).toUpperCase()}
            </div>
            <div>
              <strong>{me?.username || t("common.loading")}</strong>
              <span>{me?.role ? t(`hub.roles.${me.role}`) : ""}</span>
            </div>
            <div className={styles.languageControl}>
              <LanguageSwitcher persistRemotely={false} />
            </div>
            <button
              type="button"
              onClick={toggleTheme}
              aria-label={
                isDark
                  ? t("hub.actions.useLightTheme")
                  : t("hub.actions.useDarkTheme")
              }
            >
              {isDark ? <Sun size={16} /> : <Moon size={16} />}
            </button>
            <button
              type="button"
              onClick={logout}
              aria-label={t("hub.actions.signOut")}
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>

      <main className={styles.main}>
        {section === "runtimes" && (
          <section>
            <PageHeader
              eyebrow={t("hub.runtimes.eyebrow")}
              title={t("hub.runtimes.title")}
              description={t("hub.runtimes.description")}
              action={
                <Button
                  type="primary"
                  icon={<Plus size={16} />}
                  disabled={!runtimeAvailable}
                  onClick={() => setRuntimeModalOpen(true)}
                >
                  {t("hub.runtimes.newRuntime")}
                </Button>
              }
            />
            <div className={styles.metrics}>
              <Metric
                icon={<Server size={18} />}
                label={t("hub.runtimes.managed")}
                value={String(runtimes.length)}
                detail={t("hub.runtimes.localBoundaries")}
              />
              <Metric
                icon={<Activity size={18} />}
                label={t("hub.runtimes.runningNow")}
                value={String(runningCount)}
                detail={
                  failedCount > 0
                    ? t("hub.runtimes.needsAttention", {
                        count: failedCount,
                      })
                    : t("hub.runtimes.healthy")
                }
                warning={failedCount > 0}
              />
              <Metric
                icon={<ShieldCheck size={18} />}
                label={t("hub.runtimes.isolationPolicy")}
                value={
                  !runtimeAvailabilityKnown
                    ? t("common.loading")
                    : runtimeAvailable
                    ? t("hub.runtimes.available")
                    : t("hub.runtimes.unavailable")
                }
                detail={
                  !runtimeAvailabilityKnown
                    ? t("common.loading")
                    : runtimeAvailable
                    ? t("hub.runtimes.noFallback")
                    : t("hub.runtimes.executionBlocked")
                }
                warning={runtimeAvailabilityKnown && !runtimeAvailable}
              />
            </div>
            {runtimeAvailabilityKnown && (
              <div
                className={
                  runtimeAvailable ? styles.notice : styles.noticeError
                }
              >
                {runtimeAvailable ? (
                  <ShieldCheck size={18} />
                ) : (
                  <CircleAlert size={18} />
                )}
                <div>
                  <strong>
                    {runtimeAvailable
                      ? t("hub.runtimes.isolationTitle")
                      : t("hub.runtimes.unavailableTitle")}
                  </strong>
                  <span>
                    {runtimeAvailable
                      ? t("hub.runtimes.isolationDescription")
                      : t("hub.runtimes.unavailableDescription", {
                          driver: health?.default_driver || "local",
                          reason:
                            defaultDriverStatus?.reason ||
                            t("hub.runtimes.preflightFailed"),
                        })}
                  </span>
                </div>
              </div>
            )}
            <div className={styles.grid} aria-busy={loading}>
              {runtimes.map((runtime) => (
                <article className={styles.card} key={runtime.runtime_id}>
                  <div className={styles.cardHeader}>
                    <div className={styles.iconBox}>
                      <Server size={20} />
                    </div>
                    <div className={styles.cardTitle}>
                      <strong>{runtime.runtime_id}</strong>
                      <span>
                        {t("hub.runtimes.localEndpoint", {
                          endpoint: runtime.endpoint,
                        })}
                      </span>
                    </div>
                    <Tag color={STATE_COLORS[runtime.state]}>
                      {t(`hub.runtimeStates.${runtime.state}`)}
                    </Tag>
                  </div>
                  <dl className={styles.details}>
                    <div>
                      <dt>{t("hub.runtimes.driver")}</dt>
                      <dd>{runtime.driver}</dd>
                    </div>
                    <div>
                      <dt>{t("hub.runtimes.security")}</dt>
                      <dd>{runtime.security_level}</dd>
                    </div>
                    <div>
                      <dt>{t("hub.runtimes.tenant")}</dt>
                      <dd>{runtime.tenant_id}</dd>
                    </div>
                  </dl>
                  {runtime.last_error && (
                    <p className={styles.error}>{runtime.last_error}</p>
                  )}
                  <div className={styles.actions}>
                    {runtime.state === "running" ? (
                      <Button
                        icon={<CircleStop size={15} />}
                        loading={busyId === runtime.runtime_id}
                        onClick={() =>
                          runRuntimeAction(runtime.runtime_id, "stop")
                        }
                      >
                        {t("hub.actions.stop")}
                      </Button>
                    ) : (
                      <Button
                        icon={<Play size={15} />}
                        disabled={!runtimeAvailable}
                        loading={busyId === runtime.runtime_id}
                        onClick={() =>
                          runRuntimeAction(runtime.runtime_id, "start")
                        }
                      >
                        {t("hub.actions.start")}
                      </Button>
                    )}
                    <Button
                      danger
                      disabled={runtime.state === "running"}
                      icon={<Trash2 size={15} />}
                      aria-label={t("common.delete")}
                      onClick={() =>
                        modal.confirm({
                          title: t("hub.runtimes.removeTitle", {
                            id: runtime.runtime_id,
                          }),
                          content: t("hub.runtimes.removeDescription"),
                          okButtonProps: { danger: true },
                          onOk: () =>
                            runRuntimeAction(runtime.runtime_id, "delete"),
                        })
                      }
                    />
                  </div>
                </article>
              ))}
              {!loading && runtimes.length === 0 && (
                <EmptyState
                  icon={<Server size={26} />}
                  title={t("hub.runtimes.emptyTitle")}
                  description={t("hub.runtimes.emptyDescription")}
                />
              )}
            </div>
          </section>
        )}

        {section === "users" && me?.role === "admin" && (
          <section>
            <PageHeader
              eyebrow={t("hub.users.eyebrow")}
              title={t("hub.users.title")}
              description={t("hub.users.description")}
              action={
                <Button
                  type="primary"
                  icon={<Plus size={16} />}
                  onClick={() => setUserModalOpen(true)}
                >
                  {t("hub.users.addAccount")}
                </Button>
              }
            />
            <div className={styles.settingRow}>
              <div>
                <strong>{t("hub.users.publicRegistration")}</strong>
                <span>{t("hub.users.publicRegistrationDescription")}</span>
              </div>
              <Switch
                checked={registrationEnabled}
                onChange={async (enabled) => {
                  try {
                    await hubApi.setRegistration(enabled);
                    setRegistrationEnabled(enabled);
                  } catch (error) {
                    message.error(
                      error instanceof Error
                        ? error.message
                        : t("hub.errors.updateFailed"),
                    );
                  }
                }}
              />
            </div>
            <div className={styles.list}>
              {users.map((user) => (
                <div className={styles.userRow} key={user.user_id}>
                  <div className={styles.avatar}>
                    {user.username.slice(0, 2).toUpperCase()}
                  </div>
                  <div className={styles.userIdentity}>
                    <strong>{user.username}</strong>
                    <span>{user.user_id}</span>
                  </div>
                  <Select
                    value={user.role}
                    className={styles.roleSelect}
                    disabled={busyId === user.user_id}
                    options={[
                      {
                        label: t("hub.roles.admin"),
                        value: "admin",
                      },
                      { label: t("hub.roles.user"), value: "user" },
                    ]}
                    onChange={(role) => updateUser(user, { role })}
                  />
                  <div className={styles.userStatus}>
                    <span>
                      {user.disabled
                        ? t("hub.userStates.disabled")
                        : t("hub.userStates.active")}
                    </span>
                    <Switch
                      checked={!user.disabled}
                      loading={busyId === user.user_id}
                      onChange={(active) =>
                        updateUser(user, { disabled: !active })
                      }
                    />
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {section === "credentials" && (
          <section>
            <PageHeader
              eyebrow={t("hub.credentials.eyebrow")}
              title={t("hub.credentials.title")}
              description={t("hub.credentials.description")}
              action={
                <Button
                  type="primary"
                  icon={<Plus size={16} />}
                  onClick={() => setCredentialModalOpen(true)}
                >
                  {t("hub.credentials.storeCredential")}
                </Button>
              }
            />
            <div className={styles.list}>
              {credentials.map((credential) => (
                <div
                  className={styles.credentialRow}
                  key={`${credential.scope}:${credential.name}`}
                >
                  <div className={styles.iconBox}>
                    <KeyRound size={19} />
                  </div>
                  <div className={styles.userIdentity}>
                    <strong>{credential.name}</strong>
                    <span>{credential.scope}</span>
                  </div>
                  <span className={styles.updatedAt}>
                    {t("hub.credentials.updated", {
                      date: new Date(credential.updated_at).toLocaleString(
                        i18n.resolvedLanguage || i18n.language,
                      ),
                    })}
                  </span>
                  <Button
                    danger
                    icon={<Trash2 size={15} />}
                    aria-label={t("common.delete")}
                    onClick={() =>
                      modal.confirm({
                        title: t("hub.credentials.deleteTitle", {
                          name: credential.name,
                        }),
                        content: t("hub.credentials.deleteDescription"),
                        okButtonProps: { danger: true },
                        onOk: async () => {
                          await hubApi.deleteCredential(
                            credential.scope,
                            credential.name,
                          );
                          await loadCredentials();
                        },
                      })
                    }
                  />
                </div>
              ))}
              {credentials.length === 0 && (
                <EmptyState
                  icon={<KeyRound size={26} />}
                  title={t("hub.credentials.emptyTitle")}
                  description={t("hub.credentials.emptyDescription")}
                />
              )}
            </div>
          </section>
        )}
      </main>

      <Modal
        title={t("hub.runtimeForm.title")}
        open={runtimeModalOpen}
        onCancel={() => setRuntimeModalOpen(false)}
        footer={null}
        destroyOnClose
      >
        <Form
          form={runtimeForm}
          layout="vertical"
          initialValues={{ autoStart: true }}
          onFinish={createRuntime}
        >
          <p className={styles.formHint}>{t("hub.runtimeForm.hint")}</p>
          <Form.Item
            label={t("hub.runtimeForm.runtimeId")}
            name="runtimeId"
            rules={[
              {
                required: true,
                message: t("hub.validation.required"),
              },
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
        destroyOnClose
      >
        <Form
          form={userForm}
          layout="vertical"
          initialValues={{ role: "user" }}
          onFinish={createUser}
        >
          <p className={styles.formHint}>{t("hub.userForm.hint")}</p>
          <Form.Item
            label={t("hub.userForm.username")}
            name="username"
            rules={[
              {
                required: true,
                message: t("hub.validation.required"),
              },
            ]}
          >
            <Input autoFocus />
          </Form.Item>
          <Form.Item
            label={t("hub.userForm.temporaryPassword")}
            name="password"
            rules={[
              {
                required: true,
                message: t("hub.validation.required"),
              },
              {
                min: 8,
                message: t("hub.validation.passwordMin"),
              },
            ]}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item label={t("hub.userForm.role")} name="role">
            <Select
              options={[
                { label: t("hub.roles.user"), value: "user" },
                { label: t("hub.roles.admin"), value: "admin" },
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
        destroyOnClose
      >
        <Form
          form={credentialForm}
          layout="vertical"
          initialValues={{ scope: "tenant" }}
          onFinish={saveCredential}
        >
          <p className={styles.formHint}>{t("hub.credentialForm.hint")}</p>
          <Form.Item
            label={t("hub.credentialForm.scope")}
            name="scope"
            rules={[
              {
                required: true,
                message: t("hub.validation.required"),
              },
            ]}
          >
            <Select
              options={[
                {
                  label: t("hub.credentialForm.allRuntimes"),
                  value: "tenant",
                },
                ...runtimeOptions,
              ]}
            />
          </Form.Item>
          <Form.Item
            label={t("hub.credentialForm.environmentName")}
            name="name"
            rules={[
              {
                required: true,
                message: t("hub.validation.required"),
              },
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
            rules={[
              {
                required: true,
                message: t("hub.validation.required"),
              },
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>
            {t("hub.credentialForm.submit")}
          </Button>
        </Form>
      </Modal>
    </div>
  );
}

function Metric({
  icon,
  label,
  value,
  detail,
  warning = false,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  detail: string;
  warning?: boolean;
}) {
  return (
    <article className={warning ? styles.metricWarning : styles.metric}>
      <div className={styles.metricIcon}>{icon}</div>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{detail}</small>
      </div>
    </article>
  );
}

function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action: React.ReactNode;
}) {
  return (
    <header className={styles.pageHeader}>
      <div>
        <span className={styles.eyebrow}>{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </header>
  );
}

function EmptyState({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className={styles.empty}>
      {icon}
      <strong>{title}</strong>
      <span>{description}</span>
    </div>
  );
}
