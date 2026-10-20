import type * as ReactNS from "react";

const React: typeof ReactNS = window.QwenPaw.host.React;
const {
  Button,
  Card,
  Collapse,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Switch,
} = window.QwenPaw.host.antd;
const root = ["memory_backend_configs", "powercontext"];

const messages = {
  en: {
    title: "PowerContext Memory Configuration",
    serverUrl: "Server URL",
    token: "Bearer Token",
    scope: "Memory Scope",
    scopePlaceholder:
      "Leave empty to create/reuse this Agent's Scope, or enter an existing Scope ID",
    scopeInvalid: "Memory scope must not contain only whitespace.",
    timeout: "Request Timeout",
    autoSection: "Automatic Context",
    autoEnabled: "Automatic Context (Beta)",
    autoTooltip:
      "Retrieve context on every conversation turn. This increases token consumption.",
    maxBytes: "Maximum injected context (bytes)",
    maxBytesTooltip:
      "Bounds the complete injected context, including its wrapper, in UTF-8 bytes.",
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
    scopePlaceholder:
      "留空自动创建或复用当前 Agent 作用域，也可填写已有 Scope ID",
    scopeInvalid: "记忆作用域不能只包含空白字符。",
    timeout: "请求超时",
    autoSection: "自动上下文",
    autoEnabled: "自动上下文（Beta）",
    autoTooltip: "每轮对话自动获取上下文，会增加 token 消耗。",
    maxBytes: "最大注入上下文（字节）",
    maxBytesTooltip: "按 UTF-8 字节数限制完整的注入内容，包含外层提示和标记。",
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
      "Kosongkan untuk membuat/memakai ulang Scope Agen ini, atau isi ID Scope yang ada",
    scopeInvalid: "Ruang lingkup memori tidak boleh hanya berisi spasi.",
    timeout: "Batas Waktu Permintaan",
    autoSection: "Konteks Otomatis",
    autoEnabled: "Konteks Otomatis (Beta)",
    autoTooltip: "Ambil konteks pada setiap giliran percakapan.",
    maxBytes: "Konteks maksimum yang disisipkan (byte)",
    maxBytesTooltip:
      "Membatasi seluruh konteks yang disisipkan, termasuk pembungkusnya, dalam byte UTF-8.",
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
      "空欄でこの Agent の Scope を作成・再利用、または既存の Scope ID を入力",
    scopeInvalid: "メモリスコープを空白文字だけにすることはできません。",
    timeout: "リクエストタイムアウト",
    autoSection: "自動コンテキスト",
    autoEnabled: "自動コンテキスト（Beta）",
    autoTooltip:
      "会話の各ターンでコンテキストを取得します。トークン消費量が増加します。",
    maxBytes: "注入するコンテキストの最大量（バイト）",
    maxBytesTooltip:
      "ラッパーを含む注入内容全体を UTF-8 バイト数で制限します。",
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
      "Deixe em branco para criar/reusar o Scope deste Agente ou informe um ID de Scope existente",
    scopeInvalid: "O escopo de memória não pode conter apenas espaços.",
    timeout: "Tempo limite da solicitação",
    autoSection: "Contexto automático",
    autoEnabled: "Contexto automático (Beta)",
    autoTooltip:
      "Obtém contexto a cada turno. Isso aumenta o consumo de tokens.",
    maxBytes: "Contexto injetado máximo (bytes)",
    maxBytesTooltip:
      "Limita todo o contexto injetado, incluindo o texto que o envolve, em bytes UTF-8.",
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
      "Оставьте пустым для создания/повторного использования Scope этого Агента или введите ID существующего Scope",
    scopeInvalid: "Область памяти не может состоять только из пробелов.",
    timeout: "Тайм-аут запроса",
    autoSection: "Автоматический контекст",
    autoEnabled: "Автоматический контекст (Beta)",
    autoTooltip:
      "Получать контекст на каждом ходе диалога. Это увеличивает расход токенов.",
    maxBytes: "Максимальный объём внедряемого контекста (байт)",
    maxBytesTooltip:
      "Ограничивает весь добавленный контекст, включая обрамление, в байтах UTF-8.",
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
      "Để trống để tạo/dùng lại Scope của Agent này, hoặc nhập ID Scope hiện có",
    scopeInvalid: "Phạm vi bộ nhớ không được chỉ chứa khoảng trắng.",
    timeout: "Thời gian chờ yêu cầu",
    autoSection: "Ngữ cảnh tự động",
    autoEnabled: "Ngữ cảnh tự động (Beta)",
    autoTooltip:
      "Lấy ngữ cảnh ở mỗi lượt hội thoại; thao tác này làm tăng mức sử dụng token.",
    maxBytes: "Ngữ cảnh được chèn tối đa (byte)",
    maxBytesTooltip:
      "Giới hạn toàn bộ ngữ cảnh được chèn, bao gồm phần bao quanh, theo byte UTF-8.",
    maxResults: "Số kết quả tối đa khi tự động tìm kiếm",
    maxRequired: "Bắt buộc nhập số kết quả tối đa",
    maxMin: "Số kết quả tối đa phải ít nhất là 1",
    maxTooltip: "Số kết quả tối đa trả về khi tự động tìm kiếm bộ nhớ",
  },
} as const;

