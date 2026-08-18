import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { App, Button, Form, Input, Modal, Select, Switch, Tag } from "antd";
import {
  Activity,
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
  proApi,
  type ProCredential,
  type ProRuntime,
  type ProUser,
} from "../../api/modules/pro";
import styles from "./index.module.less";

type Section = "runtimes" | "users" | "credentials";

const STATE_COLORS: Record<ProRuntime["state"], string> = {
  created: "default",
  starting: "processing",
  running: "success",
  stopped: "default",
  failed: "error",
};

export default function ProPage() {
  const { message, modal } = App.useApp();
  const { t, i18n } = useTranslation();
  const { isDark, toggleTheme } = useTheme();
  const [me, setMe] = useState<ProUser | null>(null);
  const [section, setSection] = useState<Section>("runtimes");
  const [runtimes, setRuntimes] = useState<ProRuntime[]>([]);
  const [users, setUsers] = useState<ProUser[]>([]);
  const [credentials, setCredentials] = useState<ProCredential[]>([]);
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
    setRuntimes(await proApi.listRuntimes());
  }, []);

  const loadUsers = useCallback(async () => {
    const [nextUsers, registration] = await Promise.all([
      proApi.listUsers(),
      proApi.getRegistration(),
    ]);
    setUsers(nextUsers);
    setRegistrationEnabled(registration.enabled);
  }, []);

  const loadCredentials = useCallback(async () => {
    setCredentials(await proApi.listCredentials());
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([proApi.me(), proApi.listRuntimes()])
      .then(([identity, runtimeList]) => {
        if (cancelled) return;
        setMe(identity);
        setRuntimes(runtimeList);
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
      if (action === "start") await proApi.startRuntime(runtimeId);
      if (action === "stop") await proApi.stopRuntime(runtimeId);
      if (action === "delete") await proApi.deleteRuntime(runtimeId);
      await loadRuntimes();
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("pro.errors.actionFailed"),
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
      await proApi.createRuntime(values.runtimeId, values.autoStart);
      setRuntimeModalOpen(false);
      runtimeForm.resetFields();
      await loadRuntimes();
      message.success(t("pro.messages.runtimeCreated"));
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("pro.errors.createFailed"),
      );
    }
  };

  const createUser = async (values: {
    username: string;
    password: string;
    role: ProUser["role"];
  }) => {
    try {
      await proApi.createUser(values.username, values.password, values.role);
      setUserModalOpen(false);
      userForm.resetFields();
      await loadUsers();
      message.success(t("pro.messages.accountCreated"));
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("pro.errors.createFailed"),
      );
    }
  };

  const updateUser = async (
    user: ProUser,
    patch: Partial<Pick<ProUser, "role" | "disabled">>,
  ) => {
    setBusyId(user.user_id);
    try {
      await proApi.updateUser(user.user_id, patch);
      await loadUsers();
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("pro.errors.updateFailed"),
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
      await proApi.putCredential(values.scope, values.name, values.value);
      setCredentialModalOpen(false);
      credentialForm.resetFields();
      await loadCredentials();
      message.success(t("pro.messages.credentialStored"));
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("pro.errors.saveFailed"),
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
      label: t("pro.navigation.runtimes"),
      icon: Server,
    },
    ...(me?.role === "admin"
      ? [
          {
            id: "users" as const,
            label: t("pro.navigation.users"),
            icon: Users,
          },
        ]
      : []),
    {
      id: "credentials" as const,
      label: t("pro.navigation.credentials"),
      icon: KeyRound,
    },
  ];
  const runningCount = runtimes.filter(
    (runtime) => runtime.state === "running",
  ).length;
  const failedCount = runtimes.filter(
    (runtime) => runtime.state === "failed",
  ).length;

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <img
            src={isDark ? "/logo-dark.svg" : "/logo-light.svg"}
            alt="QwenPaw"
          />
          <div>
            <strong>{t("pro.brand.title")}</strong>
            <span>{t("pro.brand.subtitle")}</span>
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
            <span>{t("pro.actions.backToQwenPaw")}</span>
          </button>
          <div className={styles.account}>
            <div className={styles.avatarSmall}>
              {(me?.username || "Q").slice(0, 1).toUpperCase()}
            </div>
            <div>
              <strong>{me?.username || t("common.loading")}</strong>
              <span>{me?.role ? t(`pro.roles.${me.role}`) : ""}</span>
            </div>
            <div className={styles.languageControl}>
              <LanguageSwitcher persistRemotely={false} />
            </div>
            <button
              type="button"
              onClick={toggleTheme}
              aria-label={
                isDark
                  ? t("pro.actions.useLightTheme")
                  : t("pro.actions.useDarkTheme")
              }
            >
              {isDark ? <Sun size={16} /> : <Moon size={16} />}
            </button>
            <button
              type="button"
              onClick={logout}
              aria-label={t("pro.actions.signOut")}
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
              eyebrow={t("pro.runtimes.eyebrow")}
              title={t("pro.runtimes.title")}
              description={t("pro.runtimes.description")}
              action={
                <Button
                  type="primary"
                  icon={<Plus size={16} />}
                  onClick={() => setRuntimeModalOpen(true)}
                >
                  {t("pro.runtimes.newRuntime")}
                </Button>
              }
            />
            <div className={styles.metrics}>
              <Metric
                icon={<Server size={18} />}
                label={t("pro.runtimes.managed")}
                value={String(runtimes.length)}
                detail={t("pro.runtimes.localBoundaries")}
              />
              <Metric
                icon={<Activity size={18} />}
                label={t("pro.runtimes.runningNow")}
                value={String(runningCount)}
                detail={
                  failedCount > 0
                    ? t("pro.runtimes.needsAttention", {
                        count: failedCount,
                      })
                    : t("pro.runtimes.healthy")
                }
                warning={failedCount > 0}
              />
              <Metric
                icon={<ShieldCheck size={18} />}
                label={t("pro.runtimes.isolationPolicy")}
                value={t("pro.runtimes.failClosed")}
                detail={t("pro.runtimes.noFallback")}
              />
            </div>
            <div className={styles.notice}>
              <ShieldCheck size={18} />
              <div>
                <strong>{t("pro.runtimes.isolationTitle")}</strong>
                <span>{t("pro.runtimes.isolationDescription")}</span>
              </div>
            </div>
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
                        {t("pro.runtimes.localEndpoint", {
                          endpoint: runtime.endpoint,
                        })}
                      </span>
                    </div>
                    <Tag color={STATE_COLORS[runtime.state]}>
                      {t(`pro.runtimeStates.${runtime.state}`)}
                    </Tag>
                  </div>
                  <dl className={styles.details}>
                    <div>
                      <dt>{t("pro.runtimes.driver")}</dt>
                      <dd>{runtime.driver}</dd>
                    </div>
                    <div>
                      <dt>{t("pro.runtimes.security")}</dt>
                      <dd>{runtime.security_level}</dd>
                    </div>
                    <div>
                      <dt>{t("pro.runtimes.tenant")}</dt>
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
                        {t("pro.actions.stop")}
                      </Button>
                    ) : (
                      <Button
                        icon={<Play size={15} />}
                        loading={busyId === runtime.runtime_id}
                        onClick={() =>
                          runRuntimeAction(runtime.runtime_id, "start")
                        }
                      >
                        {t("pro.actions.start")}
                      </Button>
                    )}
                    <Button
                      danger
                      disabled={runtime.state === "running"}
                      icon={<Trash2 size={15} />}
                      aria-label={t("common.delete")}
                      onClick={() =>
                        modal.confirm({
                          title: t("pro.runtimes.removeTitle", {
                            id: runtime.runtime_id,
                          }),
                          content: t("pro.runtimes.removeDescription"),
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
                  title={t("pro.runtimes.emptyTitle")}
                  description={t("pro.runtimes.emptyDescription")}
                />
              )}
            </div>
          </section>
        )}

        {section === "users" && me?.role === "admin" && (
          <section>
            <PageHeader
              eyebrow={t("pro.users.eyebrow")}
              title={t("pro.users.title")}
              description={t("pro.users.description")}
              action={
                <Button
                  type="primary"
                  icon={<Plus size={16} />}
                  onClick={() => setUserModalOpen(true)}
                >
                  {t("pro.users.addAccount")}
                </Button>
              }
            />
            <div className={styles.settingRow}>
              <div>
                <strong>{t("pro.users.publicRegistration")}</strong>
                <span>{t("pro.users.publicRegistrationDescription")}</span>
              </div>
              <Switch
                checked={registrationEnabled}
                onChange={async (enabled) => {
                  try {
                    await proApi.setRegistration(enabled);
                    setRegistrationEnabled(enabled);
                  } catch (error) {
                    message.error(
                      error instanceof Error
                        ? error.message
                        : t("pro.errors.updateFailed"),
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
                        label: t("pro.roles.admin"),
                        value: "admin",
                      },
                      { label: t("pro.roles.user"), value: "user" },
                    ]}
                    onChange={(role) => updateUser(user, { role })}
                  />
                  <div className={styles.userStatus}>
                    <span>
                      {user.disabled
                        ? t("pro.userStates.disabled")
                        : t("pro.userStates.active")}
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
              eyebrow={t("pro.credentials.eyebrow")}
              title={t("pro.credentials.title")}
              description={t("pro.credentials.description")}
              action={
                <Button
                  type="primary"
                  icon={<Plus size={16} />}
                  onClick={() => setCredentialModalOpen(true)}
                >
                  {t("pro.credentials.storeCredential")}
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
                    {t("pro.credentials.updated", {
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
                        title: t("pro.credentials.deleteTitle", {
                          name: credential.name,
                        }),
                        content: t("pro.credentials.deleteDescription"),
                        okButtonProps: { danger: true },
                        onOk: async () => {
                          await proApi.deleteCredential(
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
                  title={t("pro.credentials.emptyTitle")}
                  description={t("pro.credentials.emptyDescription")}
                />
              )}
            </div>
          </section>
        )}
      </main>

      <Modal
        title={t("pro.runtimeForm.title")}
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
          <p className={styles.formHint}>{t("pro.runtimeForm.hint")}</p>
          <Form.Item
            label={t("pro.runtimeForm.runtimeId")}
            name="runtimeId"
            rules={[
              {
                required: true,
                message: t("pro.validation.required"),
              },
              {
                pattern: /^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$/,
                message: t("pro.validation.runtimeIdInvalid"),
              },
            ]}
          >
            <Input placeholder="research-runtime" autoFocus />
          </Form.Item>
          <Form.Item
            label={t("pro.runtimeForm.startImmediately")}
            name="autoStart"
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>
            {t("pro.runtimeForm.submit")}
          </Button>
        </Form>
      </Modal>

      <Modal
        title={t("pro.userForm.title")}
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
          <p className={styles.formHint}>{t("pro.userForm.hint")}</p>
          <Form.Item
            label={t("pro.userForm.username")}
            name="username"
            rules={[
              {
                required: true,
                message: t("pro.validation.required"),
              },
            ]}
          >
            <Input autoFocus />
          </Form.Item>
          <Form.Item
            label={t("pro.userForm.temporaryPassword")}
            name="password"
            rules={[
              {
                required: true,
                message: t("pro.validation.required"),
              },
              {
                min: 8,
                message: t("pro.validation.passwordMin"),
              },
            ]}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item label={t("pro.userForm.role")} name="role">
            <Select
              options={[
                { label: t("pro.roles.user"), value: "user" },
                { label: t("pro.roles.admin"), value: "admin" },
              ]}
            />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>
            {t("pro.userForm.submit")}
          </Button>
        </Form>
      </Modal>

      <Modal
        title={t("pro.credentialForm.title")}
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
          <p className={styles.formHint}>{t("pro.credentialForm.hint")}</p>
          <Form.Item
            label={t("pro.credentialForm.scope")}
            name="scope"
            rules={[
              {
                required: true,
                message: t("pro.validation.required"),
              },
            ]}
          >
            <Select
              options={[
                {
                  label: t("pro.credentialForm.allRuntimes"),
                  value: "tenant",
                },
                ...runtimeOptions,
              ]}
            />
          </Form.Item>
          <Form.Item
            label={t("pro.credentialForm.environmentName")}
            name="name"
            rules={[
              {
                required: true,
                message: t("pro.validation.required"),
              },
              {
                pattern: /^[A-Z][A-Z0-9_]{0,127}$/,
                message: t("pro.validation.credentialNameInvalid"),
              },
            ]}
          >
            <Input placeholder="OPENAI_API_KEY" />
          </Form.Item>
          <Form.Item
            label={t("pro.credentialForm.secretValue")}
            name="value"
            rules={[
              {
                required: true,
                message: t("pro.validation.required"),
              },
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>
            {t("pro.credentialForm.submit")}
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
