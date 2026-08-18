import { useCallback, useEffect, useMemo, useState } from "react";
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
      message.error(error instanceof Error ? error.message : "Action failed");
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
      message.success("Runtime created");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "Create failed");
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
      message.success("Account created");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "Create failed");
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
      message.error(error instanceof Error ? error.message : "Update failed");
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
      message.success("Credential stored");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "Save failed");
    }
  };

  const logout = () => {
    clearAuthToken();
    window.location.assign("/login");
  };

  const navigation = [
    { id: "runtimes" as const, label: "Runtimes", icon: Server },
    ...(me?.role === "admin"
      ? [{ id: "users" as const, label: "Users", icon: Users }]
      : []),
    { id: "credentials" as const, label: "Credentials", icon: KeyRound },
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
            <strong>Pro administration</strong>
            <span>Local workspace</span>
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
            <span>Back to QwenPaw</span>
          </button>
          <div className={styles.account}>
            <div className={styles.avatarSmall}>
              {(me?.username || "Q").slice(0, 1).toUpperCase()}
            </div>
            <div>
              <strong>{me?.username || "Loading"}</strong>
              <span>{me?.role || ""}</span>
            </div>
            <button
              type="button"
              onClick={toggleTheme}
              aria-label={isDark ? "Use light theme" : "Use dark theme"}
            >
              {isDark ? <Sun size={16} /> : <Moon size={16} />}
            </button>
            <button type="button" onClick={logout} aria-label="Sign out">
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>

      <main className={styles.main}>
        {section === "runtimes" && (
          <section>
            <PageHeader
              eyebrow="Pro administration"
              title="Runtime overview"
              description="Manage isolated QwenPaw processes without leaving the local app. Every runtime has its own workspace and credential boundary."
              action={
                <Button
                  type="primary"
                  icon={<Plus size={16} />}
                  onClick={() => setRuntimeModalOpen(true)}
                >
                  New runtime
                </Button>
              }
            />
            <div className={styles.metrics}>
              <Metric
                icon={<Server size={18} />}
                label="Managed runtimes"
                value={String(runtimes.length)}
                detail="Local process boundaries"
              />
              <Metric
                icon={<Activity size={18} />}
                label="Running now"
                value={String(runningCount)}
                detail={
                  failedCount > 0
                    ? `${failedCount} runtime needs attention`
                    : "All observed states are healthy"
                }
                warning={failedCount > 0}
              />
              <Metric
                icon={<ShieldCheck size={18} />}
                label="Isolation policy"
                value="Fail closed"
                detail="No unsandboxed fallback"
              />
            </div>
            <div className={styles.notice}>
              <ShieldCheck size={18} />
              <div>
                <strong>Fail-closed local isolation</strong>
                <span>
                  The entire runtime process tree is sandboxed. If the native
                  isolation probe fails, QwenPaw refuses to start it.
                </span>
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
                      <span>Local endpoint · {runtime.endpoint}</span>
                    </div>
                    <Tag color={STATE_COLORS[runtime.state]}>
                      {runtime.state}
                    </Tag>
                  </div>
                  <dl className={styles.details}>
                    <div>
                      <dt>Driver</dt>
                      <dd>{runtime.driver}</dd>
                    </div>
                    <div>
                      <dt>Security</dt>
                      <dd>{runtime.security_level}</dd>
                    </div>
                    <div>
                      <dt>Tenant</dt>
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
                        Stop
                      </Button>
                    ) : (
                      <Button
                        icon={<Play size={15} />}
                        loading={busyId === runtime.runtime_id}
                        onClick={() =>
                          runRuntimeAction(runtime.runtime_id, "start")
                        }
                      >
                        Start
                      </Button>
                    )}
                    <Button
                      danger
                      disabled={runtime.state === "running"}
                      icon={<Trash2 size={15} />}
                      onClick={() =>
                        modal.confirm({
                          title: `Remove ${runtime.runtime_id}?`,
                          content:
                            "Registration is removed; runtime data is retained.",
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
                  title="No runtimes yet"
                  description="Create the first isolated local QwenPaw runtime."
                />
              )}
            </div>
          </section>
        )}

        {section === "users" && me?.role === "admin" && (
          <section>
            <PageHeader
              eyebrow="Identity and access"
              title="User access"
              description="Create local accounts, assign administrative access and revoke sessions from one place."
              action={
                <Button
                  type="primary"
                  icon={<Plus size={16} />}
                  onClick={() => setUserModalOpen(true)}
                >
                  Add account
                </Button>
              }
            />
            <div className={styles.settingRow}>
              <div>
                <strong>Public registration</strong>
                <span>
                  When disabled, only administrators can create accounts.
                </span>
              </div>
              <Switch
                checked={registrationEnabled}
                onChange={async (enabled) => {
                  try {
                    await proApi.setRegistration(enabled);
                    setRegistrationEnabled(enabled);
                  } catch (error) {
                    message.error(
                      error instanceof Error ? error.message : "Update failed",
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
                      { label: "Administrator", value: "admin" },
                      { label: "User", value: "user" },
                    ]}
                    onChange={(role) => updateUser(user, { role })}
                  />
                  <div className={styles.userStatus}>
                    <span>{user.disabled ? "Disabled" : "Active"}</span>
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
              eyebrow="Tenant-scoped vault"
              title="Credentials"
              description="Store provider keys inside an explicit tenant or runtime scope. Secret values are encrypted and never returned by the API."
              action={
                <Button
                  type="primary"
                  icon={<Plus size={16} />}
                  onClick={() => setCredentialModalOpen(true)}
                >
                  Store credential
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
                    Updated {new Date(credential.updated_at).toLocaleString()}
                  </span>
                  <Button
                    danger
                    icon={<Trash2 size={15} />}
                    onClick={() =>
                      modal.confirm({
                        title: `Delete ${credential.name}?`,
                        content:
                          "Runtimes using this credential may stop working.",
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
                  title="Vault is empty"
                  description="Store a tenant or runtime-scoped API key."
                />
              )}
            </div>
          </section>
        )}
      </main>

      <Modal
        title="Create runtime"
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
          <p className={styles.formHint}>
            The runtime starts inside the native local sandbox. Its files,
            secrets and process tree stay separate from other users.
          </p>
          <Form.Item
            label="Runtime ID"
            name="runtimeId"
            rules={[
              { required: true },
              { pattern: /^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$/ },
            ]}
          >
            <Input placeholder="research-runtime" autoFocus />
          </Form.Item>
          <Form.Item
            label="Start immediately"
            name="autoStart"
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>
            Create runtime
          </Button>
        </Form>
      </Modal>

      <Modal
        title="Add account"
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
          <p className={styles.formHint}>
            Use a temporary password with at least eight characters. The user
            can only access runtimes owned by their personal tenant.
          </p>
          <Form.Item
            label="Username"
            name="username"
            rules={[{ required: true }]}
          >
            <Input autoFocus />
          </Form.Item>
          <Form.Item
            label="Temporary password"
            name="password"
            rules={[{ required: true, min: 8 }]}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item label="Role" name="role">
            <Select
              options={[
                { label: "User", value: "user" },
                { label: "Administrator", value: "admin" },
              ]}
            />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>
            Create account
          </Button>
        </Form>
      </Modal>

      <Modal
        title="Store credential"
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
          <p className={styles.formHint}>
            Tenant scope applies to all of your runtimes. Runtime scope is a
            private override for one selected process.
          </p>
          <Form.Item label="Scope" name="scope" rules={[{ required: true }]}>
            <Select
              options={[
                { label: "All my runtimes", value: "tenant" },
                ...runtimeOptions,
              ]}
            />
          </Form.Item>
          <Form.Item
            label="Environment name"
            name="name"
            rules={[{ required: true }, { pattern: /^[A-Z][A-Z0-9_]{0,127}$/ }]}
          >
            <Input placeholder="OPENAI_API_KEY" />
          </Form.Item>
          <Form.Item
            label="Secret value"
            name="value"
            rules={[{ required: true }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>
            Encrypt and store
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