const contextMessages = {
  en: {
    mode: "Retrieval mode",
    prepare: "Prepare context",
    memory: "Legacy memory search",
    modeHelp:
      "Use Legacy memory search for PowerContext v0.2. Prepare errors never switch modes automatically.",
    sections: "Context sections (in order)",
    sectionHelp:
      "Add, remove, or reorder sections. An empty list includes no sections. The server's default total limit is 8; its configured limit is authoritative.",
    family: "Family",
    limit: "Result limit",
    add: "Add section",
    remove: "Remove",
    up: "Move up",
    down: "Move down",
    unique: "Each family can appear only once.",
    show: "Show extra fields",
    recallRank: "Recall rank",
    confidence: "Confidence",
    profile: "Profile",
    topicMemory: "Topic memory",
    atomicMemory: "Memory",
    experience: "Experience",
  },
  zh: {
    mode: "召回方式",
    prepare: "组装上下文（Prepare）",
    memory: "旧版记忆搜索",
    modeHelp:
      "PowerContext v0.2 请选择旧版记忆搜索。Prepare 出错时不会自动切换模式。",
    sections: "上下文区块（按顺序）",
    sectionHelp:
      "可添加、移除或调整区块顺序。列表为空时不包含任何区块。服务端默认总条数上限为 8，实际以上游服务配置为准。",
    family: "类型",
    limit: "条数上限",
    add: "添加区块",
    remove: "移除",
    up: "上移",
    down: "下移",
    unique: "每种类型只能出现一次。",
    show: "显示额外字段",
    recallRank: "召回排名",
    confidence: "置信度",
    profile: "画像",
    topicMemory: "主题记忆",
    atomicMemory: "记忆",
    experience: "经验",
  },
  id: {
    mode: "Mode pengambilan",
    prepare: "Siapkan konteks",
    memory: "Pencarian memori lama",
    modeHelp:
      "Gunakan pencarian lama untuk PowerContext v0.2. Kesalahan Prepare tidak mengganti mode secara otomatis.",
    sections: "Bagian konteks (berurutan)",
    sectionHelp:
      "Tambah, hapus, atau urutkan bagian. Daftar kosong tidak menyertakan bagian apa pun. Batas total bawaan server adalah 8; konfigurasi server menentukan batas sebenarnya.",
    family: "Jenis",
    limit: "Batas hasil",
    add: "Tambah bagian",
    remove: "Hapus",
    up: "Pindah ke atas",
    down: "Pindah ke bawah",
    unique: "Setiap jenis hanya boleh muncul sekali.",
    show: "Tampilkan bidang tambahan",
    recallRank: "Peringkat pengambilan",
    confidence: "Keyakinan",
    profile: "Profil",
    topicMemory: "Memori topik",
    atomicMemory: "Memori",
    experience: "Pengalaman",
  },
  ja: {
    mode: "取得モード",
    prepare: "コンテキストを準備（Prepare）",
    memory: "旧版メモリ検索",
    modeHelp:
      "PowerContext v0.2 では旧版メモリ検索を選択してください。Prepare のエラー時に自動切替は行いません。",
    sections: "コンテキストのセクション（順序指定）",
    sectionHelp:
      "セクションの追加・削除・並べ替えができます。空のリストにはセクションが含まれません。サーバーの合計上限は既定で 8 件で、実際の設定が優先されます。",
    family: "種類",
    limit: "件数の上限",
    add: "セクションを追加",
    remove: "削除",
    up: "上へ",
    down: "下へ",
    unique: "同じ種類は一度だけ指定できます。",
    show: "追加フィールドを表示",
    recallRank: "検索順位",
    confidence: "信頼度",
    profile: "プロフィール",
    topicMemory: "トピックメモリ",
    atomicMemory: "メモリ",
    experience: "経験",
  },
  "pt-br": {
    mode: "Modo de recuperação",
    prepare: "Preparar contexto",
    memory: "Pesquisa de memória legada",
    modeHelp:
      "Use a pesquisa legada no PowerContext v0.2. Erros do Prepare não alteram o modo automaticamente.",
    sections: "Seções de contexto (em ordem)",
    sectionHelp:
      "Adicione, remova ou reordene seções. Uma lista vazia não inclui seções. O limite total padrão do servidor é 8; prevalece a configuração do servidor.",
    family: "Tipo",
    limit: "Limite de resultados",
    add: "Adicionar seção",
    remove: "Remover",
    up: "Mover para cima",
    down: "Mover para baixo",
    unique: "Cada tipo pode aparecer apenas uma vez.",
    show: "Mostrar campos extras",
    recallRank: "Posição de recuperação",
    confidence: "Confiança",
    profile: "Perfil",
    topicMemory: "Memória de tópico",
    atomicMemory: "Memória",
    experience: "Experiência",
  },
  ru: {
    mode: "Режим получения контекста",
    prepare: "Подготовка контекста",
    memory: "Устаревший поиск по памяти",
    modeHelp:
      "Для PowerContext v0.2 выберите устаревший поиск. Ошибки Prepare не переключают режим автоматически.",
    sections: "Разделы контекста (по порядку)",
    sectionHelp:
      "Добавляйте, удаляйте и перемещайте разделы. Пустой список не содержит разделов. Общий лимит сервера по умолчанию — 8; действует настройка сервера.",
    family: "Тип",
    limit: "Лимит результатов",
    add: "Добавить раздел",
    remove: "Удалить",
    up: "Выше",
    down: "Ниже",
    unique: "Каждый тип можно указать только один раз.",
    show: "Дополнительные поля",
    recallRank: "Позиция в выдаче",
    confidence: "Уверенность",
    profile: "Профиль",
    topicMemory: "Тематическая память",
    atomicMemory: "Память",
    experience: "Опыт",
  },
  vi: {
    mode: "Chế độ truy xuất",
    prepare: "Chuẩn bị ngữ cảnh",
    memory: "Tìm kiếm bộ nhớ phiên bản cũ",
    modeHelp:
      "Chọn tìm kiếm phiên bản cũ cho PowerContext v0.2. Lỗi Prepare không tự động chuyển chế độ.",
    sections: "Các phần ngữ cảnh (theo thứ tự)",
    sectionHelp:
      "Thêm, xóa hoặc sắp xếp các phần. Danh sách trống không bao gồm phần nào. Tổng giới hạn mặc định của máy chủ là 8; cấu hình máy chủ quyết định giới hạn thực tế.",
    family: "Loại",
    limit: "Giới hạn kết quả",
    add: "Thêm phần",
    remove: "Xóa",
    up: "Di chuyển lên",
    down: "Di chuyển xuống",
    unique: "Mỗi loại chỉ được xuất hiện một lần.",
    show: "Hiển thị trường bổ sung",
    recallRank: "Thứ hạng truy xuất",
    confidence: "Độ tin cậy",
    profile: "Hồ sơ",
    topicMemory: "Bộ nhớ chủ đề",
    atomicMemory: "Bộ nhớ",
    experience: "Kinh nghiệm",
  },
};

