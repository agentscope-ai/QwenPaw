import type * as ReactNS from "react";

const React: typeof ReactNS = window.QwenPaw.host.React;
const { Card, Collapse, Form, Input, InputNumber, Switch } =
  window.QwenPaw.host.antd;
const root = ["memory_backend_configs", "adbpg"];

const messages = {
  en: {
    title: "ADBPG Memory Configuration",
    isolation: "Memory Isolation (per-agent)",
    timeout: "Search Timeout",
    autoSection: "Auto Memory Search",
    autoEnabled: "Auto Memory Search (Beta)",
    autoTooltip:
      "Run memory search on every conversation turn. This improves recall but increases token consumption.",
    maxResults: "Maximum automatic memory search results",
    maxRequired: "Max results is required",
    maxMin: "Max results must be at least 1",
    maxTooltip: "Maximum number of results returned by automatic memory search",
  },
  zh: {
    title: "ADBPG 记忆配置",
    isolation: "记忆隔离（按 Agent）",
    timeout: "搜索超时",
    autoSection: "自动记忆搜索",
    autoEnabled: "自动记忆搜索（Beta）",
    autoTooltip:
      "每轮对话都自动触发记忆搜索，可以改善记忆召回，但会增加 token 消耗。",
    maxResults: "自动记忆搜索最大结果数",
    maxRequired: "最大结果数为必填项",
    maxMin: "最大结果数必须大于等于 1",
    maxTooltip: "自动记忆搜索时返回的最大结果数",
  },
  id: {
    title: "Konfigurasi Memori ADBPG",
    isolation: "Isolasi Memori (per-agen)",
    timeout: "Timeout Pencarian",
    autoSection: "Pencarian Memori Otomatis",
    autoEnabled: "Pencarian Memori Otomatis (Beta)",
    autoTooltip: "Jalankan pencarian memori pada setiap giliran percakapan.",
    maxResults: "Hasil Maksimum Pencarian Otomatis",
    maxRequired: "Hasil maksimum wajib diisi",
    maxMin: "Hasil maksimum minimal 1",
    maxTooltip:
      "Jumlah hasil maksimum saat pencarian memori otomatis diaktifkan",
  },
  ja: {
    title: "ADBPG メモリ設定",
    isolation: "メモリ分離（エージェント単位）",
    timeout: "検索タイムアウト",
    autoSection: "自動メモリ検索",
    autoEnabled: "自動メモリ検索（Beta）",
    autoTooltip:
      "会話の各ターンでメモリ検索を自動実行します。トークン消費量が増加します。",
    maxResults: "自動検索の最大結果数",
    maxRequired: "最大結果数は必須です",
    maxMin: "最大結果数は1以上である必要があります",
    maxTooltip: "自動メモリ検索で返す結果の最大数",
  },
  "pt-br": {
    title: "Configuração de memória ADBPG",
    isolation: "Isolamento de memória (por agente)",
    timeout: "Tempo limite da pesquisa",
    autoSection: "Pesquisa automática de memória",
    autoEnabled: "Pesquisa automática de memória (Beta)",
    autoTooltip:
      "Executa a pesquisa de memória a cada turno. Isso aumenta o consumo de tokens.",
    maxResults: "Máximo de resultados da pesquisa automática",
    maxRequired: "O máximo de resultados é obrigatório",
    maxMin: "O máximo de resultados deve ser pelo menos 1",
    maxTooltip:
      "Número máximo de resultados retornados pela pesquisa automática",
  },
  ru: {
    title: "Конфигурация памяти ADBPG",
    isolation: "Изоляция памяти (по агентам)",
    timeout: "Тайм-аут поиска",
    autoSection: "Автоматический поиск по памяти",
    autoEnabled: "Автоматический поиск по памяти (Beta)",
    autoTooltip:
      "Запускать поиск по памяти на каждом ходе диалога. Это увеличивает расход токенов.",
    maxResults: "Макс. результатов автоматического поиска",
    maxRequired: "Требуется указать макс. число результатов",
    maxMin: "Макс. число результатов должно быть не меньше 1",
    maxTooltip: "Максимальное количество результатов автоматического поиска",
  },
  vi: {
    title: "Cấu hình bộ nhớ ADBPG",
    isolation: "Cách ly bộ nhớ (theo tác nhân)",
    timeout: "Thời gian chờ tìm kiếm",
    autoSection: "Tìm kiếm bộ nhớ tự động",
    autoEnabled: "Tìm kiếm bộ nhớ tự động (Beta)",
    autoTooltip:
      "Tự động tìm kiếm bộ nhớ ở mỗi lượt hội thoại; thao tác này làm tăng mức sử dụng token.",
    maxResults: "Số kết quả tối đa khi tự động tìm kiếm",
    maxRequired: "Bắt buộc nhập số kết quả tối đa",
    maxMin: "Số kết quả tối đa phải ít nhất là 1",
    maxTooltip: "Số kết quả tối đa trả về khi tự động tìm kiếm bộ nhớ",
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

function ADBPGConfigCard() {
  const text = useMessages();
  return (
    <Card title={text.title}>
      <Form.Item name={[...root, "rest_base_url"]} label="REST Base URL">
        <Input placeholder="https://your-adbpg-api.example.com" />
      </Form.Item>
      <Form.Item name={[...root, "rest_api_key"]} label="REST API Key">
        <Input.Password />
      </Form.Item>
      <Form.Item
        name={[...root, "memory_isolation"]}
        label={text.isolation}
        valuePropName="checked"
        initialValue={true}
      >
        <Switch />
      </Form.Item>
      <Form.Item
        name={[...root, "search_timeout"]}
        label={text.timeout}
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
            label: text.autoSection,
            forceRender: true,
            children: (
              <>
                <Form.Item
                  name={[...root, "auto_memory_search_config", "enabled"]}
                  label={text.autoEnabled}
                  tooltip={text.autoTooltip}
                  valuePropName="checked"
                  initialValue={true}
                >
                  <Switch />
                </Form.Item>
                <Form.Item
                  name={[...root, "auto_memory_search_config", "max_results"]}
                  label={text.maxResults}
                  tooltip={text.maxTooltip}
                  initialValue={3}
                  rules={[
                    { required: true, message: text.maxRequired },
                    { type: "number", min: 1, message: text.maxMin },
                  ]}
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
