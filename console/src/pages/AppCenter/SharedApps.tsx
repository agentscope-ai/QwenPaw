import { useEffect, useState } from "react";
import { Button, Card, Empty, Space, Spin, Typography, message } from "antd";
import { useNavigate } from "react-router-dom";
import { sharedAppsApi, type SharedAppPublication } from "@/api/modules/sharedApps";
import { useAgentStore } from "@/stores/agentStore";

export function SharedApps() {
  const [items, setItems] = useState<SharedAppPublication[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();
  const setSelectedAgent = useAgentStore((state) => state.setSelectedAgent);
  useEffect(() => { void sharedAppsApi.catalog().then((v) => setItems(v.items)).catch((e) => message.error(String(e))).finally(() => setLoading(false)); }, []);
  if (loading) return <Spin />;
  if (!items.length) return <Empty description="暂无可用共享应用" />;
  return <Space direction="vertical" style={{ width: "100%" }}>
    {items.map((item) => <Card key={item.id} title={item.immutable_manifest.display?.name || "共享应用"}>
      <Typography.Paragraph>{item.immutable_manifest.display?.description}</Typography.Paragraph>
      <Typography.Text>版本 {item.version} · 模型 {item.immutable_manifest.model?.provider_id}/{item.immutable_manifest.model?.model}</Typography.Text>
      <div style={{ marginTop: 16 }}><Button type="primary" onClick={async () => {
        const result = await sharedAppsApi.start(item.shared_app_id);
        setSelectedAgent(result.agent_id);
        navigate(`/chat/${result.conversation_id}`);
      }}>开始使用</Button></div>
    </Card>)}
  </Space>;
}
