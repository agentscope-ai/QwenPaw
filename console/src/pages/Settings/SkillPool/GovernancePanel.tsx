import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Input,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from "antd";
import { useTranslation } from "react-i18next";
import { agentsApi } from "@/api/modules/agents";
import { createSkillGovernanceApi } from "@/api/modules/skillGovernance";
import { useSkillScope } from "@/api/skillScope";
import type { AdminAgentSummary } from "@/api/types/agents";
import type {
  GovernedSkill,
  SkillGrant,
  SkillPublicationRequest,
  SkillRequestDetail,
} from "@/api/types/skillGovernance";
import {
  skillErrorMessage,
  useSkillRuntime,
} from "../../Agent/Skills/useSkillRuntime";

export type GovernanceView = "published" | "requests";

export default function GovernancePanel({ view }: { view: GovernanceView }) {
  const scope = useSkillScope();
  if (!scope.multiUser || !scope.isAdmin) return null;
  return <Panel key={`${scope.key}:${view}`} view={view} />;
}

function Panel({ view }: { view: GovernanceView }) {
  const { t } = useTranslation();
  const { scope } = useSkillRuntime();
  const api = useMemo(() => createSkillGovernanceApi(scope), [scope]);
  const [items, setItems] = useState<GovernedSkill[]>([]);
  const [requests, setRequests] = useState<SkillPublicationRequest[]>([]);
  const [requestStatus, setRequestStatus] = useState("all");
  const [agents, setAgents] = useState<AdminAgentSummary[]>([]);
  const [grantItem, setGrantItem] = useState<GovernedSkill | null>(null);
  const [grants, setGrants] = useState<SkillGrant[]>([]);
  const [target, setTarget] = useState<string>();
  const [publication, setPublication] =
    useState<SkillPublicationRequest | null>(null);
  const [detail, setDetail] = useState<SkillRequestDetail | null>(null);
  const [file, setFile] = useState<{ path: string; content: string } | null>(
    null,
  );
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [error, setError] = useState("");
  const detailSequence = useRef(0);
  const fileSequence = useRef(0);
  const grantSequence = useRef(0);

  const refresh = useCallback(async () => {
    scope.assert();
    if (view === "published") {
      const [registered, targets] = await Promise.all([
        api.items(),
        agentsApi.listAdminAgents(),
      ]);
      if (!scope.current()) return;
      setItems(registered.items);
      setAgents(targets.agents);
      return;
    }
    const response = await api.requests();
    if (scope.current()) setRequests(response.requests);
  }, [api, scope, view]);

  const run = async (operation: () => Promise<unknown>, reload = true) => {
    if (!scope.current() || !scope.isAdmin || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    try {
      await operation();
      if (reload && scope.current()) await refresh();
    } catch (operationError) {
      if (scope.current()) setError(skillErrorMessage(operationError, t));
    } finally {
      if (scope.current()) {
        setBusy(false);
        busyRef.current = false;
      }
    }
  };

  useEffect(() => {
    void refresh().catch((loadError) => {
      if (scope.current()) setError(skillErrorMessage(loadError, t));
    });
  }, [refresh, scope, t]);

  const openGrants = async (item: GovernedSkill) => {
    const sequence = ++grantSequence.current;
    setGrantItem(item);
    setGrants([]);
    setTarget(undefined);
    try {
      const response = await api.grants(item.id);
      if (scope.current() && sequence === grantSequence.current)
        setGrants(response.grants);
    } catch (loadError) {
      if (scope.current() && sequence === grantSequence.current)
        setError(skillErrorMessage(loadError, t));
    }
  };

  const setGrant = (agentId: string, enabled: boolean) => {
    if (!grantItem) return;
    const id = grantItem.id;
    const sequence = grantSequence.current;
    void run(async () => {
      await api.grant(id, agentId, enabled);
      scope.assert();
      const response = await api.grants(id);
      if (sequence === grantSequence.current) setGrants(response.grants);
    });
  };

  const openRequest = async (row: SkillPublicationRequest) => {
    const sequence = ++detailSequence.current;
    fileSequence.current++;
    setPublication(row);
    setDetail(null);
    setFile(null);
    setNote("");
    setError("");
    if (!row.content_hash) return;
    try {
      const response = await api.detail(row.id);
      if (scope.current() && sequence === detailSequence.current)
        setDetail(response);
    } catch (loadError) {
      if (scope.current() && sequence === detailSequence.current)
        setError(skillErrorMessage(loadError, t));
    }
  };

  const closeRequest = () => {
    detailSequence.current++;
    fileSequence.current++;
    setPublication(null);
    setDetail(null);
    setFile(null);
  };

  const readFile = async (path: string) => {
    if (!detail) return;
    const sequence = ++fileSequence.current;
    setFile(null);
    try {
      const response = await api.file(detail.id, path);
      if (scope.current() && sequence === fileSequence.current)
        setFile({ path, content: response.content });
    } catch (loadError) {
      if (scope.current() && sequence === fileSequence.current)
        setError(skillErrorMessage(loadError, t));
    }
  };

  const review = (decision: "approve" | "reject") => {
    if (
      !publication ||
      (decision === "approve" &&
        (!detail?.content_hash || !detail.files.length))
    )
      return;
    const row = publication;
    const version = detail?.review_version ?? row.review_version;
    void run(async () => {
      try {
        await api.review(row.id, decision, version, note);
        scope.assert();
        closeRequest();
      } catch (reviewError) {
        if (!scope.current()) return;
        await refresh();
        if (row.content_hash) {
          const latest = await api.detail(row.id);
          scope.assert();
          setDetail(latest);
        }
        throw reviewError;
      }
    });
  };

  const filteredRequests = useMemo(
    () =>
      requestStatus === "all"
        ? requests
        : requests.filter((row) => row.status === requestStatus),
    [requestStatus, requests],
  );
  const requestIsPending =
    (detail?.status ?? publication?.status) === "pending";
  const errorAlert = error && <Alert type="error" showIcon message={error} />;

  if (view === "published") {
    return (
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        <Alert
          type="info"
          showIcon
          message={t("skillGovernance.publishedDescription")}
        />
        {errorAlert}
        <Button disabled={busy} onClick={() => void run(refresh, false)}>
          {t("common.refresh")}
        </Button>
        <Table
          rowKey="id"
          dataSource={items}
          pagination={{ pageSize: 10 }}
          scroll={{ x: true }}
          columns={[
            { title: t("skills.skillName"), dataIndex: "name" },
            {
              title: t("skillGovernance.sourceVersion", { version: "" }),
              dataIndex: "version",
            },
            {
              title: t("skillGovernance.hash"),
              dataIndex: "content_hash",
              render: (value) => (
                <Typography.Text code>{value}</Typography.Text>
              ),
            },
            {
              title: t("skillGovernance.active"),
              render: (_, row) => (
                <Switch
                  aria-label={`${row.name} ${t("skillGovernance.active")}`}
                  checked={row.status === "active"}
                  disabled={busy}
                  onChange={(enabled) =>
                    void run(() => api.setStatus(row.id, enabled))
                  }
                />
              ),
            },
            {
              title: t("common.actions"),
              render: (_, row) => (
                <Button disabled={busy} onClick={() => void openGrants(row)}>
                  {t("skillGovernance.grants")}
                </Button>
              ),
            },
          ]}
        />
        {grantItem && (
          <Card
            size="small"
            title={`${grantItem.name} · ${t("skillGovernance.grants")}`}
          >
            <Space wrap>
              <Select
                aria-label={t("skillGovernance.selectAgent")}
                placeholder={t("skillGovernance.selectAgent")}
                style={{ minWidth: 240 }}
                value={target}
                onChange={setTarget}
                disabled={busy}
                options={agents.map((agent) => ({
                  value: agent.id,
                  label: agent.name || agent.id,
                }))}
              />
              <Button
                disabled={busy || !target}
                onClick={() => target && setGrant(target, true)}
              >
                {t("skillGovernance.grant")}
              </Button>
            </Space>
            {grants.map((grant) => (
              <div key={grant.agent_database_id}>
                <span>
                  {grant.agent_id ?? t("skillGovernance.missingAgent")}
                </span>
                {" · "}
                <span>
                  {grant.enabled ? t("common.enabled") : t("common.disabled")}
                </span>{" "}
                <Button
                  disabled={busy || !grant.agent_id}
                  onClick={() =>
                    grant.agent_id && setGrant(grant.agent_id, !grant.enabled)
                  }
                >
                  {t(
                    grant.enabled
                      ? "skillGovernance.revoke"
                      : "skillGovernance.grant",
                  )}
                </Button>
              </div>
            ))}
          </Card>
        )}
      </Space>
    );
  }

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="middle">
      <Alert
        type="info"
        showIcon
        message={t("skillGovernance.requestsDescription")}
      />
      {errorAlert}
      <Space wrap>
        <Button disabled={busy} onClick={() => void run(refresh, false)}>
          {t("common.refresh")}
        </Button>
        <Select
          aria-label={t("skillGovernance.requestStatus")}
          value={requestStatus}
          onChange={setRequestStatus}
          style={{ minWidth: 160 }}
          options={[
            { value: "all", label: t("skillGovernance.statusAll") },
            { value: "pending", label: t("skillGovernance.statusPending") },
            { value: "approved", label: t("skillGovernance.statusApproved") },
            { value: "rejected", label: t("skillGovernance.statusRejected") },
          ]}
        />
      </Space>
      <Table
        rowKey="id"
        dataSource={filteredRequests}
        pagination={{ pageSize: 10 }}
        scroll={{ x: true }}
        columns={[
          { title: t("skills.skillName"), dataIndex: "skill_name" },
          {
            title: t("skillGovernance.applicant"),
            render: (_, row) => row.applicant_name || row.submitted_by,
          },
          {
            title: t("skillGovernance.requestAgent"),
            render: (_, row) => row.agent_name || "—",
          },
          {
            title: t("skillGovernance.requestStatus"),
            dataIndex: "status",
            render: (status) => {
              const key = String(status);
              const color =
                key === "pending"
                  ? "processing"
                  : key === "approved"
                  ? "success"
                  : "error";
              const labelKey =
                key === "pending"
                  ? "statusPending"
                  : key === "approved"
                  ? "statusApproved"
                  : "statusRejected";
              return (
                <Tag color={color}>{t(`skillGovernance.${labelKey}`)}</Tag>
              );
            },
          },
          {
            title: t("skillGovernance.reviewVersion"),
            dataIndex: "review_version",
          },
          {
            title: t("common.actions"),
            render: (_, row) => (
              <Button disabled={busy} onClick={() => void openRequest(row)}>
                {t(
                  row.status === "pending"
                    ? "skillGovernance.reviewAction"
                    : "skillGovernance.viewDetails",
                )}
              </Button>
            ),
          },
        ]}
      />
      <Modal
        open={!!publication}
        title={publication?.skill_name}
        width={760}
        destroyOnHidden
        onCancel={closeRequest}
        footer={
          requestIsPending ? (
            <Space>
              <Button
                disabled={busy || (!!publication?.content_hash && !detail)}
                onClick={() => review("reject")}
              >
                {t("skillGovernance.reject")}
              </Button>
              <Button
                type="primary"
                disabled={busy || !detail?.content_hash || !detail.files.length}
                onClick={() => review("approve")}
              >
                {t("skillGovernance.approve")}
              </Button>
            </Space>
          ) : (
            <Button onClick={closeRequest}>{t("common.close")}</Button>
          )
        }
      >
        {errorAlert}
        <p>
          {t("skillGovernance.applicant")}:{" "}
          {publication?.applicant_name || publication?.submitted_by || "—"}
        </p>
        <p>
          {t("skillGovernance.requestAgent")}: {publication?.agent_name || "—"}
        </p>
        <p>
          {t("skillGovernance.reviewVersion")}:{" "}
          {detail?.review_version ?? publication?.review_version}
        </p>
        <Typography.Text code>
          {detail?.content_hash ?? publication?.content_hash ?? "—"}
        </Typography.Text>
        {!publication?.content_hash && (
          <Alert type="warning" message={t("skillGovernance.noSnapshot")} />
        )}
        <p>{t("skillGovernance.files")}</p>
        <Space wrap>
          {detail?.files.map((path) => (
            <Button
              key={path}
              disabled={busy}
              onClick={() => void readFile(path)}
            >
              {path}
            </Button>
          ))}
        </Space>
        {file && (
          <pre
            style={{ maxHeight: 320, overflow: "auto", whiteSpace: "pre-wrap" }}
          >
            {file.content}
          </pre>
        )}
        {requestIsPending ? (
          <Input.TextArea
            aria-label={t("skillGovernance.note")}
            placeholder={t("skillGovernance.note")}
            maxLength={4000}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            disabled={busy}
          />
        ) : (
          <Space direction="vertical">
            <span>
              {t("skillGovernance.reviewer")}: {publication?.reviewed_by ?? "—"}
            </span>
            <span>
              {t("skillGovernance.reviewedAt")}:{" "}
              {publication?.reviewed_at ?? "—"}
            </span>
            <span>
              {t("skillGovernance.note")}: {publication?.review_note ?? "—"}
            </span>
          </Space>
        )}
      </Modal>
    </Space>
  );
}
