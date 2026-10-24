const G = window.QwenPaw, w = G.host;
async function ae(d, o = {}) {
  const { timeout: e = 3e4, ...n } = o, l = new AbortController(), p = window.setTimeout(() => l.abort(), e);
  try {
    const m = await w.fetch(d, {
      ...n,
      signal: l.signal,
      headers: { "Content-Type": "application/json", ...n.headers }
    }), h = await m.json();
    if (!m.ok)
      throw new Error(
        typeof (h == null ? void 0 : h.detail) == "string" ? h.detail : `HTTP ${m.status}`
      );
    return h;
  } finally {
    window.clearTimeout(p);
  }
}
const fe = {
  get: () => ae("/desktop/recording/feature", { timeout: 5e3 }),
  set: (d) => ae("/desktop/recording/feature", {
    method: "PUT",
    body: JSON.stringify({ enabled: d })
  })
};
function Re(d) {
  const o = (n, l = {}) => ae(n, {
    ...l,
    headers: { ...l.headers, "X-Agent-Id": d }
  }), e = (n) => o(`/desktop/recording/${n}`, {
    method: "POST"
  });
  return {
    getStatus: () => o("/desktop/recording", {
      timeout: 5e3
    }),
    requestPermission: () => o(
      "/desktop/recording/permission/request",
      {
        method: "POST",
        timeout: 12e4
      }
    ),
    start: () => e("start"),
    pause: () => e("pause"),
    resume: () => e("resume"),
    stop: () => e("stop"),
    reviewRecording: (n) => o("/desktop/recording/learn/review", {
      method: "POST",
      body: JSON.stringify({ recording_id: n })
    }),
    prepareLearn: (n) => o("/desktop/recording/learn/prepare", {
      method: "POST",
      body: JSON.stringify(n)
    }),
    generateDraft: (n) => o("/desktop/recording/learn/generate", {
      method: "POST",
      body: JSON.stringify({ consent_token: n, consent: !0 }),
      timeout: 6e4
    }),
    recoverDraft: (n) => o(
      `/desktop/recording/learn/draft/${n}`,
      { timeout: 5e3 }
    ),
    materializeSkill: (n) => o("/desktop/recording/learn/materialize", {
      method: "POST",
      body: JSON.stringify({ ...n, approved: !0 }),
      timeout: 6e4
    })
  };
}
const Be = { "desktop.recording.cancel": "Cancel", "desktop.recording.title": "Workflow recording", "desktop.recording.start": "Record", "desktop.recording.authorize": "Enable recording", "desktop.recording.recording": "Recording", "desktop.recording.paused": "Paused", "desktop.recording.pause": "Pause", "desktop.recording.resume": "Resume", "desktop.recording.stop": "Stop", "desktop.recording.started": "Workflow recording started", "desktop.recording.permissionRequested": "Enable Input Monitoring and Accessibility for QwenPaw Computer Use in System Settings, then click Record again", "desktop.recording.saved": "Recording saved", "desktop.recording.unavailable": "Recording is unavailable while the desktop runtime is connecting", "desktop.recording.errors.inputMonitoringDenied": "Allow QwenPaw Computer Use in System Settings > Privacy & Security > Input Monitoring, then try again", "desktop.recording.errors.desktopBusy": "Another desktop session is already using recording", "desktop.recording.errors.runtimeUnavailable": "The desktop recording service is not ready", "desktop.recording.errors.generic": "Recording operation failed", "desktop.recording.learn.intentTitle": "Create a Skill from recording", "desktop.recording.learn.intentAction": "Preview shared data", "desktop.recording.learn.intentDescription": "Describe the workflow outcome. Recorded actions are evidence and will not be replayed as a coordinate macro.", "desktop.recording.learn.goal": "Workflow goal", "desktop.recording.learn.goalPlaceholder": "For example: calculate two user-provided numbers in Calculator", "desktop.recording.learn.context": "Additional context", "desktop.recording.learn.contextPlaceholder": "Optional: identify reusable inputs and actions to ignore", "desktop.recording.learn.selectEvents": "Select actions that belong to the workflow", "desktop.recording.learn.noTarget": "No semantic target", "desktop.recording.learn.unknownApp": "Unknown app", "desktop.recording.learn.eventType.activate": "Activate", "desktop.recording.learn.eventType.drag": "Drag", "desktop.recording.learn.eventType.scroll": "Scroll", "desktop.recording.learn.eventType.redacted_input": "Redacted input", "desktop.recording.learn.consentTitle": "Confirm analysis scope", "desktop.recording.learn.consentAction": "Generate draft", "desktop.recording.learn.externalTransfer": "Recording evidence will be sent to the configured model provider", "desktop.recording.learn.localProcessing": "Recording evidence will be processed by a local model", "desktop.recording.learn.consentDescription": "Only the redacted fields below are shared. Key content, absolute coordinates, screenshots, and recording paths are excluded. Consent applies to this generation only.", "desktop.recording.learn.provider": "Provider", "desktop.recording.learn.model": "Model", "desktop.recording.learn.events": "Source events → compact evidence", "desktop.recording.learn.fields": "Field scope", "desktop.recording.learn.consent": "I approve analyzing this recording with the model and fields shown above", "desktop.recording.learn.draftTitle": "Review Skill draft", "desktop.recording.learn.draftAction": "Create and enable Skill", "desktop.recording.learn.draftDescription": "The draft uses {{used}} source events and ignores {{ignored}}. You can edit it before creation.", "desktop.recording.learn.skillName": "Skill name", "desktop.recording.learn.skillContent": "SKILL.md content", "desktop.recording.learn.ambiguities": "The draft has unresolved ambiguities", "desktop.recording.learn.addContext": "Add context", "desktop.recording.learn.created": "Skill {{name}} was created and enabled", "desktop.recording.learn.failed": "Could not create a Skill from this recording", "desktop.recording.learn.modelUnavailable": "Configure and select a model in Models settings, then retry. Your recording is still saved.", "feature.description": "Record → review evidence → generate and save a Skill. This version records events only, not video.", "feature.enabled": "Enable Record & Replay", "feature.platform": "Recording requires QwenPaw Desktop on macOS 14 or later.", "feature.independence": "Turning this off ends its recording and pending Learn requests. Saved recordings and Skills are retained; Computer Use is unchanged. Desktop Replay requires the optional Computer Use plugin." }, Le = { "desktop.recording.cancel": "取消", "desktop.recording.title": "工作流录制", "desktop.recording.start": "录制", "desktop.recording.authorize": "启用录制", "desktop.recording.recording": "录制中", "desktop.recording.paused": "已暂停", "desktop.recording.pause": "暂停", "desktop.recording.resume": "继续", "desktop.recording.stop": "停止", "desktop.recording.started": "工作流录制已开始", "desktop.recording.permissionRequested": "请在系统设置中允许 QwenPaw Computer Use 使用输入监控和辅助功能，然后再次点击录制", "desktop.recording.saved": "录制已保存", "desktop.recording.unavailable": "桌面运行时正在连接，暂时无法录制", "desktop.recording.errors.inputMonitoringDenied": "请在系统设置 > 隐私与安全性 > 输入监控中允许 QwenPaw Computer Use，然后重试", "desktop.recording.errors.desktopBusy": "另一个桌面会话正在使用录制功能", "desktop.recording.errors.runtimeUnavailable": "桌面录制服务尚未就绪", "desktop.recording.errors.generic": "录制操作失败", "desktop.recording.learn.intentTitle": "从录制创建 Skill", "desktop.recording.learn.intentAction": "预览发送内容", "desktop.recording.learn.intentDescription": "说明这个工作流最终要完成什么。录制动作只是证据，不会被当作坐标宏直接回放。", "desktop.recording.learn.goal": "工作流目标", "desktop.recording.learn.goalPlaceholder": "例如：在计算器中计算两个用户提供的数字", "desktop.recording.learn.context": "补充说明", "desktop.recording.learn.contextPlaceholder": "可选：说明哪些演示值应成为输入，以及应忽略哪些动作", "desktop.recording.learn.selectEvents": "选择属于工作流的动作", "desktop.recording.learn.noTarget": "无语义控件", "desktop.recording.learn.unknownApp": "未知应用", "desktop.recording.learn.eventType.activate": "点击", "desktop.recording.learn.eventType.drag": "拖动", "desktop.recording.learn.eventType.scroll": "滚动", "desktop.recording.learn.eventType.redacted_input": "脱敏输入", "desktop.recording.learn.consentTitle": "确认分析范围", "desktop.recording.learn.consentAction": "生成草稿", "desktop.recording.learn.externalTransfer": "录制证据将发送给已配置的模型服务商", "desktop.recording.learn.localProcessing": "录制证据将在本地模型中处理", "desktop.recording.learn.consentDescription": "只发送下列已脱敏字段，不发送按键内容、绝对坐标、截图或录制文件路径。授权仅对本次生成有效。", "desktop.recording.learn.provider": "服务商", "desktop.recording.learn.model": "模型", "desktop.recording.learn.events": "原始事件 → 压缩证据", "desktop.recording.learn.fields": "字段范围", "desktop.recording.learn.consent": "我确认使用上述模型和字段范围分析本次录制", "desktop.recording.learn.draftTitle": "审核 Skill 草稿", "desktop.recording.learn.draftAction": "创建并启用 Skill", "desktop.recording.learn.draftDescription": "草稿使用 {{used}} 条源事件，忽略 {{ignored}} 条源事件。创建前可以编辑内容。", "desktop.recording.learn.skillName": "Skill 名称", "desktop.recording.learn.skillContent": "SKILL.md 内容", "desktop.recording.learn.ambiguities": "草稿仍有未解决的歧义", "desktop.recording.learn.addContext": "补充说明", "desktop.recording.learn.created": "Skill {{name}} 已创建并启用", "desktop.recording.learn.failed": "无法从本次录制创建 Skill", "desktop.recording.learn.modelUnavailable": "请先在「模型」设置中配置并选择模型，再重试。录制结果仍然保留。", "feature.description": "录制 → 审核证据 → 生成并保存 Skill。当前版本仅记录事件，不录制视频。", "feature.enabled": "启用 Record & Replay", "feature.platform": "录制需要 macOS 14 或更高版本的 QwenPaw Desktop。", "feature.independence": "停用会结束本插件的录制和未完成的 Learn 请求，保留已有录制与 Skill，不改变 Computer Use。桌面 Replay 需要另行启用可选的 Computer Use 插件。" }, qe = { "desktop.recording.cancel": "キャンセル", "desktop.recording.title": "ワークフロー記録", "desktop.recording.start": "記録", "desktop.recording.authorize": "記録を有効化", "desktop.recording.recording": "記録中", "desktop.recording.paused": "一時停止中", "desktop.recording.pause": "一時停止", "desktop.recording.resume": "再開", "desktop.recording.stop": "停止", "desktop.recording.started": "ワークフローの記録を開始しました", "desktop.recording.permissionRequested": "システム設定で QwenPaw Computer Use の入力監視とアクセシビリティを許可し、もう一度記録をクリックしてください", "desktop.recording.saved": "記録を保存しました", "desktop.recording.unavailable": "デスクトップランタイムへの接続中は記録できません", "desktop.recording.errors.inputMonitoringDenied": "システム設定 > プライバシーとセキュリティ > 入力監視で QwenPaw Computer Use を許可してから再試行してください", "desktop.recording.errors.desktopBusy": "別のデスクトップセッションが記録機能を使用しています", "desktop.recording.errors.runtimeUnavailable": "デスクトップ記録サービスの準備ができていません", "desktop.recording.errors.generic": "記録操作に失敗しました", "desktop.recording.learn.intentTitle": "記録から Skill を作成", "desktop.recording.learn.intentAction": "共有データを確認", "desktop.recording.learn.intentDescription": "ワークフローの目的を説明してください。記録した操作は証拠として扱われ、座標マクロとして再生されません。", "desktop.recording.learn.goal": "ワークフローの目的", "desktop.recording.learn.goalPlaceholder": "例：電卓でユーザー指定の2つの数値を計算する", "desktop.recording.learn.context": "補足情報", "desktop.recording.learn.contextPlaceholder": "任意：再利用する入力と無視する操作を指定", "desktop.recording.learn.selectEvents": "ワークフローに含める操作を選択", "desktop.recording.learn.noTarget": "セマンティックターゲットなし", "desktop.recording.learn.unknownApp": "不明なアプリ", "desktop.recording.learn.eventType.activate": "クリック", "desktop.recording.learn.eventType.drag": "ドラッグ", "desktop.recording.learn.eventType.scroll": "スクロール", "desktop.recording.learn.eventType.redacted_input": "編集済み入力", "desktop.recording.learn.consentTitle": "分析範囲を確認", "desktop.recording.learn.consentAction": "下書きを生成", "desktop.recording.learn.externalTransfer": "記録証拠は設定済みモデルプロバイダーに送信されます", "desktop.recording.learn.localProcessing": "記録証拠はローカルモデルで処理されます", "desktop.recording.learn.consentDescription": "以下の編集済みフィールドのみ送信します。キー内容、絶対座標、スクリーンショット、記録パスは含みません。同意は今回の生成にのみ有効です。", "desktop.recording.learn.provider": "プロバイダー", "desktop.recording.learn.model": "モデル", "desktop.recording.learn.events": "元イベント → 圧縮証拠", "desktop.recording.learn.fields": "フィールド範囲", "desktop.recording.learn.consent": "上記のモデルとフィールドでこの記録を分析することに同意します", "desktop.recording.learn.draftTitle": "Skill 下書きを確認", "desktop.recording.learn.draftAction": "Skill を作成して有効化", "desktop.recording.learn.draftDescription": "下書きは {{used}} 件の元イベントを使用し、{{ignored}} 件を無視します。作成前に編集できます。", "desktop.recording.learn.skillName": "Skill 名", "desktop.recording.learn.skillContent": "SKILL.md の内容", "desktop.recording.learn.ambiguities": "下書きに未解決の曖昧さがあります", "desktop.recording.learn.addContext": "情報を追加", "desktop.recording.learn.created": "Skill {{name}} を作成して有効化しました", "desktop.recording.learn.failed": "この記録から Skill を作成できませんでした" }, Oe = { "desktop.recording.cancel": "Cancelar", "desktop.recording.title": "Gravação de fluxo de trabalho", "desktop.recording.start": "Gravar", "desktop.recording.authorize": "Ativar gravação", "desktop.recording.recording": "Gravando", "desktop.recording.paused": "Pausado", "desktop.recording.pause": "Pausar", "desktop.recording.resume": "Continuar", "desktop.recording.stop": "Parar", "desktop.recording.started": "Gravação do fluxo de trabalho iniciada", "desktop.recording.permissionRequested": "Ative o Monitoramento de Entrada e a Acessibilidade para o QwenPaw Computer Use nos Ajustes do Sistema e clique em Gravar novamente", "desktop.recording.saved": "Gravação salva", "desktop.recording.unavailable": "A gravação fica indisponível enquanto o ambiente de desktop se conecta", "desktop.recording.errors.inputMonitoringDenied": "Permita o QwenPaw Computer Use em Ajustes do Sistema > Privacidade e Segurança > Monitoramento de Entrada e tente novamente", "desktop.recording.errors.desktopBusy": "Outra sessão de desktop já está usando a gravação", "desktop.recording.errors.runtimeUnavailable": "O serviço de gravação do desktop não está pronto", "desktop.recording.errors.generic": "Falha na operação de gravação", "desktop.recording.learn.intentTitle": "Criar Skill da gravação", "desktop.recording.learn.intentAction": "Visualizar dados compartilhados", "desktop.recording.learn.intentDescription": "Descreva o resultado do fluxo. As ações gravadas são evidências e não serão reproduzidas como macro de coordenadas.", "desktop.recording.learn.goal": "Objetivo do fluxo", "desktop.recording.learn.goalPlaceholder": "Exemplo: calcular dois números fornecidos pelo usuário na Calculadora", "desktop.recording.learn.context": "Contexto adicional", "desktop.recording.learn.contextPlaceholder": "Opcional: identifique entradas reutilizáveis e ações a ignorar", "desktop.recording.learn.selectEvents": "Selecione as ações que pertencem ao fluxo", "desktop.recording.learn.noTarget": "Sem alvo semântico", "desktop.recording.learn.unknownApp": "Aplicativo desconhecido", "desktop.recording.learn.eventType.activate": "Ativar", "desktop.recording.learn.eventType.drag": "Arrastar", "desktop.recording.learn.eventType.scroll": "Rolar", "desktop.recording.learn.eventType.redacted_input": "Entrada editada", "desktop.recording.learn.consentTitle": "Confirmar escopo da análise", "desktop.recording.learn.consentAction": "Gerar rascunho", "desktop.recording.learn.externalTransfer": "As evidências serão enviadas ao provedor de modelo configurado", "desktop.recording.learn.localProcessing": "As evidências serão processadas por um modelo local", "desktop.recording.learn.consentDescription": "Somente os campos editados abaixo serão compartilhados. Conteúdo de teclas, coordenadas absolutas, capturas de tela e caminhos ficam de fora. O consentimento vale apenas para esta geração.", "desktop.recording.learn.provider": "Provedor", "desktop.recording.learn.model": "Modelo", "desktop.recording.learn.events": "Eventos de origem → evidência compacta", "desktop.recording.learn.fields": "Escopo dos campos", "desktop.recording.learn.consent": "Aprovo a análise desta gravação com o modelo e os campos acima", "desktop.recording.learn.draftTitle": "Revisar rascunho do Skill", "desktop.recording.learn.draftAction": "Criar e ativar Skill", "desktop.recording.learn.draftDescription": "O rascunho usa {{used}} eventos e ignora {{ignored}}. Você pode editá-lo antes da criação.", "desktop.recording.learn.skillName": "Nome do Skill", "desktop.recording.learn.skillContent": "Conteúdo do SKILL.md", "desktop.recording.learn.ambiguities": "O rascunho contém ambiguidades não resolvidas", "desktop.recording.learn.addContext": "Adicionar contexto", "desktop.recording.learn.created": "O Skill {{name}} foi criado e ativado", "desktop.recording.learn.failed": "Não foi possível criar um Skill desta gravação" }, Ne = { "desktop.recording.cancel": "Отмена", "desktop.recording.title": "Запись рабочего процесса", "desktop.recording.start": "Записать", "desktop.recording.authorize": "Разрешить запись", "desktop.recording.recording": "Идёт запись", "desktop.recording.paused": "Приостановлено", "desktop.recording.pause": "Пауза", "desktop.recording.resume": "Продолжить", "desktop.recording.stop": "Остановить", "desktop.recording.started": "Запись рабочего процесса начата", "desktop.recording.permissionRequested": "Разрешите мониторинг ввода и универсальный доступ для QwenPaw Computer Use в системных настройках, затем снова нажмите «Записать»", "desktop.recording.saved": "Запись сохранена", "desktop.recording.unavailable": "Запись недоступна, пока подключается среда рабочего стола", "desktop.recording.errors.inputMonitoringDenied": "Разрешите QwenPaw Computer Use в разделе Системные настройки > Конфиденциальность и безопасность > Мониторинг ввода и повторите попытку", "desktop.recording.errors.desktopBusy": "Запись уже используется другим сеансом рабочего стола", "desktop.recording.errors.runtimeUnavailable": "Служба записи рабочего стола не готова", "desktop.recording.errors.generic": "Не удалось выполнить операцию записи", "desktop.recording.learn.intentTitle": "Создать Skill из записи", "desktop.recording.learn.intentAction": "Просмотреть передаваемые данные", "desktop.recording.learn.intentDescription": "Опишите результат процесса. Записанные действия служат доказательствами и не воспроизводятся как координатный макрос.", "desktop.recording.learn.goal": "Цель процесса", "desktop.recording.learn.goalPlaceholder": "Например: вычислить два заданных пользователем числа в Калькуляторе", "desktop.recording.learn.context": "Дополнительный контекст", "desktop.recording.learn.contextPlaceholder": "Необязательно: укажите повторно используемые входы и действия, которые нужно игнорировать", "desktop.recording.learn.selectEvents": "Выберите действия рабочего процесса", "desktop.recording.learn.noTarget": "Нет семантической цели", "desktop.recording.learn.unknownApp": "Неизвестное приложение", "desktop.recording.learn.eventType.activate": "Активация", "desktop.recording.learn.eventType.drag": "Перетаскивание", "desktop.recording.learn.eventType.scroll": "Прокрутка", "desktop.recording.learn.eventType.redacted_input": "Обезличенный ввод", "desktop.recording.learn.consentTitle": "Подтвердить область анализа", "desktop.recording.learn.consentAction": "Создать черновик", "desktop.recording.learn.externalTransfer": "Данные записи будут отправлены настроенному поставщику модели", "desktop.recording.learn.localProcessing": "Данные записи будут обработаны локальной моделью", "desktop.recording.learn.consentDescription": "Передаются только перечисленные обезличенные поля. Содержимое клавиш, абсолютные координаты, снимки экрана и пути записи исключены. Согласие действует только для этой генерации.", "desktop.recording.learn.provider": "Поставщик", "desktop.recording.learn.model": "Модель", "desktop.recording.learn.events": "Исходные события → сжатые данные", "desktop.recording.learn.fields": "Область полей", "desktop.recording.learn.consent": "Я разрешаю анализ этой записи указанной моделью и с указанными полями", "desktop.recording.learn.draftTitle": "Проверить черновик Skill", "desktop.recording.learn.draftAction": "Создать и включить Skill", "desktop.recording.learn.draftDescription": "Черновик использует {{used}} событий и игнорирует {{ignored}}. Перед созданием его можно изменить.", "desktop.recording.learn.skillName": "Имя Skill", "desktop.recording.learn.skillContent": "Содержимое SKILL.md", "desktop.recording.learn.ambiguities": "В черновике остались неразрешённые неоднозначности", "desktop.recording.learn.addContext": "Добавить контекст", "desktop.recording.learn.created": "Skill {{name}} создан и включён", "desktop.recording.learn.failed": "Не удалось создать Skill из этой записи" }, Ue = { "desktop.recording.cancel": "Hủy", "desktop.recording.title": "Ghi lại quy trình làm việc", "desktop.recording.start": "Ghi", "desktop.recording.authorize": "Bật ghi", "desktop.recording.recording": "Đang ghi", "desktop.recording.paused": "Đã tạm dừng", "desktop.recording.pause": "Tạm dừng", "desktop.recording.resume": "Tiếp tục", "desktop.recording.stop": "Dừng", "desktop.recording.started": "Đã bắt đầu ghi quy trình làm việc", "desktop.recording.permissionRequested": "Hãy bật Giám sát đầu vào và Trợ năng cho QwenPaw Computer Use trong Cài đặt hệ thống rồi nhấp Ghi lại", "desktop.recording.saved": "Đã lưu bản ghi", "desktop.recording.unavailable": "Không thể ghi trong khi môi trường desktop đang kết nối", "desktop.recording.errors.inputMonitoringDenied": "Hãy cho phép QwenPaw Computer Use trong Cài đặt hệ thống > Quyền riêng tư & Bảo mật > Giám sát đầu vào rồi thử lại", "desktop.recording.errors.desktopBusy": "Một phiên desktop khác đang sử dụng chức năng ghi", "desktop.recording.errors.runtimeUnavailable": "Dịch vụ ghi desktop chưa sẵn sàng", "desktop.recording.errors.generic": "Thao tác ghi thất bại", "desktop.recording.learn.intentTitle": "Tạo Skill từ bản ghi", "desktop.recording.learn.intentAction": "Xem trước dữ liệu chia sẻ", "desktop.recording.learn.intentDescription": "Mô tả kết quả quy trình. Các thao tác đã ghi chỉ là bằng chứng và không được phát lại như macro tọa độ.", "desktop.recording.learn.goal": "Mục tiêu quy trình", "desktop.recording.learn.goalPlaceholder": "Ví dụ: tính hai số do người dùng cung cấp trong Máy tính", "desktop.recording.learn.context": "Ngữ cảnh bổ sung", "desktop.recording.learn.contextPlaceholder": "Tùy chọn: xác định đầu vào có thể tái sử dụng và thao tác cần bỏ qua", "desktop.recording.learn.selectEvents": "Chọn các thao tác thuộc quy trình", "desktop.recording.learn.noTarget": "Không có đích ngữ nghĩa", "desktop.recording.learn.unknownApp": "Ứng dụng không xác định", "desktop.recording.learn.eventType.activate": "Kích hoạt", "desktop.recording.learn.eventType.drag": "Kéo", "desktop.recording.learn.eventType.scroll": "Cuộn", "desktop.recording.learn.eventType.redacted_input": "Đầu vào đã biên tập", "desktop.recording.learn.consentTitle": "Xác nhận phạm vi phân tích", "desktop.recording.learn.consentAction": "Tạo bản nháp", "desktop.recording.learn.externalTransfer": "Bằng chứng ghi sẽ được gửi tới nhà cung cấp mô hình đã cấu hình", "desktop.recording.learn.localProcessing": "Bằng chứng ghi sẽ được xử lý bởi mô hình cục bộ", "desktop.recording.learn.consentDescription": "Chỉ các trường đã được biên tập bên dưới được chia sẻ. Nội dung phím, tọa độ tuyệt đối, ảnh chụp màn hình và đường dẫn bản ghi đều bị loại trừ. Sự đồng ý chỉ áp dụng cho lần tạo này.", "desktop.recording.learn.provider": "Nhà cung cấp", "desktop.recording.learn.model": "Mô hình", "desktop.recording.learn.events": "Sự kiện nguồn → bằng chứng rút gọn", "desktop.recording.learn.fields": "Phạm vi trường", "desktop.recording.learn.consent": "Tôi đồng ý phân tích bản ghi này bằng mô hình và các trường nêu trên", "desktop.recording.learn.draftTitle": "Xem lại bản nháp Skill", "desktop.recording.learn.draftAction": "Tạo và bật Skill", "desktop.recording.learn.draftDescription": "Bản nháp dùng {{used}} sự kiện nguồn và bỏ qua {{ignored}}. Bạn có thể chỉnh sửa trước khi tạo.", "desktop.recording.learn.skillName": "Tên Skill", "desktop.recording.learn.skillContent": "Nội dung SKILL.md", "desktop.recording.learn.ambiguities": "Bản nháp còn điểm chưa rõ", "desktop.recording.learn.addContext": "Thêm ngữ cảnh", "desktop.recording.learn.created": "Skill {{name}} đã được tạo và bật", "desktop.recording.learn.failed": "Không thể tạo Skill từ bản ghi này" }, Ie = { "desktop.recording.cancel": "Batal", "desktop.recording.title": "Perekaman alur kerja", "desktop.recording.start": "Rekam", "desktop.recording.authorize": "Aktifkan perekaman", "desktop.recording.recording": "Merekam", "desktop.recording.paused": "Dijeda", "desktop.recording.pause": "Jeda", "desktop.recording.resume": "Lanjutkan", "desktop.recording.stop": "Hentikan", "desktop.recording.started": "Perekaman alur kerja dimulai", "desktop.recording.permissionRequested": "Aktifkan Pemantauan Input dan Aksesibilitas untuk QwenPaw Computer Use di Pengaturan Sistem, lalu klik Rekam lagi", "desktop.recording.saved": "Rekaman disimpan", "desktop.recording.unavailable": "Perekaman tidak tersedia saat runtime desktop sedang tersambung", "desktop.recording.errors.inputMonitoringDenied": "Izinkan QwenPaw Computer Use di Pengaturan Sistem > Privasi & Keamanan > Pemantauan Input, lalu coba lagi", "desktop.recording.errors.desktopBusy": "Sesi desktop lain sedang menggunakan perekaman", "desktop.recording.errors.runtimeUnavailable": "Layanan perekaman desktop belum siap", "desktop.recording.errors.generic": "Operasi perekaman gagal", "desktop.recording.learn.intentTitle": "Buat Skill dari rekaman", "desktop.recording.learn.intentAction": "Pratinjau data yang dibagikan", "desktop.recording.learn.intentDescription": "Jelaskan hasil alur kerja. Tindakan yang direkam adalah bukti dan tidak diputar ulang sebagai makro koordinat.", "desktop.recording.learn.goal": "Tujuan alur kerja", "desktop.recording.learn.goalPlaceholder": "Contoh: hitung dua angka dari pengguna di Kalkulator", "desktop.recording.learn.context": "Konteks tambahan", "desktop.recording.learn.contextPlaceholder": "Opsional: tentukan input yang dapat digunakan kembali dan tindakan yang diabaikan", "desktop.recording.learn.selectEvents": "Pilih tindakan yang termasuk dalam alur kerja", "desktop.recording.learn.noTarget": "Tidak ada target semantik", "desktop.recording.learn.unknownApp": "Aplikasi tidak dikenal", "desktop.recording.learn.eventType.activate": "Aktifkan", "desktop.recording.learn.eventType.drag": "Seret", "desktop.recording.learn.eventType.scroll": "Gulir", "desktop.recording.learn.eventType.redacted_input": "Input tersunting", "desktop.recording.learn.consentTitle": "Konfirmasi cakupan analisis", "desktop.recording.learn.consentAction": "Buat draf", "desktop.recording.learn.externalTransfer": "Bukti rekaman akan dikirim ke penyedia model yang dikonfigurasi", "desktop.recording.learn.localProcessing": "Bukti rekaman akan diproses oleh model lokal", "desktop.recording.learn.consentDescription": "Hanya kolom tersunting di bawah yang dibagikan. Isi tombol, koordinat absolut, tangkapan layar, dan jalur rekaman tidak disertakan. Persetujuan hanya berlaku untuk pembuatan ini.", "desktop.recording.learn.provider": "Penyedia", "desktop.recording.learn.model": "Model", "desktop.recording.learn.events": "Peristiwa sumber → bukti ringkas", "desktop.recording.learn.fields": "Cakupan kolom", "desktop.recording.learn.consent": "Saya menyetujui analisis rekaman ini dengan model dan kolom di atas", "desktop.recording.learn.draftTitle": "Tinjau draf Skill", "desktop.recording.learn.draftAction": "Buat dan aktifkan Skill", "desktop.recording.learn.draftDescription": "Draf memakai {{used}} peristiwa sumber dan mengabaikan {{ignored}}. Anda dapat mengeditnya sebelum dibuat.", "desktop.recording.learn.skillName": "Nama Skill", "desktop.recording.learn.skillContent": "Isi SKILL.md", "desktop.recording.learn.ambiguities": "Draf masih memiliki ambiguitas", "desktop.recording.learn.addContext": "Tambahkan konteks", "desktop.recording.learn.created": "Skill {{name}} telah dibuat dan diaktifkan", "desktop.recording.learn.failed": "Tidak dapat membuat Skill dari rekaman ini" }, re = {
  en: Be,
  zh: Le,
  ja: qe,
  pt: Oe,
  ru: Ne,
  vi: Ue,
  id: Ie
};
function _e() {
  const d = w.useLocale().toLowerCase().split(/[-_]/)[0], o = re[d] ?? re.en;
  return {
    t: (e, n = {}) => (o[e] ?? re.en[e] ?? e).replace(
      /\{\{(\w+)\}\}/g,
      (p, m) => String(n[m] ?? "")
    )
  };
}
const ze = "_control_pmnk3_1", Me = "_recordingLabel_pmnk3_7", je = "_recordingDot_pmnk3_15", Qe = "_startButton_pmnk3_22", Ke = "_actionButton_pmnk3_23", Ge = "_stopButton_pmnk3_26", $e = "_learnBody_pmnk3_30", He = "_timeline_pmnk3_34", y = {
  control: ze,
  recordingLabel: Me,
  recordingDot: je,
  startButton: Qe,
  actionButton: Ke,
  stopButton: Ge,
  learnBody: $e,
  timeline: He
}, Je = "._control_pmnk3_1{display:inline-flex;align-items:center;gap:4px;min-height:30px}._recordingLabel_pmnk3_7{display:inline-flex;align-items:center;gap:6px;color:#cf1322;font-size:13px;white-space:nowrap}._recordingDot_pmnk3_15{width:7px;height:7px;border-radius:50%;background:#ff4d4f;box-shadow:0 0 0 3px #ff4d4f26}._startButton_pmnk3_22,._actionButton_pmnk3_23{min-width:32px}._stopButton_pmnk3_26{min-width:32px;color:#cf1322!important}._learnBody_pmnk3_30{width:100%;padding-top:8px}._timeline_pmnk3_34{display:flex;width:100%;max-height:240px;flex-direction:column;gap:8px;padding:12px;overflow:auto;border:1px solid rgba(0,0,0,.08);border-radius:8px}", t = w.React, { useCallback: Fe, useEffect: ne, useMemo: Xe, useRef: B, useState: s } = t, {
  Alert: ve,
  Checkbox: ye,
  Descriptions: L,
  Input: M,
  Modal: Ve,
  Space: j,
  Tooltip: te,
  Typography: Q,
  message: T,
  Button: K
} = w.antd, { CaretRightOutlined: We, PauseOutlined: Ye, PlayCircleOutlined: Ze, StopOutlined: er } = w.antdIcons, rr = 2e3, nr = (d) => {
  const o = d instanceof Error ? d.message : String(d);
  return o.includes("input_monitoring_denied") ? "inputMonitoringDenied" : o.includes("desktop_busy") ? "desktopBusy" : o.includes("desktop_runtime_unavailable") ? "runtimeUnavailable" : "generic";
};
function tr() {
  const d = w.useSelectedAgent();
  return /* @__PURE__ */ t.createElement(or, { key: d.id, agentId: d.id });
}
function or({ agentId: d }) {
  const o = Xe(
    () => Re(d),
    [d]
  ), { t: e } = _e(), [n, l] = s(null), [p, m] = s(null), [h, b] = s(!1), [S, A] = s(!1), [g, k] = s("intent"), [x, _] = s(!1), [$, C] = s(""), [D, ie] = s(""), [se, ce] = s(""), [f, le] = s(null), [P, pe] = s(null), [H, J] = s([]), [ge, F] = s(!1), [v, X] = s(null), [V, q] = s(""), [W, R] = s(""), Y = B(/* @__PURE__ */ new Set()), O = B(0), N = B(!1), Z = B(!1), u = B(!0);
  ne(() => (u.current = !0, () => {
    u.current = !1;
  }), []);
  const ke = Fe(async () => {
    if (N.current || Z.current || !u.current) return;
    Z.current = !0;
    const r = O.current;
    try {
      const a = await o.getStatus();
      u.current && r === O.current && (l(a), b(!1));
    } catch {
      u.current && r === O.current && b(!0);
    } finally {
      Z.current = !1;
    }
  }, [o]);
  ne(() => {
    let r = !1;
    const a = async () => {
      r || await ke();
    };
    a();
    const i = window.setInterval(() => void a(), rr);
    return () => {
      r = !0, window.clearInterval(i);
    };
  }, [ke]), ne(() => {
    const r = n == null ? void 0 : n.last_recording;
    S || (r == null ? void 0 : r.state) !== "completed" || r.agent_id !== d || Y.current.has(r.recording_id) || (Y.current.add(r.recording_id), o.recoverDraft(r.recording_id).then((a) => {
      a === null || !u.current || (C(a.recording_id), X(a), q(a.name), R(a.content), k("draft"), A(!0));
    }).catch(() => {
      Y.current.delete(r.recording_id);
    }));
  }, [S, n == null ? void 0 : n.last_recording, d, o]);
  const ee = async (r) => {
    if (!N.current) {
      N.current = !0, O.current += 1, m(r);
      try {
        if (r === "start" && ((n == null ? void 0 : n.input_monitoring) === "required" || (n == null ? void 0 : n.accessibility) === "required")) {
          const i = await o.requestPermission();
          if (!u.current) return;
          if (l(i), i.input_monitoring !== "granted") {
            T.info(e("desktop.recording.permissionRequested"));
            return;
          }
          i.accessibility !== "granted" && T.info(e("desktop.recording.permissionRequested"));
        }
        const a = await o[r]();
        if (!u.current) return;
        if (l(a), b(!1), r === "start")
          T.success(e("desktop.recording.started"));
        else if (r === "stop") {
          T.success(e("desktop.recording.saved"));
          const i = a.last_recording;
          (i == null ? void 0 : i.state) === "completed" && i.agent_id === d && i.event_count > 0 && u.current && (C(i.recording_id), k("intent"), A(!0), _(!0), o.reviewRecording(i.recording_id).then((I) => {
            pe(I), J(
              I.events.map((z) => z.evidence_id)
            );
          }).catch(() => {
            T.error(e("desktop.recording.learn.failed"));
          }).finally(() => _(!1)));
        }
      } catch (a) {
        u.current && (b(!0), T.error(e(`desktop.recording.errors.${nr(a)}`)));
      } finally {
        N.current = !1, u.current && m(null);
      }
    }
  }, ue = () => {
    A(!1), k("intent"), _(!1), C(""), ie(""), ce(""), le(null), pe(null), J([]), F(!1), X(null), q(""), R("");
  }, Se = (r) => {
    q(r), R(
      (a) => a.replace(/^name:.*$/m, `name: ${r}`)
    );
  }, xe = async () => {
    if (!x) {
      _(!0);
      try {
        if (g === "intent") {
          const r = ((P == null ? void 0 : P.events) ?? []).filter((i) => H.includes(i.evidence_id)).flatMap((i) => i.source_sequences), a = await o.prepareLearn({
            recording_id: $,
            goal: D.trim(),
            confirmed_context: se.trim(),
            selected_sequences: r
          });
          le(a), F(!1), k("consent");
        } else if (g === "consent" && f !== null) {
          const r = await o.generateDraft(
            f.consent_token
          );
          X(r), q(r.name), R(r.content), k("draft");
        } else if (g === "draft" && v !== null) {
          const r = await o.materializeSkill({
            draft_id: v.draft_id,
            name: V.trim(),
            content: W
          });
          T.success(
            e("desktop.recording.learn.created", { name: r.name })
          ), ue();
        }
      } catch (r) {
        const a = r instanceof Error && ["learn_model_unavailable", "learn_provider_unavailable"].includes(
          r.message
        );
        T.error(
          e(
            a ? "desktop.recording.learn.modelUnavailable" : "desktop.recording.learn.failed"
          )
        );
      } finally {
        _(!1);
      }
    }
  }, me = (n == null ? void 0 : n.available) === !0 && !h, U = (n == null ? void 0 : n.state) ?? "idle", Ce = U === "recording", E = U === "paused", Pe = e(me ? "desktop.recording.title" : "desktop.recording.unavailable"), he = (n == null ? void 0 : n.input_monitoring) === "required" || (n == null ? void 0 : n.accessibility) === "required" ? e("desktop.recording.authorize") : e("desktop.recording.start"), Ee = !Ce && !E ? /* @__PURE__ */ t.createElement(te, { title: Pe }, /* @__PURE__ */ t.createElement("span", null, /* @__PURE__ */ t.createElement(
    K,
    {
      type: "text",
      size: "small",
      icon: /* @__PURE__ */ t.createElement(Ze, null),
      className: y.startButton,
      disabled: !me,
      loading: p === "start" || n === null,
      "aria-label": he,
      onClick: () => void ee("start")
    },
    he
  ))) : /* @__PURE__ */ t.createElement(
    "div",
    {
      className: y.control,
      role: "group",
      "aria-label": e("desktop.recording.title"),
      "data-state": U
    },
    /* @__PURE__ */ t.createElement("span", { className: y.recordingLabel, role: "status" }, /* @__PURE__ */ t.createElement("span", { className: y.recordingDot, "aria-hidden": "true" }), e(E ? "desktop.recording.paused" : "desktop.recording.recording")),
    /* @__PURE__ */ t.createElement(j, { size: 0 }, /* @__PURE__ */ t.createElement(
      te,
      {
        title: e(E ? "desktop.recording.resume" : "desktop.recording.pause")
      },
      /* @__PURE__ */ t.createElement(
        K,
        {
          type: "text",
          size: "small",
          className: y.actionButton,
          icon: E ? /* @__PURE__ */ t.createElement(We, null) : /* @__PURE__ */ t.createElement(Ye, null),
          loading: p === "pause" || p === "resume",
          disabled: p !== null,
          "aria-label": e(E ? "desktop.recording.resume" : "desktop.recording.pause"),
          onClick: () => void ee(E ? "resume" : "pause")
        }
      )
    ), /* @__PURE__ */ t.createElement(te, { title: e("desktop.recording.stop") }, /* @__PURE__ */ t.createElement(
      K,
      {
        type: "text",
        size: "small",
        className: y.stopButton,
        icon: /* @__PURE__ */ t.createElement(er, null),
        loading: p === "stop",
        disabled: p !== null,
        "aria-label": e("desktop.recording.stop"),
        onClick: () => void ee("stop")
      }
    )))
  ), Ae = g === "intent" && (!D.trim() || P === null || H.length === 0) || g === "consent" && !ge || g === "draft" && (!V.trim() || !W.trim() || (v == null ? void 0 : v.needs_confirmation) === !0);
  return /* @__PURE__ */ t.createElement(t.Fragment, null, /* @__PURE__ */ t.createElement("style", null, Je), Ee, U === "failed" && /* @__PURE__ */ t.createElement(Q.Text, { type: "danger", role: "alert" }, e("desktop.recording.errors.generic")), /* @__PURE__ */ t.createElement(
    Ve,
    {
      open: S,
      title: e(`desktop.recording.learn.${g}Title`),
      okText: e(`desktop.recording.learn.${g}Action`),
      cancelText: e("desktop.recording.cancel"),
      confirmLoading: x,
      okButtonProps: { disabled: Ae },
      onOk: () => void xe(),
      onCancel: ue,
      width: 720,
      destroyOnHidden: !0
    },
    g === "intent" && /* @__PURE__ */ t.createElement(
      j,
      {
        direction: "vertical",
        size: "middle",
        className: y.learnBody
      },
      /* @__PURE__ */ t.createElement(Q.Text, null, e("desktop.recording.learn.intentDescription")),
      /* @__PURE__ */ t.createElement(
        M.TextArea,
        {
          value: D,
          rows: 3,
          maxLength: 500,
          showCount: !0,
          "aria-label": e("desktop.recording.learn.goal"),
          placeholder: e("desktop.recording.learn.goalPlaceholder"),
          onChange: (r) => ie(r.target.value)
        }
      ),
      /* @__PURE__ */ t.createElement(
        M.TextArea,
        {
          value: se,
          rows: 2,
          maxLength: 2e3,
          "aria-label": e("desktop.recording.learn.context"),
          placeholder: e("desktop.recording.learn.contextPlaceholder"),
          onChange: (r) => ce(r.target.value)
        }
      ),
      P !== null && /* @__PURE__ */ t.createElement("div", { className: y.timeline }, /* @__PURE__ */ t.createElement(Q.Text, { strong: !0 }, e("desktop.recording.learn.selectEvents")), P.events.map((r) => {
        const a = r.locator.name || r.locator.identifier || r.locator.role || e("desktop.recording.learn.noTarget"), i = r.locator.app_name || r.locator.bundle_id || e("desktop.recording.learn.unknownApp");
        return /* @__PURE__ */ t.createElement(
          ye,
          {
            key: r.evidence_id,
            checked: H.includes(r.evidence_id),
            onChange: (I) => J(
              (z) => I.target.checked ? [...z, r.evidence_id] : z.filter(
                (De) => De !== r.evidence_id
              )
            )
          },
          i,
          " · ",
          a,
          " ·",
          " ",
          e(`desktop.recording.learn.eventType.${r.type}`),
          " (",
          r.source_sequences.length,
          ")"
        );
      }))
    ),
    g === "consent" && f !== null && /* @__PURE__ */ t.createElement(
      j,
      {
        direction: "vertical",
        size: "middle",
        className: y.learnBody
      },
      /* @__PURE__ */ t.createElement(
        ve,
        {
          type: f.external_transfer ? "warning" : "info",
          showIcon: !0,
          message: f.external_transfer ? e("desktop.recording.learn.externalTransfer") : e("desktop.recording.learn.localProcessing"),
          description: e("desktop.recording.learn.consentDescription")
        }
      ),
      /* @__PURE__ */ t.createElement(L, { size: "small", column: 1, bordered: !0 }, /* @__PURE__ */ t.createElement(L.Item, { label: e("desktop.recording.learn.provider") }, f.model_target.provider_id), /* @__PURE__ */ t.createElement(L.Item, { label: e("desktop.recording.learn.model") }, f.model_target.model), /* @__PURE__ */ t.createElement(L.Item, { label: e("desktop.recording.learn.events") }, f.selected_event_count, " → ", f.evidence_event_count), /* @__PURE__ */ t.createElement(L.Item, { label: e("desktop.recording.learn.fields") }, f.field_scope.join(", "))),
      /* @__PURE__ */ t.createElement(
        ye,
        {
          checked: ge,
          onChange: (r) => F(r.target.checked)
        },
        e("desktop.recording.learn.consent")
      )
    ),
    g === "draft" && v !== null && /* @__PURE__ */ t.createElement(
      j,
      {
        direction: "vertical",
        size: "middle",
        className: y.learnBody
      },
      v.needs_confirmation && /* @__PURE__ */ t.createElement(
        ve,
        {
          type: "warning",
          showIcon: !0,
          message: e("desktop.recording.learn.ambiguities"),
          description: v.ambiguities.join("; "),
          action: /* @__PURE__ */ t.createElement(K, { size: "small", onClick: () => k("intent") }, e("desktop.recording.learn.addContext"))
        }
      ),
      /* @__PURE__ */ t.createElement(Q.Text, null, e("desktop.recording.learn.draftDescription", {
        used: v.source_sequences.length,
        ignored: v.ignored_source_sequences.length
      })),
      /* @__PURE__ */ t.createElement(
        M,
        {
          value: V,
          maxLength: 64,
          "aria-label": e("desktop.recording.learn.skillName"),
          onChange: (r) => Se(r.target.value)
        }
      ),
      /* @__PURE__ */ t.createElement(
        M.TextArea,
        {
          value: W,
          rows: 16,
          maxLength: 1e5,
          "aria-label": e("desktop.recording.learn.skillContent"),
          onChange: (r) => R(r.target.value)
        }
      )
    )
  ));
}
const c = w.React, { Alert: be, Space: we, Switch: ar, Typography: oe, message: dr } = w.antd;
function Te({ page: d = !1 }) {
  const { t: o } = _e(), [e, n] = c.useState(null), [l, p] = c.useState(!1), [m, h] = c.useState(!1), b = c.useRef(0), S = c.useRef(!1);
  c.useEffect(() => {
    let k = !1, x = !1;
    const _ = async () => {
      if (x || S.current) return;
      x = !0;
      const C = b.current;
      try {
        const D = await fe.get();
        !k && C === b.current && (n(D), p(!1));
      } catch {
        !k && C === b.current && p(!0);
      } finally {
        x = !1;
      }
    };
    _();
    const $ = window.setInterval(() => void _(), 2e3);
    return () => {
      k = !0, window.clearInterval($);
    };
  }, []);
  const A = async (k) => {
    b.current += 1, S.current = !0, h(!0);
    try {
      n(await fe.set(k)), p(!1);
    } catch {
      p(!0), dr.error(o("desktop.recording.errors.generic"));
    } finally {
      S.current = !1, h(!1);
    }
  }, g = e != null && e.enabled && e.supported_platform && !l ? /* @__PURE__ */ c.createElement(tr, null) : null;
  return d ? /* @__PURE__ */ c.createElement(we, { direction: "vertical", style: { width: "100%", padding: 24 } }, /* @__PURE__ */ c.createElement(oe.Title, { level: 3 }, "Record & Replay"), /* @__PURE__ */ c.createElement(oe.Paragraph, null, o("feature.description")), l && /* @__PURE__ */ c.createElement(be, { type: "error", message: o("desktop.recording.errors.generic") }), e && !e.supported_platform && /* @__PURE__ */ c.createElement(be, { type: "info", message: o("feature.platform") }), /* @__PURE__ */ c.createElement(we, null, /* @__PURE__ */ c.createElement(
    ar,
    {
      checked: (e == null ? void 0 : e.enabled) ?? !1,
      loading: m || e === null,
      disabled: l || (e == null ? void 0 : e.supported_platform) !== !0,
      "aria-label": o("feature.enabled"),
      onChange: (k) => void A(k)
    }
  ), o("feature.enabled")), /* @__PURE__ */ c.createElement(oe.Paragraph, { type: "secondary" }, o("feature.independence")), g) : g;
}
const de = w.React;
G.chat.rightHeader.add("record-and-replay", /* @__PURE__ */ de.createElement(Te, null), {
  id: "recording-controls",
  order: 60
});
G.route.add("record-and-replay", {
  id: "record-and-replay.settings",
  path: "/plugin/record-and-replay",
  component: () => /* @__PURE__ */ de.createElement(Te, { page: !0 })
});
G.menu.add("record-and-replay", {
  id: "record-and-replay.settings",
  location: "primary.settings",
  label: "Record & Replay",
  icon: /* @__PURE__ */ de.createElement("span", null, "⏺"),
  route: "record-and-replay.settings",
  order: 44
});
