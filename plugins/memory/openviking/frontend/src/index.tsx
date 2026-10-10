import type * as ReactNS from "react";

const React: typeof ReactNS = window.QwenPaw.host.React;
const { Card, Collapse, Form, Input, InputNumber, Select, Switch } =
  window.QwenPaw.host.antd;
const root = ["memory_backend_configs", "openviking"];

const messages = {
  en: {
    title: "OpenViking Memory Configuration",
    endpoint: "Server Endpoint",
    invalidEndpoint: "Enter a valid HTTP or HTTPS server address",
    key: "Tenant API Key",
    timeout: "Request Timeout (seconds)",
    tokenBudget: "Automatic Recall Token Budget",
    commit: "Commit Policy",
    auto: "Auto Memory Search",
    autoEnabled: "Enable automatic recall",
    maxResults: "Maximum automatic recall results",
    commitAuto: "Let OpenViking commit automatically",
    commitTurn: "Commit every completed turn",
  },
  zh: {
    title: "OpenViking 记忆配置",
    endpoint: "服务端点",
    invalidEndpoint: "请输入有效的 HTTP 或 HTTPS 服务地址",
    key: "租户 API Key",
    timeout: "请求超时（秒）",
    tokenBudget: "自动召回 Token 预算",
    commit: "提交策略",
    auto: "自动记忆搜索",
    autoEnabled: "启用自动召回",
    maxResults: "自动召回最大结果数",
    commitAuto: "由 OpenViking 自动提交",
    commitTurn: "每个完成的对话轮次提交",
  },
  ja: {
    title: "OpenViking メモリ設定",
    endpoint: "サーバーエンドポイント",
    invalidEndpoint:
      "有効な HTTP または HTTPS サーバーアドレスを入力してください",
    key: "テナント API キー",
    timeout: "リクエストタイムアウト（秒）",
    tokenBudget: "自動想起のトークン予算",
    commit: "コミットポリシー",
    auto: "自動メモリ検索",
    autoEnabled: "自動想起を有効にする",
    maxResults: "自動想起の最大結果数",
    commitAuto: "OpenViking に自動コミットを任せる",
    commitTurn: "完了した各ターンをコミットする",
  },
  id: {
    title: "Konfigurasi Memori OpenViking",
    endpoint: "Endpoint Server",
    invalidEndpoint: "Masukkan alamat server HTTP atau HTTPS yang valid",
    key: "Kunci API Tenant",
    timeout: "Batas Waktu Permintaan (detik)",
    tokenBudget: "Anggaran Token Pemanggilan Otomatis",
    commit: "Kebijakan Commit",
    auto: "Pencarian Memori Otomatis",
    autoEnabled: "Aktifkan pemanggilan otomatis",
    maxResults: "Hasil pemanggilan otomatis maksimum",
    commitAuto: "Biarkan OpenViking melakukan commit otomatis",
    commitTurn: "Commit setiap giliran yang selesai",
  },
  "pt-br": {
    title: "Configuração de memória OpenViking",
    endpoint: "Endpoint do servidor",
    invalidEndpoint: "Insira um endereço de servidor HTTP ou HTTPS válido",
    key: "Chave de API do locatário",
    timeout: "Tempo limite da solicitação (segundos)",
    tokenBudget: "Orçamento de tokens para recuperação automática",
    commit: "Política de commit",
    auto: "Pesquisa automática de memória",
    autoEnabled: "Ativar recuperação automática",
    maxResults: "Máximo de resultados da recuperação automática",
    commitAuto: "Permitir que o OpenViking faça commit automaticamente",
    commitTurn: "Fazer commit em cada turno concluído",
  },
  ru: {
    title: "Настройка памяти OpenViking",
    endpoint: "Конечная точка сервера",
    invalidEndpoint: "Введите корректный адрес сервера HTTP или HTTPS",
    key: "API-ключ арендатора",
    timeout: "Тайм-аут запроса (секунды)",
    tokenBudget: "Бюджет токенов автоматического поиска",
    commit: "Политика фиксации",
    auto: "Автоматический поиск памяти",
    autoEnabled: "Включить автоматическое извлечение",
    maxResults: "Максимум результатов автоматического поиска",
    commitAuto: "Разрешить OpenViking фиксировать автоматически",
    commitTurn: "Фиксировать каждый завершённый ход",
  },
  vi: {
    title: "Cấu hình bộ nhớ OpenViking",
    endpoint: "Điểm cuối máy chủ",
    invalidEndpoint: "Nhập địa chỉ máy chủ HTTP hoặc HTTPS hợp lệ",
    key: "Khóa API tenant",
    timeout: "Thời gian chờ yêu cầu (giây)",
    tokenBudget: "Ngân sách token truy xuất tự động",
    commit: "Chính sách commit",
    auto: "Tìm kiếm bộ nhớ tự động",
    autoEnabled: "Bật truy xuất tự động",
    maxResults: "Số kết quả truy xuất tự động tối đa",
    commitAuto: "Để OpenViking tự động commit",
    commitTurn: "Commit mỗi lượt hoàn tất",
  },
} as const;

