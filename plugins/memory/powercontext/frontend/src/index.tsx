import type * as ReactNS from "react";

const React: typeof ReactNS = window.QwenPaw.host.React;
const { Card, Collapse, Form, Input, InputNumber, Switch } =
  window.QwenPaw.host.antd;
const root = ["memory_backend_configs", "powercontext"];

const messages = {
  en: {
    title: "PowerContext Memory Configuration",
    serverUrl: "Server URL",
    token: "Bearer Token",
    scope: "Memory Scope",
    scopePlaceholder:
      "Leave empty to use this installation's unique agent scope",
    scopeInvalid: "Memory scope must not contain only whitespace.",
    timeout: "Request Timeout",
    autoSection: "Auto Memory Search",
    autoEnabled: "Auto Memory Search (Beta)",
    autoTooltip:
      "Run memory search on every conversation turn. This improves recall but increases token consumption.",
    maxBytes: "Maximum injected context (bytes)",
    maxBytesTooltip:
      "Bounds the total PowerContext search result content added to one model turn.",
    maxResults: "Maximum automatic memory search results",
    maxRequired: "Max results is required",
    maxMin: "Max results must be at least 1",
    maxTooltip: "Maximum number of results returned by automatic memory search",
  },
  zh: {
    title: "PowerContext 记忆配置",
    serverUrl: "服务地址",
    token: "Bearer Token",
    scope: "记忆作用域",
    scopePlaceholder: "留空以使用当前安装中唯一的 Agent 作用域",
    scopeInvalid: "记忆作用域不能只包含空白字符。",
    timeout: "请求超时",
    autoSection: "自动记忆搜索",
    autoEnabled: "自动记忆搜索（Beta）",
    autoTooltip:
      "每轮对话都自动触发记忆搜索，可以改善记忆召回，但会增加 token 消耗。",
    maxBytes: "最大注入上下文（字节）",
    maxBytesTooltip: "限制单轮模型调用中注入的 PowerContext 检索结果总量。",
    maxResults: "自动记忆搜索最大结果数",
    maxRequired: "最大结果数为必填项",
    maxMin: "最大结果数必须大于等于 1",
    maxTooltip: "自动记忆搜索时返回的最大结果数",
  },
  id: {
    title: "Konfigurasi Memori PowerContext",
    serverUrl: "URL Server",
    token: "Token Bearer",
    scope: "Ruang Lingkup Memori",
    scopePlaceholder:
      "Kosongkan untuk menggunakan ruang lingkup agen unik untuk instalasi ini",
    scopeInvalid: "Ruang lingkup memori tidak boleh hanya berisi spasi.",
    timeout: "Batas Waktu Permintaan",
    autoSection: "Pencarian Memori Otomatis",
    autoEnabled: "Pencarian Memori Otomatis (Beta)",
    autoTooltip: "Jalankan pencarian memori pada setiap giliran percakapan.",
    maxBytes: "Konteks maksimum yang disisipkan (byte)",
    maxBytesTooltip:
      "Membatasi total hasil pencarian PowerContext yang ditambahkan ke satu giliran model.",
    maxResults: "Hasil Maksimum Pencarian Otomatis",
    maxRequired: "Hasil maksimum wajib diisi",
    maxMin: "Hasil maksimum minimal 1",
    maxTooltip:
      "Jumlah hasil maksimum saat pencarian memori otomatis diaktifkan",
  },
  ja: {
    title: "PowerContext メモリ設定",
    serverUrl: "サーバー URL",
    token: "Bearer トークン",
    scope: "メモリスコープ",
    scopePlaceholder:
      "空欄の場合、このインストール固有のエージェントスコープを使用します",
    scopeInvalid: "メモリスコープを空白文字だけにすることはできません。",
    timeout: "リクエストタイムアウト",
    autoSection: "自動メモリ検索",
    autoEnabled: "自動メモリ検索（Beta）",
    autoTooltip:
      "会話の各ターンでメモリ検索を自動実行します。トークン消費量が増加します。",
    maxBytes: "注入するコンテキストの最大量（バイト）",
    maxBytesTooltip:
      "1回のモデル呼び出しに追加される PowerContext 検索結果の合計量を制限します。",
    maxResults: "自動検索の最大結果数",
    maxRequired: "最大結果数は必須です",
    maxMin: "最大結果数は1以上である必要があります",
    maxTooltip: "自動メモリ検索で返す結果の最大数",
  },
  "pt-br": {
    title: "Configuração de memória PowerContext",
    serverUrl: "URL do servidor",
    token: "Token Bearer",
    scope: "Escopo de memória",
    scopePlaceholder:
      "Deixe em branco para usar o escopo de agente exclusivo desta instalação",
    scopeInvalid: "O escopo de memória não pode conter apenas espaços.",
    timeout: "Tempo limite da solicitação",
    autoSection: "Pesquisa automática de memória",
    autoEnabled: "Pesquisa automática de memória (Beta)",
    autoTooltip:
      "Executa a pesquisa de memória a cada turno. Isso aumenta o consumo de tokens.",
    maxBytes: "Contexto injetado máximo (bytes)",
    maxBytesTooltip:
      "Limita o total de resultados de pesquisa do PowerContext adicionados a um turno do modelo.",
    maxResults: "Máximo de resultados da pesquisa automática",
    maxRequired: "O máximo de resultados é obrigatório",
    maxMin: "O máximo de resultados deve ser pelo menos 1",
    maxTooltip:
      "Número máximo de resultados retornados pela pesquisa automática",
  },
  ru: {
    title: "Конфигурация памяти PowerContext",
    serverUrl: "URL сервера",
    token: "Bearer-токен",
    scope: "Область памяти",
    scopePlaceholder:
      "Оставьте пустым, чтобы использовать уникальную область агента для этой установки",
    scopeInvalid: "Область памяти не может состоять только из пробелов.",
    timeout: "Тайм-аут запроса",
    autoSection: "Автоматический поиск по памяти",
    autoEnabled: "Автоматический поиск по памяти (Beta)",
    autoTooltip:
      "Запускать поиск по памяти на каждом ходе диалога. Это увеличивает расход токенов.",
    maxBytes: "Максимальный объём внедряемого контекста (байт)",
    maxBytesTooltip:
      "Ограничивает общий объём результатов поиска PowerContext за один ход модели.",
    maxResults: "Макс. результатов автоматического поиска",
    maxRequired: "Требуется указать макс. число результатов",
    maxMin: "Макс. число результатов должно быть не меньше 1",
    maxTooltip: "Максимальное количество результатов автоматического поиска",
  },
  vi: {
    title: "Cấu hình bộ nhớ PowerContext",
    serverUrl: "URL máy chủ",
    token: "Bearer Token",
    scope: "Phạm vi bộ nhớ",
    scopePlaceholder:
      "Để trống để sử dụng phạm vi tác nhân riêng của bản cài đặt này",
    scopeInvalid: "Phạm vi bộ nhớ không được chỉ chứa khoảng trắng.",
    timeout: "Thời gian chờ yêu cầu",
    autoSection: "Tìm kiếm bộ nhớ tự động",
    autoEnabled: "Tìm kiếm bộ nhớ tự động (Beta)",
    autoTooltip:
      "Tự động tìm kiếm bộ nhớ ở mỗi lượt hội thoại; thao tác này làm tăng mức sử dụng token.",
    maxBytes: "Ngữ cảnh được chèn tối đa (byte)",
    maxBytesTooltip:
      "Giới hạn tổng lượng kết quả tìm kiếm PowerContext được thêm vào một lượt mô hình.",
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

function PowerContextConfigCard() {
  const text = useMessages();
  return (
    <Card title={text.title}>
      <Form.Item
        name={[...root, "base_url"]}
        label={text.serverUrl}
        rules={[{ required: true }, { type: "url" }]}
      >
        <Input placeholder="http://127.0.0.1:8000" />
      </Form.Item>
      <Form.Item name={[...root, "token"]} label={text.token}>
        <Input.Password />
      </Form.Item>
      <Form.Item
        name={[...root, "scope_id"]}
        label={text.scope}
        rules={[
          { max: 256 },
          {
            validator: (_: unknown, value: string) =>
              !value || value.trim()
                ? Promise.resolve()
                : Promise.reject(new Error(text.scopeInvalid)),
          },
        ]}
      >
        <Input maxLength={256} placeholder={text.scopePlaceholder} />
      </Form.Item>
      <Form.Item
        name={[...root, "timeout"]}
        label={text.timeout}
        initialValue={10}
        rules={[{ required: true }, { type: "number", min: 1, max: 60 }]}
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
                  name={[
                    ...root,
                    "auto_memory_search_config",
                    "max_context_bytes",
                  ]}
                  label={text.maxBytes}
                  tooltip={text.maxBytesTooltip}
                  initialValue={12000}
                  rules={[
                    { required: true },
                    { type: "number", min: 1024, max: 32768 },
                  ]}
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
                  label={text.maxResults}
                  tooltip={text.maxTooltip}
                  initialValue={3}
                  rules={[
                    { required: true, message: text.maxRequired },
                    { type: "number", min: 1, max: 50, message: text.maxMin },
                  ]}
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