type ContextFamily = "profile" | "topic-memory" | "memory" | "experience";
type AssemblySection = { family: ContextFamily; limit: number };
const defaultSections: AssemblySection[] = [
  { family: "profile", limit: 1 },
  { family: "topic-memory", limit: 2 },
  { family: "memory", limit: 3 },
  { family: "experience", limit: 2 },
];
const assemblyPath = [...root, "context_assembly"];

function useMessages() {
  const locale = (window.QwenPaw.host.useLocale?.() || "en").toLowerCase();
  const key = locale.startsWith("zh")
    ? "zh"
    : locale.startsWith("pt")
    ? "pt-br"
    : locale.split("-")[0];
  return {
    ...(messages[key as keyof typeof messages] || messages.en),
    ...(contextMessages[key as keyof typeof contextMessages] ||
      contextMessages.en),
  };
}

function ContextAssemblyEditor() {
  const text = useMessages();
  const form = Form.useFormInstance();
  const sections: AssemblySection[] =
    Form.useWatch([...assemblyPath, "sections"], form) ?? defaultSections;
  const familyOptions = [
    { value: "profile", label: text.profile },
    { value: "topic-memory", label: text.topicMemory },
    { value: "memory", label: text.atomicMemory },
    { value: "experience", label: text.experience },
  ];
  return (
    <>
      <Form.Item
        name={[...assemblyPath, "format"]}
        initialValue="markdown"
        hidden
      >
        <Input />
      </Form.Item>
      <Form.Item label={text.sections} extra={text.sectionHelp}>
        <Form.List
          name={[...assemblyPath, "sections"]}
          initialValue={defaultSections}
          rules={[
            {
              validator: (_: unknown, value: AssemblySection[]) =>
                new Set(value.map((section) => section.family)).size ===
                value.length
                  ? Promise.resolve()
                  : Promise.reject(new Error(text.unique)),
            },
          ]}
        >
          {(
            fields: { key: number; name: number }[],
            {
              add,
              remove,
              move,
            }: {
              add: (section: AssemblySection) => void;
              remove: (index: number) => void;
              move: (from: number, to: number) => void;
            },
            { errors }: { errors: ReactNS.ReactNode[] },
          ) => (
            <>
              {fields.map((field, index) => {
                const family = sections[field.name]?.family;
                const max = family === "experience" ? 2 : 8;
                return (
                  <Space
                    key={field.key}
                    align="start"
                    wrap
                    style={{ display: "flex", marginBottom: 8 }}
                  >
                    <Form.Item
                      name={[field.name, "family"]}
                      label={text.family}
                      rules={[{ required: true }]}
                    >
                      <Select
                        style={{ minWidth: 180 }}
                        options={familyOptions.map((option) => ({
                          ...option,
                          disabled:
                            option.value !== family &&
                            sections.some(
                              (section) => section.family === option.value,
                            ),
                        }))}
                        onChange={(value: ContextFamily) => {
                          const limitPath = [
                            ...assemblyPath,
                            "sections",
                            field.name,
                            "limit",
                          ];
                          const current = form.getFieldValue(limitPath);
                          if (value === "experience" && current > 2)
                            form.setFieldValue(limitPath, 2);
                        }}
                      />
                    </Form.Item>
                    <Form.Item
                      name={[field.name, "limit"]}
                      label={text.limit}
                      rules={[
                        { required: true },
                        { type: "integer", min: 1, max },
                      ]}
                    >
                      <InputNumber min={1} max={max} precision={0} />
                    </Form.Item>
                    <Space wrap style={{ paddingTop: 30 }}>
                      <Button
                        disabled={index === 0}
                        onClick={() => move(index, index - 1)}
                      >
                        {text.up}
                      </Button>
                      <Button
                        disabled={index === fields.length - 1}
                        onClick={() => move(index, index + 1)}
                      >
                        {text.down}
                      </Button>
                      <Button onClick={() => remove(field.name)}>
                        {text.remove}
                      </Button>
                    </Space>
                  </Space>
                );
              })}
              <Button
                disabled={fields.length >= defaultSections.length}
                onClick={() => {
                  const next = defaultSections.find(
                    (candidate) =>
                      !sections.some(
                        (section) => section.family === candidate.family,
                      ),
                  );
                  if (next) add({ ...next });
                }}
              >
                {text.add}
              </Button>
              <Form.ErrorList errors={errors} />
            </>
          )}
        </Form.List>
      </Form.Item>
      <Form.Item
        name={[...assemblyPath, "show"]}
        label={text.show}
        initialValue={[]}
      >
        <Select
          mode="multiple"
          allowClear
          options={[
            { value: "recall_rank", label: text.recallRank },
            { value: "confidence", label: text.confidence },
          ]}
        />
      </Form.Item>
    </>
  );
}

function AutomaticContextOptions() {
  const text = useMessages();
  const form = Form.useFormInstance();
  const mode =
    Form.useWatch([...root, "auto_memory_search_config", "mode"], form) ??
    "prepare";
  return (
    <>
      <Form.Item
        name={[...root, "auto_memory_search_config", "mode"]}
        label={text.mode}
        extra={text.modeHelp}
        initialValue="prepare"
        rules={[{ required: true }]}
      >
        <Select
          options={[
            { value: "prepare", label: text.prepare },
            { value: "memory", label: text.memory },
          ]}
        />
      </Form.Item>
      {mode === "prepare" ? (
        <ContextAssemblyEditor />
      ) : (
        <Form.Item
          name={[...root, "auto_memory_search_config", "max_results"]}
          label={text.maxResults}
          tooltip={text.maxTooltip}
          initialValue={3}
          rules={[
            { required: true, message: text.maxRequired },
            { type: "integer", min: 1, max: 50, message: text.maxMin },
          ]}
        >
          <InputNumber
            min={1}
            max={50}
            precision={0}
            style={{ width: "100%" }}
          />
        </Form.Item>
      )}
    </>
  );
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
                <AutomaticContextOptions />
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
