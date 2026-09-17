import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Select,
  Space,
  Switch,
  Table,
  Typography,
} from "antd";
import { request } from "@/api/request";
import { adminUsersApi, type AdminUser } from "@/api/modules/adminUsers";
import { useAuthStore } from "@/stores/authStore";
import type { CatalogModel } from "@/api/modules/modelCatalog";

interface RegisteredModel {
  id: string;
  provider_name: string;
  name: string;
  status: string;
  user_grants?: Array<{ user_id: string; username: string; enabled: boolean }>;
}
interface Impact {
  uncovered_users: Array<{ username: string }>;
  affected_defaults: Array<{
    username: string;
    agent_id: string | null;
    model: string;
  }>;
}

export default function GovernancePanel() {
  const { mode, user } = useAuthStore();
  const [status, setStatus] = useState({ enforced: false, version: 0 });
  const [loaded, setLoaded] = useState(false);
  const [models, setModels] = useState<RegisteredModel[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [preview, setPreview] = useState<CatalogModel[] | null>(null);
  const [impact, setImpact] = useState<Impact | null>(null);
  const [selectedUsers, setSelectedUsers] = useState<Record<string, string>>(
    {},
  );
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const enabled = mode === "multi_user" && user?.platform_role === "admin";
  const refresh = async () => {
    const [current, registered, people] = await Promise.all([
      request<typeof status>("/model-governance/status"),
      request<RegisteredModel[]>("/model-governance/models"),
      adminUsersApi.list(),
    ]);
    setStatus(current);
    setLoaded(true);
    setModels(registered);
    setUsers(people);
  };
  useEffect(() => {
    if (enabled) void refresh().catch((error) => setError(String(error)));
  }, [enabled]);
  if (!enabled) return null;
  const run = async (operation: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try {
      await operation();
      await refresh();
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };
  const grant = (id: string, enabled: boolean) =>
    run(() =>
      request(`/model-governance/models/${id}/users/${selectedUsers[id]}`, {
        method: "PUT",
        body: JSON.stringify({ enabled }),
      }),
    );
  return (
    <Card title="模型授权治理" style={{ marginBottom: 20 }}>
      <Space direction="vertical" style={{ width: "100%" }}>
        <Alert
          type={status.enforced ? "success" : "warning"}
          showIcon
          message={
            !loaded
              ? "正在读取治理状态"
              : status.enforced
              ? "授权治理已启用"
              : "尚未启用：当前兼容运行，不强制按授权隔离"
          }
          description="按初始化、明确用户授权、启用的顺序操作。停用模型会阻止后续使用，历史会话保留。"
        />
        {error && <Alert type="error" message={error} />}
        <Space wrap>
          <Button
            loading={busy}
            onClick={() =>
              void run(async () =>
                setPreview(
                  await request<CatalogModel[]>(
                    "/model-governance/import/preview",
                    { method: "POST" },
                  ),
                ),
              )
            }
          >
            初始化预览
          </Button>
          {preview !== null && (
            <Button
              loading={busy}
              onClick={() =>
                void run(async () => {
                  await request("/model-governance/import", { method: "POST" });
                  setPreview(null);
                })
              }
            >
              登记元数据
            </Button>
          )}
          <Button
            loading={busy}
            onClick={() =>
              void run(async () =>
                setImpact(
                  await request<Impact>(
                    "/model-governance/enforcement/preview",
                  ),
                ),
              )
            }
          >
            启用影响预览
          </Button>
        </Space>
        {preview !== null && (
          <Typography.Paragraph>
            将登记 {preview.length} 个模型：
            {preview.map((m) => `${m.provider_name}/${m.name}`).join("、")}
            。不导入密钥、不自动授权、不自动启用。
          </Typography.Paragraph>
        )}
        <Table
          rowKey="id"
          size="small"
          dataSource={models}
          pagination={{ pageSize: 5 }}
          columns={[
            {
              title: "已授权用户",
              render: (_, row) =>
                row.user_grants
                  ?.filter((grant) => grant.enabled)
                  .map((grant) => grant.username)
                  .join("、") || "无",
            },
            {
              title: "模型",
              render: (_, row) => `${row.provider_name}/${row.name}`,
            },
            {
              title: "可用",
              render: (_, row) => (
                <Switch
                  checked={row.status === "active"}
                  disabled={busy}
                  onChange={(enabled) =>
                    void run(() =>
                      request(`/model-governance/models/${row.id}/status`, {
                        method: "PATCH",
                        body: JSON.stringify({ enabled }),
                      }),
                    )
                  }
                />
              ),
            },
            {
              title: "明确用户授权",
              render: (_, row) => (
                <Space wrap>
                  <Select
                    aria-label={`授权用户-${row.id}`}
                    style={{ width: 160 }}
                    value={selectedUsers[row.id]}
                    options={users
                      .filter(
                        (u) =>
                          u.status === "active" && u.platform_role === "member",
                      )
                      .map((u) => ({ value: u.id, label: u.username }))}
                    onChange={(id) =>
                      setSelectedUsers({ ...selectedUsers, [row.id]: id })
                    }
                  />
                  <Button
                    disabled={!selectedUsers[row.id] || busy}
                    onClick={() => void grant(row.id, true)}
                  >
                    授权
                  </Button>
                  <Button
                    disabled={!selectedUsers[row.id] || busy}
                    onClick={() => void grant(row.id, false)}
                  >
                    撤销
                  </Button>
                </Space>
              ),
            },
          ]}
        />
        {impact && (
          <>
            <Alert
              type="warning"
              message={`无直接可用授权用户：${
                impact.uncovered_users.map((u) => u.username).join("、") || "无"
              }`}
              description={`可能无法使用默认模型：${
                impact.affected_defaults
                  .map(
                    (item) =>
                      `${item.username} / ${item.agent_id || "平台"} / ${
                        item.model
                      }`,
                  )
                  .join("；") || "无"
              }。Agent 专属授权仅在有真实使用权时生效。`}
            />
            <Button
              type="primary"
              loading={busy}
              onClick={() =>
                void run(async () => {
                  await request("/model-governance/enforcement", {
                    method: "PUT",
                    body: JSON.stringify({
                      enabled: !status.enforced,
                      expected_version: status.version,
                      reason: "管理员已确认影响预览",
                    }),
                  });
                  setImpact(null);
                })
              }
            >
              {status.enforced ? "明确停用治理" : "确认影响并启用治理"}
            </Button>
          </>
        )}
      </Space>
    </Card>
  );
}
