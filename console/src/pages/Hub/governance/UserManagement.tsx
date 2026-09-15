import { useCallback, useEffect, useState, useRef } from "react";
import {
  App,
  Button,
  Modal,
  Input,
  Pagination,
  Progress,
  Select,
  Skeleton,
  Switch,
  Tabs,
  Tag,
} from "antd";
import { ArrowUpRight, Search, UserPlus, Users, X } from "lucide-react";
import {
  hubApi,
  type HubUser,
  type HubRuntime,
} from "../../../api/modules/hub";
import {
  governanceRequest as request,
  type UsageReport,
  type ManagedModel,
} from "../../../api/modules/hubGovernance";
import Invitations from "./Invitations";
import PasswordReset from "./PasswordReset";
import BudgetEditor from "./BudgetEditor";
import { budgetMode, budgetLimit, type BudgetMode } from "./budgetUtils";
import { formatTokens } from "./budgetUtils";
import { editable, useGovernanceText } from "./shared";
import styles from "./governance.module.less";

type Props = {
  initialUser?: string;
  users: HubUser[];
  me: HubUser;
  total: number;
  page: number;
  pageSize: number;
  query: string;
  onQuery: (value: string) => void;
  role?: string;
  onRole: (value: string | undefined) => void;
  state?: string;
  onState: (value: string | undefined) => void;
  onPage: (page: number) => Promise<void>;
  onCreate: () => void;
  onUpdate: (
    user: HubUser,
    values: { role?: HubUser["role"]; disabled?: boolean },
  ) => Promise<void>;
};
export default function UserManagement(props: Props) {
  const text = useGovernanceText();
  const { message } = App.useApp();
  const [report, setReport] = useState<UsageReport>();
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string>();
  const [models, setModels] = useState<ManagedModel[]>([]);
  const [runtime, setRuntime] = useState<HubRuntime[]>([]);
  const [mode, setMode] = useState<BudgetMode>("inherit");
  const [amount, setAmount] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState("members");
  const load = useCallback(async () => {
    try {
      const r = await request<UsageReport>("admin/usage");
      setReport(r);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load, props.users]);
  const user = props.users.find((u) => u.user_id === selected);
  const usage = report?.members.find((u) => u.user_id === selected);
  const open = async (u: HubUser) => {
    const current = report?.members.find((m) => m.user_id === u.user_id);
    setSelected(u.user_id);
    setMode(
      budgetMode(
        current?.token_limit ?? null,
        current?.inherits_budget ?? true,
      ),
    );
    setAmount(current?.token_limit ?? null);
    setModels([]);
    setRuntime([]);
    setBusy(true);
    try {
      const [m, r] = await Promise.all([
        request<ManagedModel[]>("admin/models"),
        hubApi.listRuntimes({ owner: u.username, page: 1, pageSize: 100 }),
      ]);
      setModels(m);
      setRuntime(r.items);
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const openedInitial = useRef<string>();
  useEffect(() => {
    if (
      !props.initialUser ||
      openedInitial.current === props.initialUser ||
      !report
    )
      return;
    const found = props.users.find((u) => u.username === props.initialUser);
    if (found) {
      openedInitial.current = props.initialUser;
      void open(found);
    }
  });
  const saveBudget = async () => {
    if (!user) return;
    if (mode === "limited" && !amount) {
      message.error(
        text("请输入大于 0 的额度", "Enter a limit greater than zero"),
      );
      return;
    }
    setBusy(true);
    try {
      await request(`admin/budgets/${user.user_id}`, "PUT", {
        inherit: mode === "inherit",
        token_limit: budgetLimit(mode, amount),
      });
      await load();
      message.success(text("成员额度已保存", "Member budget saved"));
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const grant = async (model: ManagedModel, enabled: boolean) => {
    if (!user) return;
    setBusy(true);
    try {
      await request(`admin/models/${model.id}`, "PUT", {
        ...editable(model),
        revision: model.revision,
        user_ids: enabled
          ? [...new Set([...model.user_ids, user.user_id])]
          : model.user_ids.filter((id) => id !== user.user_id),
      });
      setModels(await request<ManagedModel[]>("admin/models"));
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className={styles.panel}>
      <div className={styles.heading}>
        <div>
          <span className={styles.eyebrow}>
            {text("团队管理", "WORKSPACE")}
          </span>
          <h2>{text("用户", "Users")}</h2>
          <p>
            {text(
              "在一个地方管理账号、模型权限和使用额度。",
              "Manage accounts, model access and individual budgets in one place.",
            )}
          </p>
        </div>
        {tab === "members" && (
          <Button
            type="primary"
            icon={<UserPlus size={15} />}
            onClick={props.onCreate}
          >
            {text("创建用户", "Create user")}
          </Button>
        )}
      </div>
      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: "members",
            label: text("成员", "Members"),
            children: (
              <>
                <div className={styles.tablePanel}>
                  <div className={styles.toolbar}>
                    <Input
                      prefix={<Search size={15} />}
                      value={props.query}
                      allowClear
                      placeholder={text("搜索用户", "Search users")}
                      onChange={(e) => props.onQuery(e.target.value)}
                    />
                    <Select
                      allowClear
                      placeholder={text("所有角色", "All roles")}
                      value={props.role}
                      onChange={props.onRole}
                      options={[
                        { value: "admin", label: text("管理员", "Admin") },
                        { value: "user", label: text("成员", "Member") },
                      ]}
                    />
                    <Select
                      allowClear
                      placeholder={text("所有状态", "All states")}
                      value={props.state}
                      onChange={props.onState}
                      options={[
                        { value: "active", label: text("正常", "Active") },
                        {
                          value: "disabled",
                          label: text("已停用", "Disabled"),
                        },
                      ]}
                    />
                  </div>
                  {error && (
                    <div role="alert" className={styles.notice}>
                      {error}
                      <Button onClick={load}>{text("重试", "Retry")}</Button>
                    </div>
                  )}
                  <div className={styles.userList}>
                    <div className={styles.userHead}>
                      <span>{text("用户", "User")}</span>
                      <span>{text("账号状态", "Account status")}</span>
                      <span>{text("本月用量", "Monthly usage")}</span>
                      <span>{text("月额度", "Monthly limit")}</span>
                      <span />
                    </div>
                    {props.users.map((u) => {
                      const m = report?.members.find(
                        (item) => item.user_id === u.user_id,
                      );
                      return (
                        <button
                          key={u.user_id}
                          className={styles.userRow}
                          onClick={() => open(u)}
                        >
                          <span className={styles.identity}>
                            <span className={styles.avatar}>
                              {u.username.slice(0, 1).toUpperCase()}
                            </span>
                            <span>
                              <strong>{u.username}</strong>
                              <small>
                                {u.role === "admin"
                                  ? text("管理员", "Admin")
                                  : text("成员", "Member")}
                                {u.user_id === props.me.user_id
                                  ? text(" · 你", " · You")
                                  : ""}
                              </small>
                            </span>
                          </span>
                          <span>
                            <Tag
                              bordered={false}
                              color={u.disabled ? "default" : "success"}
                            >
                              {u.disabled
                                ? text("已停用", "Disabled")
                                : text("正常", "Active")}
                            </Tag>
                            <small className={styles.runtimeState}>
                              {m?.runtime_states?.length
                                ? m.runtime_states.some(
                                    (state) => state === "running",
                                  )
                                  ? text("实例运行中", "Instance running")
                                  : text("实例未运行", "Instance stopped")
                                : text("暂无实例", "No instance")}
                            </small>
                          </span>
                          <span className={styles.cellValue}>
                            <small>{text("本月用量", "Monthly usage")}</small>
                            {m ? `${formatTokens(m.charged)} Token` : "—"}
                          </span>
                          <span className={styles.cellValue}>
                            <small>{text("月额度", "Monthly limit")}</small>
                            {m
                              ? m.token_limit === null
                                ? text("不限额", "Unlimited")
                                : m.token_limit === 0
                                ? text("暂停调用", "Paused")
                                : formatTokens(m.token_limit)
                              : "—"}
                            {m?.inherits_budget && (
                              <em>{text("继承默认", "Default")}</em>
                            )}
                          </span>
                          <ArrowUpRight size={15} />
                        </button>
                      );
                    })}
                  </div>
                  {!props.users.length && (
                    <div className={styles.empty}>
                      <Users size={28} />
                      <strong>
                        {text("没有匹配的用户", "No matching users")}
                      </strong>
                      <p>
                        {text(
                          "尝试调整筛选条件，或创建新用户。",
                          "Adjust your filters or create a user.",
                        )}
                      </p>
                    </div>
                  )}
                  <div className={styles.tableFooter}>
                    <span>
                      {props.total} {text("位用户", "users")}
                    </span>
                    <Pagination
                      size="small"
                      current={props.page}
                      pageSize={props.pageSize}
                      total={props.total}
                      showSizeChanger={false}
                      onChange={props.onPage}
                    />
                  </div>
                </div>
              </>
            ),
          },
          {
            key: "invitations",
            label: text("邀请码", "Invitations"),
            children: <Invitations />,
          },
        ]}
      />
      <Modal
        width={760}
        centered
        footer={null}
        open={!!user}
        onCancel={() => setSelected(undefined)}
        title={user?.username}
        closeIcon={<X size={18} />}
        className={styles.userModal}
      >
        {user && (
          <Tabs
            items={[
              {
                key: "usage",
                label: text("用量与额度", "Usage & budget"),
                children: (
                  <div className={styles.panel}>
                    {usage ? (
                      <div className={styles.card}>
                        <span className={styles.muted}>
                          {usage.period} · {text("已使用", "Used")}
                        </span>
                        <strong className={styles.metric}>
                          {formatTokens(usage.charged)} <small>Token</small>
                        </strong>
                        {usage.token_limit !== null &&
                          usage.token_limit > 0 && (
                            <Progress
                              status={
                                usage.remaining === 0 ? "exception" : "normal"
                              }
                              percent={Math.min(
                                100,
                                Math.round(
                                  ((usage.charged + usage.reserved) /
                                    usage.token_limit) *
                                    100,
                                ),
                              )}
                              strokeColor="var(--app-accent)"
                            />
                          )}
                        <div className={styles.detailRow}>
                          <span>{text("处理中预留", "Reserved")}</span>
                          <strong>{formatTokens(usage.reserved)}</strong>
                        </div>
                      </div>
                    ) : (
                      <Skeleton active />
                    )}
                    <div className={styles.card}>
                      <h3>{text("每月额度", "Monthly limit")}</h3>
                      <BudgetEditor
                        mode={mode}
                        amount={amount}
                        onMode={setMode}
                        onAmount={setAmount}
                        allowInherit
                      />
                      <Button
                        type="primary"
                        loading={busy}
                        onClick={saveBudget}
                      >
                        {text("保存额度", "Save limit")}
                      </Button>
                    </div>
                    <details className={styles.help}>
                      <summary>
                        {text("用量如何计算？", "How is usage calculated?")}
                      </summary>
                      <p>
                        {text(
                          "处理中调用会暂时预留额度。供应商未返回用量的调用按预留量计入，避免漏计。",
                          "Active requests temporarily reserve tokens. If the provider omits usage, the reserved amount is charged.",
                        )}
                      </p>
                    </details>
                  </div>
                ),
              },
              {
                key: "models",
                label: text("模型权限", "Model access"),
                children: (
                  <div className={styles.panel}>
                    <p className={styles.muted}>
                      {text(
                        "全体成员可用的模型自动授予访问权限。",
                        "Models available to all members are automatically granted.",
                      )}
                    </p>
                    {models.map((m) => (
                      <div className={styles.accessRow} key={m.id}>
                        <div>
                          <strong>{m.name}</strong>
                          <small>
                            {m.all_members
                              ? text("全体成员", "All members")
                              : text("单独授权", "Individual grant")}
                            {!m.enabled ? text(" · 已停用", " · Disabled") : ""}
                          </small>
                        </div>
                        <Switch
                          aria-label={m.name}
                          checked={
                            m.all_members || m.user_ids.includes(user.user_id)
                          }
                          disabled={m.all_members || busy}
                          onChange={(v) => grant(m, v)}
                        />
                      </div>
                    ))}
                    {!models.length && !busy && (
                      <p>{text("尚未配置模型", "No models configured")}</p>
                    )}
                  </div>
                ),
              },
              {
                key: "account",
                label: text("账号", "Account"),
                children: (
                  <div className={styles.panel}>
                    <div className={styles.card}>
                      <h3>{text("账号设置", "Account settings")}</h3>
                      <div className={styles.field}>
                        <label>{text("角色", "Role")}</label>
                        <Select
                          value={user.role}
                          disabled={user.user_id === props.me.user_id}
                          onChange={(role) => props.onUpdate(user, { role })}
                          options={[
                            { value: "admin", label: text("管理员", "Admin") },
                            { value: "user", label: text("成员", "Member") },
                          ]}
                        />
                      </div>
                      <div className={styles.accessRow}>
                        <span>{text("启用账号", "Account enabled")}</span>
                        <Switch
                          checked={!user.disabled}
                          disabled={user.user_id === props.me.user_id}
                          onChange={(v) =>
                            props.onUpdate(user, { disabled: !v })
                          }
                        />
                      </div>
                      <PasswordReset user={user} />
                    </div>
                    <div className={styles.card}>
                      <h3>{text("运行实例", "Instances")}</h3>
                      {runtime.map((r) => (
                        <div className={styles.detailRow} key={r.runtime_id}>
                          <span>{r.runtime_id}</span>
                          <Tag>{r.state}</Tag>
                        </div>
                      ))}
                      {!runtime.length && (
                        <p>{text("暂无实例", "No instances")}</p>
                      )}
                    </div>
                  </div>
                ),
              },
            ]}
          />
        )}
      </Modal>
    </section>
  );
}
