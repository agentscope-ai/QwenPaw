/**
 * Page showing live NocoBase users and their effective channel access.
 */

import { nocobaseApi } from "../api";

export function UsersPage() {
  const { React, antd } = (window as any).QwenPaw.host;
  const { useState, useEffect } = React;
  const { Card, Table, Tag, Button, Space, message, Spin } = antd;

  const [users, setUsers] = useState([] as any[]);
  const [loading, setLoading] = useState(true);

  const fetchUsers = async () => {
    setLoading(true);
    try {
      const data = await nocobaseApi.getUsers();
      setUsers(data || []);
    } catch (err: any) {
      message.error(err.message || "加载用户失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUsers();
  }, []);

  const columns = [
    {
      title: "NocoBase ID",
      dataIndex: "id",
      key: "id",
    },
    {
      title: "邮箱 / Sender ID",
      dataIndex: "sender_id",
      key: "sender_id",
    },
    {
      title: "昵称",
      dataIndex: "nickname",
      key: "nickname",
    },
    {
      title: "角色",
      key: "roles",
      render: (_: any, record: any) =>
        (record.roles || []).map((role: string, idx: number) =>
          React.createElement(Tag, { key: idx, color: "blue" }, role),
        ),
    },
  ];

  return React.createElement(
    Card,
    {
      title: "NocoBase 用户",
      extra: React.createElement(
        Space,
        {},
        React.createElement(Button, { onClick: fetchUsers, loading }, "刷新"),
      ),
    },
    loading && users.length === 0
      ? React.createElement(
          "div",
          { style: { textAlign: "center", padding: 60 } },
          React.createElement(Spin, { size: "large" }),
        )
      : React.createElement(Table, {
          columns,
          dataSource: users.map((u) => ({ ...u, key: u.id || u.sender_id })),
          pagination: { pageSize: 20 },
        }),
  );
}
