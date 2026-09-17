import { useEffect, useState } from "react";
import { Button, Card, Empty, Form, Input, Space, Tag, message } from "antd";
import { sharedAppsApi, type SharedAppRecord, type SharedAppPublication } from "@/api/modules/sharedApps";
import { useAgentStore } from "@/stores/agentStore";

export function MyPublications() {
  const [apps, setApps] = useState<SharedAppRecord[]>([]);
  const [publications, setPublications] = useState<Record<string, SharedAppPublication[]>>({});
  const selectedAgent = useAgentStore((state) => state.selectedAgent);
  const selectedAgentRecord = useAgentStore((state) =>
    state.agents.find((agent) => agent.id === state.selectedAgent),
  );
  const canCreate = Boolean(
    selectedAgent && selectedAgentRecord?.access_role === "owner",
  );
  const load = async () => { const result = await sharedAppsApi.mine(); setApps(result.items); await Promise.all(result.items.map(async (app) => { const rows = await sharedAppsApi.publications(app.id); setPublications((old) => ({ ...old, [app.id]: rows.items })); })); };
  useEffect(() => { void load().catch((e) => message.error(String(e))); }, []);
  const createCurrent = async () => {
    if (!selectedAgent) return;
    await sharedAppsApi.create(selectedAgent);
    await load();
    message.success("已为当前 Agent 创建共享应用草稿");
  };
  return <Space direction="vertical" style={{ width: "100%" }}>
    <Space>
      <Button type="primary" disabled={!canCreate} onClick={() => void createCurrent().catch((e) => message.error(String(e)))}>
        为当前 Agent 创建共享应用
      </Button>
      <span>{selectedAgentRecord ? `当前 Agent：${selectedAgentRecord.name}` : "请先选择 Agent"}</span>
    </Space>
    {!apps.length ? <Empty description={canCreate ? "尚未创建共享应用" : "仅 Agent 所有者可以创建共享应用"} /> : apps.map((app) => <Card key={app.id} title={`共享应用 ${app.id.slice(0, 8)}`} extra={<Tag>{app.status}</Tag>}>
    <Form layout="inline" onFinish={async (v) => { const draft = await sharedAppsApi.saveDraft(app.id, { display: { name: v.name, description: v.description } }); await sharedAppsApi.submit(app.id, draft.revision); await load(); message.success("已提交审核"); }}>
      <Form.Item name="name" rules={[{ required: true }]}><Input placeholder="应用名称" /></Form.Item>
      <Form.Item name="description"><Input placeholder="应用说明" /></Form.Item>
      <Button htmlType="submit" type="primary">保存并提交</Button>
    </Form>
    <Space wrap style={{ marginTop: 16 }}>{(publications[app.id] || []).map((p) => <Tag key={p.id} color={p.review_status === "rejected" ? "red" : p.review_status === "approved" ? "green" : "blue"}>{p.version} {p.review_status}{p.review_note ? `：${p.review_note}` : ""}</Tag>)}</Space>
  </Card>)}</Space>;
}
