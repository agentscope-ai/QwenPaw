/**
 * NocoBase Auth configuration page.
 */

import { nocobaseApi } from "../api";

export function ConfigPage() {
  const { React, antd } = (window as any).QwenPaw.host;
  const { useState, useEffect } = React;
  const { Card, Form, Input, Switch, Button, Space, message, Select, Spin } =
    antd;
  const [form] = Form.useForm();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    nocobaseApi
      .getConfig()
      .then((config: any) => {
        form.setFieldsValue({
          enabled: config.enabled ?? false,
          base_url: config.base_url ?? "",
          api_token: config.api_token ?? "",
          authenticator: config.authenticator ?? "basic",
          user_id_field: config.user_id_field ?? "email",
        });
      })
      .catch((err: any) => {
        message.error(err.message || "加载配置失败");
      })
      .finally(() => setLoading(false));
  }, [form, message]);

  const handleSave = async () => {
    let values;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setSaving(true);
    try {
      await nocobaseApi.updateConfig({
        ...values,
        role_channel_map: [],
      });
      message.success("配置已保存");
    } catch (err: any) {
      message.error(err.message || "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    try {
      const result = await nocobaseApi.testConnection();
      if (result.ok) {
        message.success("NocoBase 连接成功");
      } else {
        message.error(result.error || "连接失败");
      }
    } catch (err: any) {
      message.error(err.message || "连接测试失败");
    } finally {
      setTesting(false);
    }
  };

  if (loading) {
    return React.createElement(
      "div",
      { style: { textAlign: "center", padding: 60 } },
      React.createElement(Spin, { size: "large" }),
    );
  }

  return React.createElement(
    Card,
    { title: "NocoBase 连接配置", style: { maxWidth: 640 } },
    React.createElement(
      Form,
      { form, layout: "vertical", onFinish: handleSave },
      React.createElement(
        Form.Item,
        {
          name: "enabled",
          valuePropName: "checked",
          label: "启用 NocoBase 权限",
        },
        React.createElement(Switch),
      ),
      React.createElement(
        Form.Item,
        {
          name: "base_url",
          label: "NocoBase 地址",
          rules: [{ required: true, message: "请输入 NocoBase 地址" }],
        },
        React.createElement(Input, {
          placeholder: "https://nocobase.example.com",
        }),
      ),
      React.createElement(
        Form.Item,
        {
          name: "api_token",
          label: "API Token（用于同步用户/角色）",
        },
        React.createElement(Input.Password, {
          placeholder: "NocoBase API Token",
        }),
      ),
      React.createElement(
        Form.Item,
        {
          name: "authenticator",
          label: "登录认证器",
          rules: [{ required: true, message: "请输入登录认证器" }],
        },
        React.createElement(Input, {
          placeholder: "basic",
        }),
      ),
      React.createElement(
        Form.Item,
        {
          name: "user_id_field",
          label: "用户 ID 字段",
          rules: [{ required: true, message: "请选择用户 ID 字段" }],
        },
        React.createElement(
          Select,
          {},
          React.createElement(Select.Option, { value: "email" }, "Email"),
          React.createElement(Select.Option, { value: "phone" }, "Phone"),
          React.createElement(Select.Option, { value: "nickname" }, "Nickname"),
          React.createElement(Select.Option, { value: "username" }, "Username"),
        ),
      ),
      React.createElement(
        Form.Item,
        {},
        React.createElement(
          Space,
          {},
          React.createElement(
            Button,
            { type: "primary", htmlType: "submit", loading: saving },
            "保存",
          ),
          React.createElement(
            Button,
            { onClick: handleTest, loading: testing },
            "测试连接",
          ),
        ),
      ),
    ),
  );
}
