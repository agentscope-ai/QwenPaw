/**
 * Page for editing NocoBase role -> QwenPaw channel mappings.
 */

import { nocobaseApi } from "../api";

function parseChannels(value: string): string[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

function channelsToString(channels: string[] | undefined): string {
  return (channels || []).join(", ");
}

export function RolesPage() {
  const { React, antd } = (window as any).QwenPaw.host;
  const { useState, useEffect } = React;
  const { Card, Table, Input, Button, Space, message, Spin, Tag } = antd;

  const [config, setConfig] = useState(null as any);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const fetchConfig = async () => {
    setLoading(true);
    try {
      const data = await nocobaseApi.getConfig();
      setConfig(data);
    } catch (err: any) {
      message.error(err.message || "加载配置失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchConfig();
  }, []);

  const updateMapping = (
    roleName: string,
    field: "allowed_channels" | "denied_channels",
    value: string,
  ) => {
    setConfig((prev: any) => {
      if (!prev) return prev;
      const map = [...(prev.role_channel_map || [])];
      const idx = map.findIndex((m: any) => m.role_name === roleName);
      if (idx >= 0) {
        map[idx] = { ...map[idx], [field]: parseChannels(value) };
      } else {
        map.push({
          role_name: roleName,
          allowed_channels:
            field === "allowed_channels" ? parseChannels(value) : [],
          denied_channels:
            field === "denied_channels" ? parseChannels(value) : [],
        });
      }
      return { ...prev, role_channel_map: map };
    });
  };

  const handleSave = async () => {
    if (!config) return;
    setSaving(true);
    try {
      await nocobaseApi.updateConfig(config);
      message.success("角色映射已保存");
    } catch (err: any) {
      message.error(err.message || "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const roleMap = (config?.role_channel_map || []) as any[];

  const columns = [
    {
      title: "角色",
      dataIndex: "role_name",
      key: "role_name",
      render: (name: string) => React.createElement("strong", null, name),
    },
    {
      title: "允许访问的频道",
      key: "allowed",
      render: (_: any, record: any) => {
        const existing = roleMap.find((m) => m.role_name === record.role_name);
        return React.createElement(Input, {
          placeholder: "console, dingtalk, telegram",
          defaultValue: channelsToString(existing?.allowed_channels),
          onBlur: (e: any) =>
            updateMapping(record.role_name, "allowed_channels", e.target.value),
        });
      },
    },
    {
      title: "拒绝访问的频道",
      key: "denied",
      render: (_: any, record: any) => {
        const existing = roleMap.find((m) => m.role_name === record.role_name);
        return React.createElement(Input, {
          placeholder: "dingtalk",
          defaultValue: channelsToString(existing?.denied_channels),
          onBlur: (e: any) =>
            updateMapping(record.role_name, "denied_channels", e.target.value),
        });
      },
    },
    {
      title: "说明",
      key: "hint",
      render: () =>
        React.createElement(Tag, { color: "orange" }, "deny 优先于 allow"),
    },
  ];

  const dataSource = roleMap.map((m: any) => ({
    ...m,
    key: m.role_name,
  }));

  return React.createElement(
    Card,
    {
      title: "角色 → 频道映射",
      extra: React.createElement(
        Button,
        { type: "primary", onClick: handleSave, loading: saving },
        "保存映射",
      ),
    },
    loading
      ? React.createElement(
          "div",
          { style: { textAlign: "center", padding: 60 } },
          React.createElement(Spin, { size: "large" }),
        )
      : React.createElement(
          Space,
          { direction: "vertical", style: { width: "100%" } },
          React.createElement(
            "div",
            { style: { color: "#8c8c8c", fontSize: 12 } },
            "先保存 NocoBase 连接配置，再在此页面为每个角色配置可访问的 QwenPaw 频道。多个频道用英文逗号分隔。",
          ),
          React.createElement(Table, {
            columns,
            dataSource,
            pagination: false,
          }),
        ),
  );
}
