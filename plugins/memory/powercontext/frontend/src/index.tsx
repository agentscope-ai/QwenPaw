import type * as ReactNS from "react";

const React: typeof ReactNS = window.QwenPaw.host.React;
const { Card, Collapse, Form, Input, InputNumber, Switch } =
  window.QwenPaw.host.antd;
const root = ["memory_backend_configs", "powercontext"];

function PowerContextConfigCard() {
  const locale = window.QwenPaw.host.useLocale?.() || "en";
  const zh = locale.toLowerCase().startsWith("zh");
  return (
    <Card title={zh ? "PowerContext 记忆" : "PowerContext Memory"}>
      <Form.Item
        name={[...root, "base_url"]}
        label={zh ? "服务地址" : "Server URL"}
        rules={[{ required: true }, { type: "url" }]}
      >
        <Input placeholder="http://127.0.0.1:8000" />
      </Form.Item>
      <Form.Item
        name={[...root, "token"]}
        label={zh ? "访问令牌" : "Access token"}
      >
        <Input.Password />
      </Form.Item>
      <Form.Item
        name={[...root, "scope_id"]}
        label={zh ? "记忆作用域" : "Memory scope"}
        rules={[
          { max: 256 },
          {
            validator: (_: unknown, value: string) =>
              !value || value.trim()
                ? Promise.resolve()
                : Promise.reject(
                    new Error(
                      zh ? "作用域不能只包含空白" : "Scope must not be blank",
                    ),
                  ),
          },
        ]}
      >
        <Input maxLength={256} />
      </Form.Item>
      <Form.Item
        name={[...root, "timeout"]}
        label={zh ? "请求超时" : "Request timeout"}
        initialValue={10}
        rules={[{ type: "number", min: 1, max: 60 }]}
      >
        <InputNumber
          min={1}
          max={60}
          addonAfter="s"
          style={{ width: "100%" }}
        />
      </Form.Item>
      <Collapse
        items={[
          {
            key: "auto",
            label: zh ? "自动记忆召回" : "Automatic memory recall",
            forceRender: true,
            children: (
              <>
                <Form.Item
                  name={[...root, "auto_memory_search_config", "enabled"]}
                  label={zh ? "启用" : "Enabled"}
                  valuePropName="checked"
                  initialValue={true}
                >
                  <Switch />
                </Form.Item>
                <Form.Item
                  name={[
                    ...root,
                    "auto_memory_search_config",
                    "max_context_bytes",
                  ]}
                  label={zh ? "最大注入字节数" : "Maximum injected bytes"}
                  initialValue={12000}
                  rules={[{ type: "number", min: 1024, max: 32768 }]}
                >
                  <InputNumber
                    min={1024}
                    max={32768}
                    step={1024}
                    style={{ width: "100%" }}
                  />
                </Form.Item>
                <Form.Item
                  name={[...root, "auto_memory_search_config", "max_results"]}
                  label={zh ? "最大结果数" : "Maximum results"}
                  initialValue={3}
                  rules={[{ type: "number", min: 1, max: 50 }]}
                >
                  <InputNumber min={1} max={50} style={{ width: "100%" }} />
                </Form.Item>
              </>
            ),
          },
        ]}
      />
    </Card>
  );
}

window.QwenPaw.memoryBackends.register("memory-powercontext", {
  id: "powercontext",
  label: "PowerContext",
  configPath: root,
  tabKey: "powercontextMemory",
  ConfigComponent: PowerContextConfigCard,
});
