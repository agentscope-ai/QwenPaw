import { useEffect, useState } from "react";
import { Button, Card, Input, Space, Table, message } from "antd";
import { sharedAppsApi, type SharedAppPublication } from "@/api/modules/sharedApps";

export default function PublicationsAdminPage() {
  const [items, setItems] = useState<SharedAppPublication[]>([]);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const load = () => sharedAppsApi.pending().then((v) => setItems(v.items));
  useEffect(() => { void load().catch((e) => message.error(String(e))); }, []);
  return <Card title="共享应用发布审核"><Table rowKey="id" dataSource={items} columns={[
    { title: "应用", render: (_, p) => p.immutable_manifest.display?.name || p.shared_app_id },
    { title: "版本", dataIndex: "version" },
    { title: "模型", render: (_, p) => `${p.immutable_manifest.model?.provider_id}/${p.immutable_manifest.model?.model}` },
    { title: "操作", render: (_, p) => <Space>
      {p.review_status === "pending" && <><Input aria-label={`审核意见 ${p.version}`} value={notes[p.id] || ""} onChange={(e) => setNotes({ ...notes, [p.id]: e.target.value })} /><Button onClick={async () => { await sharedAppsApi.review(p.id, "rejected", notes[p.id] || ""); await load(); }}>拒绝</Button><Button onClick={async () => { await sharedAppsApi.review(p.id, "approved", notes[p.id] || ""); await load(); }}>批准</Button></>}
      {p.review_status === "approved" && p.current_publication_id !== p.id && <Button type="primary" onClick={async () => { if (p.current_publication_id) await sharedAppsApi.rollback(p.shared_app_id, p.id, p.current_publication_id); else await sharedAppsApi.publish(p, null); await load(); }}>{p.current_publication_id ? "回滚到此版本" : "发布"}</Button>}
      {p.current_publication_id === p.id && <Button danger onClick={async () => { await sharedAppsApi.retire(p.shared_app_id, p.id); await load(); }}>下架</Button>}
    </Space> },
  ]} /></Card>;
}
