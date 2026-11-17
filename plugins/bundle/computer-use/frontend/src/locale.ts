export type ComputerUseLocale =
  | "en"
  | "zh"
  | "ja"
  | "ru"
  | "pt-BR"
  | "id"
  | "vi";

const messages = {
  en: {
    routeLabel: "Computer Use",
    title: "Computer Use",
    ready: "Runtime ready",
    unavailable: "Runtime unavailable",
    refresh: "Refresh",
    stop: "Stop automation",
    feature: "Enable Computer Use",
    enabledMsg: "Computer Use enabled",
    disabledMsg: "Computer Use disabled; running automation stopped",
    application: "Application",
    applicationId: "Application ID",
    revoke: "Revoke access",
    revokeConfirm: "Revoke this application access?",
    empty: "No applications are always allowed.",
    approvalTitle: "Application access",
    unknownApplication: "Unknown application",
    risk: "Risk",
    deny: "Deny app for this session",
    allowSession: "Allow app for this session",
    allowAlways: "Always allow this app",
    approvalHint:
      "Allow or deny access to this application for the current session. Allowing lets the pending operation continue.",
    persistentHint:
      "Always allow saves application access for all agents in this QwenPaw installation until revoked in Computer Use → Access management. Revoking it does not clear existing session decisions or stop running operations.",
    submitting: "Submitting decision…",
    waiting: "Waiting for confirmation",
    expired: "Request expired",
    unavailableRequest: "Request already handled or expired",
    submitUnconfirmed:
      "Could not confirm the decision. Refresh the page to check the request before trying again.",
    submitRejected: "The server rejected this decision",
    failed: "Action failed.",
    accessManagement: "Access management",
    version: "Version",
    decision: {
      deny: "App access denied for this session.",
      session: "Access allowed for this session.",
      always: "Application always allowed.",
    },
  },
  zh: {
    routeLabel: "电脑操作",
    title: "电脑操作",
    ready: "运行环境已就绪",
    unavailable: "运行环境不可用",
    refresh: "刷新",
    stop: "停止自动化",
    feature: "启用电脑操作",
    enabledMsg: "已启用电脑操作",
    disabledMsg: "已关闭电脑操作，正在进行的自动化已停止",
    application: "应用",
    applicationId: "应用标识",
    revoke: "撤销授权",
    revokeConfirm: "撤销这个应用的授权？",
    empty: "暂未允许任何应用长期访问。",
    approvalTitle: "应用访问请求",
    unknownApplication: "未知应用",
    risk: "风险",
    deny: "本会话拒绝此应用",
    allowSession: "本会话允许此应用",
    allowAlways: "长期允许此应用",
    approvalHint:
      "在当前会话内允许或拒绝访问此应用。允许后将继续待处理的操作。",
    persistentHint:
      "长期授权会保存此应用的访问权限，供当前 QwenPaw 安装下的所有 Agent 使用，直到在“电脑操作 → 授权管理”中撤销。撤销不会清除已有会话决定或停止正在运行的操作。",
    submitting: "正在提交决定…",
    waiting: "等待确认",
    expired: "请求已过期",
    unavailableRequest: "请求已处理或已失效",
    submitUnconfirmed: "未能确认提交结果，请刷新页面核对请求状态后再操作。",
    submitRejected: "服务器拒绝了此决定",
    failed: "操作失败。",
    accessManagement: "授权管理",
    version: "版本",
    decision: {
      deny: "已拒绝本会话对此应用的访问。",
      session: "已允许本次会话访问。",
      always: "已始终允许该应用。",
    },
  },
  ja: {
    routeLabel: "コンピューター操作",
    title: "コンピューター操作",
    ready: "実行環境の準備完了",
    unavailable: "実行環境を利用できません",
    refresh: "更新",
    stop: "自動操作を停止",
    feature: "コンピューター操作を有効にする",
    enabledMsg: "コンピューター操作を有効にしました",
    disabledMsg: "コンピューター操作を無効にし、実行中の自動操作を停止しました",
    application: "アプリ",
    applicationId: "アプリID",
    revoke: "アクセス権を解除",
    revokeConfirm: "このアプリのアクセス権を解除しますか？",
    empty: "常に許可されているアプリはありません。",
    approvalTitle: "アプリへのアクセス",
    unknownApplication: "不明なアプリ",
    risk: "リスク",
    allowAlways: "このアプリを常に許可",
    approvalHint:
      "このセッションでアプリへのアクセスを許可または拒否します。許可すると保留中の操作を続行します。",
    persistentHint:
      "常に許可すると、このQwenPaw環境内のすべてのエージェントにアプリへのアクセス権が保存されます。「コンピューター操作 → アクセス管理」で解除するまで有効です。解除しても既存のセッションの決定は消去されず、実行中の操作も停止しません。",
    failed: "操作に失敗しました。",
    accessManagement: "アクセス管理",
    version: "バージョン",
    decision: {
      deny: "このセッションでのアプリへのアクセスを拒否しました。",
      session: "このセッションでのアクセスを許可しました。",
      always: "アプリを常に許可しました。",
    },
    deny: "このセッションでアプリを拒否",
    allowSession: "このセッションでアプリを許可",
    submitting: "決定を送信中…",
    waiting: "確認待ち",
    expired: "リクエストの有効期限が切れました",
    unavailableRequest: "リクエストは処理済み、または無効です",
    submitUnconfirmed:
      "送信結果を確認できませんでした。ページを更新してリクエストの状態を確認してから再試行してください。",
    submitRejected: "サーバーがこの決定を拒否しました",
  },
  ru: {
    routeLabel: "Управление компьютером",
    title: "Управление компьютером",
    ready: "Среда выполнения готова",
    unavailable: "Среда выполнения недоступна",
    refresh: "Обновить",
    stop: "Остановить автоматизацию",
    feature: "Включить управление компьютером",
    enabledMsg: "Управление компьютером включено",
    disabledMsg:
      "Управление компьютером отключено; текущая автоматизация остановлена",
    application: "Приложение",
    applicationId: "ID приложения",
    revoke: "Отозвать доступ",
    revokeConfirm: "Отозвать доступ к этому приложению?",
    empty: "Нет приложений с постоянным разрешением.",
    approvalTitle: "Доступ к приложению",
    unknownApplication: "Неизвестное приложение",
    risk: "Риск",
    allowAlways: "Всегда разрешать это приложение",
    approvalHint:
      "Разрешить или запретить доступ к этому приложению на время текущего сеанса. Разрешение продолжит ожидающую операцию.",
    persistentHint:
      "Постоянное разрешение сохраняет доступ к приложению для всех агентов этой установки QwenPaw до отзыва в разделе «Управление компьютером → Управление доступом». Отзыв не сбрасывает существующие решения сеансов и не останавливает выполняемые операции.",
    failed: "Действие не выполнено.",
    accessManagement: "Управление доступом",
    version: "Версия",
    decision: {
      deny: "Доступ к приложению запрещён на время сеанса.",
      session: "Доступ разрешён на время сеанса.",
      always: "Приложению предоставлен постоянный доступ.",
    },
    deny: "Запретить приложение на время сеанса",
    allowSession: "Разрешить приложение на время сеанса",
    submitting: "Отправка решения…",
    waiting: "Ожидание подтверждения",
    expired: "Срок действия запроса истёк",
    unavailableRequest: "Запрос уже обработан или недействителен",
    submitUnconfirmed:
      "Не удалось подтвердить результат отправки. Обновите страницу и проверьте состояние запроса перед повторной попыткой.",
    submitRejected: "Сервер отклонил это решение",
  },
  "pt-BR": {
    routeLabel: "Uso do computador",
    title: "Uso do computador",
    ready: "Ambiente de execução pronto",
    unavailable: "Ambiente de execução indisponível",
    refresh: "Atualizar",
    stop: "Parar automação",
    feature: "Ativar uso do computador",
    enabledMsg: "Uso do computador ativado",
    disabledMsg:
      "Uso do computador desativado; automação em andamento interrompida",
    application: "Aplicativo",
    applicationId: "ID do aplicativo",
    revoke: "Revogar acesso",
    revokeConfirm: "Revogar o acesso a este aplicativo?",
    empty: "Nenhum aplicativo tem permissão permanente.",
    approvalTitle: "Acesso ao aplicativo",
    unknownApplication: "Aplicativo desconhecido",
    risk: "Risco",
    allowAlways: "Sempre permitir este aplicativo",
    approvalHint:
      "Permita ou bloqueie o acesso a este aplicativo na sessão atual. Ao permitir, a operação pendente continuará.",
    persistentHint:
      "A permissão permanente salva o acesso ao aplicativo para todos os agentes desta instalação do QwenPaw até sua revogação em Uso do computador → Gerenciamento de acesso. A revogação não apaga decisões existentes das sessões nem interrompe operações em andamento.",
    failed: "Falha na ação.",
    accessManagement: "Gerenciamento de acesso",
    version: "Versão",
    decision: {
      deny: "Acesso ao aplicativo bloqueado nesta sessão.",
      session: "Acesso permitido nesta sessão.",
      always: "Aplicativo permitido permanentemente.",
    },
    deny: "Bloquear aplicativo nesta sessão",
    allowSession: "Permitir aplicativo nesta sessão",
    submitting: "Enviando decisão…",
    waiting: "Aguardando confirmação",
    expired: "Solicitação expirada",
    unavailableRequest: "Solicitação já processada ou inválida",
    submitUnconfirmed:
      "Não foi possível confirmar o resultado do envio. Atualize a página e verifique o estado da solicitação antes de tentar novamente.",
    submitRejected: "O servidor rejeitou esta decisão",
  },
  id: {
    routeLabel: "Penggunaan Komputer",
    title: "Penggunaan Komputer",
    ready: "Lingkungan eksekusi siap",
    unavailable: "Lingkungan eksekusi tidak tersedia",
    refresh: "Muat ulang",
    stop: "Hentikan otomatisasi",
    feature: "Aktifkan Penggunaan Komputer",
    enabledMsg: "Penggunaan Komputer diaktifkan",
    disabledMsg:
      "Penggunaan Komputer dinonaktifkan; otomatisasi yang berjalan dihentikan",
    application: "Aplikasi",
    applicationId: "ID aplikasi",
    revoke: "Cabut akses",
    revokeConfirm: "Cabut akses aplikasi ini?",
    empty: "Belum ada aplikasi yang selalu diizinkan.",
    approvalTitle: "Akses aplikasi",
    unknownApplication: "Aplikasi tidak dikenal",
    risk: "Risiko",
    allowAlways: "Selalu izinkan aplikasi ini",
    approvalHint:
      "Izinkan atau blokir akses ke aplikasi ini selama sesi saat ini. Mengizinkan akses akan melanjutkan operasi yang tertunda.",
    persistentHint:
      "Izin permanen menyimpan akses aplikasi untuk semua agen dalam instalasi QwenPaw ini hingga dicabut melalui Penggunaan Komputer → Pengelolaan akses. Pencabutan tidak menghapus keputusan sesi yang ada atau menghentikan operasi yang sedang berjalan.",
    failed: "Tindakan gagal.",
    accessManagement: "Pengelolaan akses",
    version: "Versi",
    decision: {
      deny: "Akses aplikasi diblokir selama sesi ini.",
      session: "Akses diizinkan selama sesi ini.",
      always: "Aplikasi selalu diizinkan.",
    },
    deny: "Blokir aplikasi selama sesi ini",
    allowSession: "Izinkan aplikasi selama sesi ini",
    submitting: "Mengirim keputusan…",
    waiting: "Menunggu konfirmasi",
    expired: "Permintaan kedaluwarsa",
    unavailableRequest: "Permintaan sudah ditangani atau tidak berlaku",
    submitUnconfirmed:
      "Hasil pengiriman belum dapat dikonfirmasi. Muat ulang halaman dan periksa status permintaan sebelum mencoba lagi.",
    submitRejected: "Server menolak keputusan ini",
  },
  vi: {
    routeLabel: "Sử dụng máy tính",
    title: "Sử dụng máy tính",
    ready: "Môi trường thực thi đã sẵn sàng",
    unavailable: "Môi trường thực thi không khả dụng",
    refresh: "Làm mới",
    stop: "Dừng tự động hóa",
    feature: "Bật Sử dụng máy tính",
    enabledMsg: "Đã bật Sử dụng máy tính",
    disabledMsg: "Đã tắt Sử dụng máy tính; tự động hóa đang chạy đã dừng",
    application: "Ứng dụng",
    applicationId: "ID ứng dụng",
    revoke: "Thu hồi quyền truy cập",
    revokeConfirm: "Thu hồi quyền truy cập ứng dụng này?",
    empty: "Chưa có ứng dụng nào được cho phép vĩnh viễn.",
    approvalTitle: "Quyền truy cập ứng dụng",
    unknownApplication: "Ứng dụng không xác định",
    risk: "Rủi ro",
    allowAlways: "Luôn cho phép ứng dụng này",
    approvalHint:
      "Cho phép hoặc chặn quyền truy cập ứng dụng này trong phiên hiện tại. Khi được cho phép, thao tác đang chờ sẽ tiếp tục.",
    persistentHint:
      "Quyền truy cập vĩnh viễn được lưu cho tất cả Agent trong bản cài đặt QwenPaw này cho đến khi bị thu hồi tại Sử dụng máy tính → Quản lý quyền truy cập. Thu hồi không xóa các quyết định hiện có của phiên hoặc dừng thao tác đang chạy.",
    failed: "Thao tác thất bại.",
    accessManagement: "Quản lý quyền truy cập",
    version: "Phiên bản",
    decision: {
      deny: "Đã chặn quyền truy cập ứng dụng trong phiên này.",
      session: "Đã cho phép truy cập trong phiên này.",
      always: "Đã cho phép ứng dụng vĩnh viễn.",
    },
    deny: "Chặn ứng dụng trong phiên này",
    allowSession: "Cho phép ứng dụng trong phiên này",
    submitting: "Đang gửi quyết định…",
    waiting: "Đang chờ xác nhận",
    expired: "Yêu cầu đã hết hạn",
    unavailableRequest: "Yêu cầu đã được xử lý hoặc không còn hiệu lực",
    submitUnconfirmed:
      "Không thể xác nhận kết quả gửi. Hãy tải lại trang và kiểm tra trạng thái yêu cầu trước khi thử lại.",
    submitRejected: "Máy chủ đã từ chối quyết định này",
  },
} as const;

export type MessageKey = keyof typeof messages.en;
export type DecisionKey = `decision.${keyof typeof messages.en.decision}`;

export function resolveLocale(
  value: string | null | undefined,
): ComputerUseLocale {
  const language = value?.toLowerCase().split("-")[0];
  if (language === "pt") return "pt-BR";
  if (
    language === "zh" ||
    language === "ja" ||
    language === "ru" ||
    language === "id" ||
    language === "vi"
  ) {
    return language;
  }
  return "en";
}

export function t(
  selectedLocale: ComputerUseLocale,
  key: MessageKey | DecisionKey,
): string {
  if (key.startsWith("decision.")) {
    const decision = key.slice(
      "decision.".length,
    ) as keyof typeof messages.en.decision;
    return messages[selectedLocale].decision[decision];
  }
  return messages[selectedLocale][key as MessageKey] as string;
}
