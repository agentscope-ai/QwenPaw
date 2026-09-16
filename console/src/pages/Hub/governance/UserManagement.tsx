import { useTranslation } from "react-i18next";
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
import { editable } from "./shared";
import { governanceErrorMessage } from "./errors";
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
  const { t, i18n } = useTranslation();
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
      message.error(governanceErrorMessage(e, t));
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
      message.error(t("hub.governance.budget.positiveLimit"));
      return;
    }
    setBusy(true);
    try {
      await request(`admin/budgets/${user.user_id}`, "PUT", {
        inherit: mode === "inherit",
        token_limit: budgetLimit(mode, amount),
      });
      await load();
      message.success(t("hub.governance.users.budgetSaved"));
    } catch (e) {
      message.error(governanceErrorMessage(e, t));
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
      message.error(governanceErrorMessage(e, t));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className={styles.panel}>
      <div className={styles.heading}>
        <div>
          <span className={styles.eyebrow}>
            {t("hub.governance.models.eyebrow")}
          </span>
          <h2>{t("hub.navigation.users")}</h2>
          <p>{t("hub.governance.users.description")}</p>
        </div>
        {tab === "members" && (
          <Button
            type="primary"
            icon={<UserPlus size={15} />}
            onClick={props.onCreate}
          >
            {t("hub.governance.users.create")}
          </Button>
        )}
      </div>
      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: "members",
            label: t("hub.governance.users.members"),
            children: (
              <>
                <div className={styles.tablePanel}>
                  <div className={styles.toolbar}>
                    <Input
                      prefix={<Search size={15} />}
                      value={props.query}
                      allowClear
                      placeholder={t("hub.governance.users.search")}
                      onChange={(e) => props.onQuery(e.target.value)}
                    />
                    <Select
                      allowClear
                      placeholder={t("hub.table.allRoles")}
                      value={props.role}
                      onChange={props.onRole}
                      options={[
                        { value: "admin", label: t("hub.roles.admin") },
                        {
                          value: "user",
                          label: t("hub.governance.users.member"),
                        },
                      ]}
                    />
                    <Select
                      allowClear
                      placeholder={t("hub.table.allStates")}
                      value={props.state}
                      onChange={props.onState}
                      options={[
                        { value: "active", label: t("hub.userStates.active") },
                        {
                          value: "disabled",
                          label: t("common.disabled"),
                        },
                      ]}
                    />
                  </div>
                  {error && (
                    <div role="alert" className={styles.notice}>
                      {governanceErrorMessage(error, t)}
                      <Button onClick={load}>{t("common.retry")}</Button>
                    </div>
                  )}
                  <div className={styles.userList}>
                    <div className={styles.userHead}>
                      <span>{t("hub.table.user")}</span>
                      <span>{t("hub.governance.users.status")}</span>
                      <span>{t("hub.governance.users.monthlyUsage")}</span>
                      <span>{t("hub.governance.users.monthlyLimit")}</span>
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
                                  ? t("hub.roles.admin")
                                  : t("hub.governance.users.member")}
                                {u.user_id === props.me.user_id
                                  ? ` · ${t("hub.governance.users.you")}`
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
                                ? t("common.disabled")
                                : t("hub.userStates.active")}
                            </Tag>
                            <small className={styles.runtimeState}>
                              {m?.runtime_states?.length
                                ? m.runtime_states.some(
                                    (state) => state === "running",
                                  )
                                  ? t("hub.governance.users.running")
                                  : t("hub.governance.users.stopped")
                                : t("hub.governance.users.noInstance")}
                            </small>
                          </span>
                          <span className={styles.cellValue}>
                            <small>
                              {t("hub.governance.users.monthlyUsage")}
                            </small>
                            {m
                              ? `${formatTokens(
                                  m.charged,
                                  i18n.language,
                                )} Token`
                              : "—"}
                          </span>
                          <span className={styles.cellValue}>
                            <small>
                              {t("hub.governance.users.monthlyLimit")}
                            </small>
                            {m
                              ? m.token_limit === null
                                ? t("hub.governance.budget.unlimited")
                                : m.token_limit === 0
                                ? t("hub.governance.users.paused")
                                : formatTokens(m.token_limit, i18n.language)
                              : "—"}
                            {m?.inherits_budget && (
                              <em>{t("hub.governance.users.default")}</em>
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
                      <strong>{t("hub.governance.users.emptyTitle")}</strong>
                      <p>{t("hub.governance.users.emptyHint")}</p>
                    </div>
                  )}
                  <div className={styles.tableFooter}>
                    <span>
                      {t("hub.governance.users.count", { count: props.total })}
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
            label: t("hub.governance.invitations.navigation"),
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
                label: t("hub.governance.users.usageBudget"),
                children: (
                  <div className={styles.panel}>
                    {usage ? (
                      <div className={styles.card}>
                        <span className={styles.muted}>
                          {usage.period} · {t("hub.governance.users.used")}
                        </span>
                        <strong className={styles.metric}>
                          {formatTokens(usage.charged, i18n.language)}{" "}
                          <small>Token</small>
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
                          <span>{t("hub.governance.users.reserved")}</span>
                          <strong>
                            {formatTokens(usage.reserved, i18n.language)}
                          </strong>
                        </div>
                      </div>
                    ) : (
                      <Skeleton active />
                    )}
                    <div className={styles.card}>
                      <h3>{t("hub.governance.users.monthlyLimit")}</h3>
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
                        {t("hub.governance.users.saveLimit")}
                      </Button>
                    </div>
                    <details className={styles.help}>
                      <summary>
                        {t("hub.governance.users.calculationTitle")}
                      </summary>
                      <p>{t("hub.governance.users.calculationHint")}</p>
                    </details>
                  </div>
                ),
              },
              {
                key: "models",
                label: t("hub.governance.users.modelAccess"),
                children: (
                  <div className={styles.panel}>
                    <p className={styles.muted}>
                      {t("hub.governance.users.modelAccessHint")}
                    </p>
                    {models.map((m) => (
                      <div className={styles.accessRow} key={m.id}>
                        <div>
                          <strong>{m.name}</strong>
                          <small>
                            {m.all_members
                              ? t("hub.governance.models.allMembersLabel")
                              : t("hub.governance.users.individualGrant")}
                            {!m.enabled
                              ? ` · ${t("hub.governance.users.disabled")}`
                              : ""}
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
                      <p>{t("hub.governance.users.noModels")}</p>
                    )}
                  </div>
                ),
              },
              {
                key: "account",
                label: t("hub.governance.users.account"),
                children: (
                  <div className={styles.panel}>
                    <div className={styles.card}>
                      <h3>{t("hub.governance.users.accountSettings")}</h3>
                      <div className={styles.field}>
                        <label>{t("hub.table.role")}</label>
                        <Select
                          value={user.role}
                          disabled={user.user_id === props.me.user_id}
                          onChange={(role) => props.onUpdate(user, { role })}
                          options={[
                            { value: "admin", label: t("hub.roles.admin") },
                            {
                              value: "user",
                              label: t("hub.governance.users.member"),
                            },
                          ]}
                        />
                      </div>
                      <div className={styles.accessRow}>
                        <span>{t("hub.governance.users.enabled")}</span>
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
                      <h3>{t("hub.governance.users.instances")}</h3>
                      {runtime.map((r) => (
                        <div className={styles.detailRow} key={r.runtime_id}>
                          <span>{r.runtime_id}</span>
                          <Tag>{r.state}</Tag>
                        </div>
                      ))}
                      {!runtime.length && (
                        <p>{t("hub.governance.users.noInstances")}</p>
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