function useMessages() {
  const locale = (window.QwenPaw.host.useLocale?.() || "en").toLowerCase();
  const key = locale.startsWith("zh")
    ? "zh"
    : locale.startsWith("pt")
    ? "pt-br"
    : locale.split("-")[0];
  return messages[key as keyof typeof messages] || messages.en;
}

function OpenVikingConfigCard() {
  const text = useMessages();
  return (
    <Card title={text.title}>
      <Form.Item
        name={[...root, "base_url"]}
        label={text.endpoint}
        initialValue="http://127.0.0.1:1933"
        rules={[
          { required: true },
          {
            validator: async (_: unknown, value: string) => {
              if (!value) return;
              try {
                const url = new URL(value);
                if (
                  ["http:", "https:"].includes(url.protocol) &&
                  url.hostname
                ) {
                  return;
                }
              } catch {
                // Fall through to the localized validation error.
              }
              throw new Error(text.invalidEndpoint);
            },
          },
        ]}
      >
        <Input placeholder="http://127.0.0.1:1933" />
      </Form.Item>
      <Form.Item
        name={[...root, "api_key"]}
        label={text.key}
        rules={[{ required: true }]}
      >
        <Input.Password autoComplete="new-password" />
      </Form.Item>
      <Form.Item
        name={[...root, "request_timeout"]}
        label={text.timeout}
        initialValue={10}
        rules={[{ required: true }, { type: "number", min: 1, max: 300 }]}
      >
        <InputNumber min={1} max={300} style={{ width: "100%" }} />
      </Form.Item>
      <Form.Item
        name={[...root, "retrieval_token_budget"]}
        label={text.tokenBudget}
        initialValue={2048}
        rules={[{ required: true }, { type: "number", min: 64, max: 32000 }]}
      >
        <InputNumber min={64} max={32000} style={{ width: "100%" }} />
      </Form.Item>
      <Form.Item
        name={[...root, "commit_policy"]}
        label={text.commit}
        initialValue="auto"
      >
        <Select
          options={[
            { value: "auto", label: text.commitAuto },
            { value: "every_turn", label: text.commitTurn },
          ]}
        />
      </Form.Item>
      <Collapse
        items={[
          {
            key: "auto",
            label: text.auto,
            forceRender: true,
            children: (
              <>
                <Form.Item
                  name={[...root, "auto_memory_search_config", "enabled"]}
                  label={text.autoEnabled}
                  valuePropName="checked"
                  initialValue={true}
                >
                  <Switch />
                </Form.Item>
                <Form.Item
                  name={[...root, "auto_memory_search_config", "max_results"]}
                  label={text.maxResults}
                  initialValue={3}
                  rules={[
                    { required: true },
                    { type: "number", min: 1, max: 20 },
                  ]}
                >
                  <InputNumber min={1} max={20} style={{ width: "100%" }} />
                </Form.Item>
              </>
            ),
          },
        ]}
      />
    </Card>
  );
}

window.QwenPaw.memoryBackends.register("memory-openviking", {
  id: "openviking",
  label: "OpenViking",
  configPath: root,
  tabKey: "openvikingMemory",
  ConfigComponent: OpenVikingConfigCard,
});
