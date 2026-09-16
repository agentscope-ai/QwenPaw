import { LockOutlined } from "@ant-design/icons";
import { Tag, Tooltip } from "antd";

export interface PublicationModelLockProps {
  version: string;
  providerId: string;
  model: string;
}

export default function PublicationModelLock({ version, providerId, model }: PublicationModelLockProps) {
  return <Tooltip title="共享应用模型由已审核发布版本锁定">
    <Tag icon={<LockOutlined />} color="blue">{version} · {providerId}/{model}</Tag>
  </Tooltip>;
}
