import type * as ReactNS from "react";

const React: typeof ReactNS = window.QwenPaw.host.React;
const { Card, Collapse, Form, Input, InputNumber, Switch } =
  window.QwenPaw.host.antd;
const root = ["memory_backend_configs", "adbpg"];

function ADBPGConfigCard() {
  const locale = window.QwenPaw.host.useLocale?.() || "en";
  const zh = locale.toLowerCase().startsWith("zh");
  return (
    <Card title={zh ? "ADBPG 记忆" : "ADBPG Memory"}>
      <Form.Item name={[...root, "rest_base_url"]} label="REST Base URL">
        <Input placeholder="https://your-adbpg-api.example.com" />
      </Form.Item>
      <Form.Item name={[...root, "rest_api_key"]} label="REST API Key">
        <Input.Password />
      </Form.Item>
      <Form.Item
        name={[...root, "memory_isolation"]}
        label={zh ? "按 Agent 隔离" : "Per-agent isolation"}
        valuePropName="checked"
        initialValue={true}
      >
        <Switch />
      </Form.Item>
      <Form.Item
        name={[...root, "search_timeout"]}
        label={zh ? "搜索超时" : "Search timeout"}
        initialValue={10}
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
                  name={[...root, "auto_memory_search_config", "max_results"]}
                  label={zh ? "最大结果数" : "Maximum results"}
                  initialValue={3}
                  rules={[{ required: true }, { type: "number", min: 1 }]}
                >
                  <InputNumber min={1} style={{ width: "100%" }} />
                </Form.Item>
              </>
            ),
          },
        ]}
      />
    </Card>
  );
}

window.QwenPaw.memoryBackends.register("memory-adbpg", {
  id: "adbpg",
  label: "ADBPG",
  configPath: root,
  tabKey: "adbpgMemory",
  ConfigComponent: ADBPGConfigCard,
});
