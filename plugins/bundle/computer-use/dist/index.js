const L = {
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
    revokeHint: "This removes only the saved application grant for this QwenPaw installation. Existing session decisions and running operations are not affected.",
    cancel: "Cancel",
    empty: "No applications are always allowed.",
    approvalTitle: "Application access",
    unknownApplication: "Unknown application",
    risk: "Risk",
    deny: "Deny app for this session",
    allowSession: "Allow app for this session",
    allowAlways: "Always allow this app",
    approvalHint: "Allow or deny access to this application for the current session. Allowing lets the pending operation continue.",
    persistentHint: "Always allow saves application access for all agents in this QwenPaw installation until revoked in Computer Use → Access management. Revoking it does not clear existing session decisions or stop running operations.",
    submitting: "Submitting decision…",
    waiting: "Waiting for confirmation",
    expired: "Request expired",
    unavailableRequest: "Request already handled or expired",
    submitUnconfirmed: "Could not confirm the decision. Check the request status before trying again.",
    checkStatus: "Check request status",
    checkStatusFailed: "Could not check the request status. Try again.",
    submitRejected: "The server rejected this decision",
    failed: "Action failed.",
    accessManagement: "Access management",
    version: "Version",
    decision: {
      deny: "App access denied for this session.",
      session: "Access allowed for this session.",
      always: "Application always allowed."
    }
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
    revokeHint: "仅移除当前 QwenPaw 安装中保存的此应用长期授权，不会清除已有会话决定或停止正在运行的操作。",
    cancel: "取消",
    empty: "暂未允许任何应用长期访问。",
    approvalTitle: "应用访问请求",
    unknownApplication: "未知应用",
    risk: "风险",
    deny: "本会话拒绝此应用",
    allowSession: "本会话允许此应用",
    allowAlways: "长期允许此应用",
    approvalHint: "在当前会话内允许或拒绝访问此应用。允许后将继续待处理的操作。",
    persistentHint: "长期授权会保存此应用的访问权限，供当前 QwenPaw 安装下的所有 Agent 使用，直到在“电脑操作 → 授权管理”中撤销。撤销不会清除已有会话决定或停止正在运行的操作。",
    submitting: "正在提交决定…",
    waiting: "等待确认",
    expired: "请求已过期",
    unavailableRequest: "请求已处理或已失效",
    submitUnconfirmed: "未能确认提交结果，请检查请求状态后再操作。",
    checkStatus: "检查请求状态",
    checkStatusFailed: "无法检查请求状态，请重试。",
    submitRejected: "服务器拒绝了此决定",
    failed: "操作失败。",
    accessManagement: "授权管理",
    version: "版本",
    decision: {
      deny: "已拒绝本会话对此应用的访问。",
      session: "已允许本次会话访问。",
      always: "已始终允许该应用。"
    }
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
    revokeHint: "このQwenPaw環境に保存されたアプリの許可のみを削除します。既存のセッションの決定や実行中の操作には影響しません。",
    cancel: "キャンセル",
    empty: "常に許可されているアプリはありません。",
    approvalTitle: "アプリへのアクセス",
    unknownApplication: "不明なアプリ",
    risk: "リスク",
    allowAlways: "このアプリを常に許可",
    approvalHint: "このセッションでアプリへのアクセスを許可または拒否します。許可すると保留中の操作を続行します。",
    persistentHint: "常に許可すると、このQwenPaw環境内のすべてのエージェントにアプリへのアクセス権が保存されます。「コンピューター操作 → アクセス管理」で解除するまで有効です。解除しても既存のセッションの決定は消去されず、実行中の操作も停止しません。",
    failed: "操作に失敗しました。",
    accessManagement: "アクセス管理",
    version: "バージョン",
    decision: {
      deny: "このセッションでのアプリへのアクセスを拒否しました。",
      session: "このセッションでのアクセスを許可しました。",
      always: "アプリを常に許可しました。"
    },
    deny: "このセッションでアプリを拒否",
    allowSession: "このセッションでアプリを許可",
    submitting: "決定を送信中…",
    waiting: "確認待ち",
    expired: "リクエストの有効期限が切れました",
    unavailableRequest: "リクエストは処理済み、または無効です",
    submitUnconfirmed: "送信結果を確認できませんでした。リクエストの状態を確認してから再試行してください。",
    checkStatus: "リクエストの状態を確認",
    checkStatusFailed: "リクエストの状態を確認できませんでした。もう一度お試しください。",
    submitRejected: "サーバーがこの決定を拒否しました"
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
    disabledMsg: "Управление компьютером отключено; текущая автоматизация остановлена",
    application: "Приложение",
    applicationId: "ID приложения",
    revoke: "Отозвать доступ",
    revokeConfirm: "Отозвать доступ к этому приложению?",
    revokeHint: "Будет удалено только сохранённое разрешение приложения в этой установке QwenPaw. Существующие решения сеансов и выполняемые операции не изменятся.",
    cancel: "Отмена",
    empty: "Нет приложений с постоянным разрешением.",
    approvalTitle: "Доступ к приложению",
    unknownApplication: "Неизвестное приложение",
    risk: "Риск",
    allowAlways: "Всегда разрешать это приложение",
    approvalHint: "Разрешить или запретить доступ к этому приложению на время текущего сеанса. Разрешение продолжит ожидающую операцию.",
    persistentHint: "Постоянное разрешение сохраняет доступ к приложению для всех агентов этой установки QwenPaw до отзыва в разделе «Управление компьютером → Управление доступом». Отзыв не сбрасывает существующие решения сеансов и не останавливает выполняемые операции.",
    failed: "Действие не выполнено.",
    accessManagement: "Управление доступом",
    version: "Версия",
    decision: {
      deny: "Доступ к приложению запрещён на время сеанса.",
      session: "Доступ разрешён на время сеанса.",
      always: "Приложению предоставлен постоянный доступ."
    },
    deny: "Запретить приложение на время сеанса",
    allowSession: "Разрешить приложение на время сеанса",
    submitting: "Отправка решения…",
    waiting: "Ожидание подтверждения",
    expired: "Срок действия запроса истёк",
    unavailableRequest: "Запрос уже обработан или недействителен",
    submitUnconfirmed: "Не удалось подтвердить решение. Проверьте состояние запроса перед повторной попыткой.",
    checkStatus: "Проверить состояние запроса",
    checkStatusFailed: "Не удалось проверить состояние запроса. Попробуйте ещё раз.",
    submitRejected: "Сервер отклонил это решение"
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
    disabledMsg: "Uso do computador desativado; automação em andamento interrompida",
    application: "Aplicativo",
    applicationId: "ID do aplicativo",
    revoke: "Revogar acesso",
    revokeConfirm: "Revogar o acesso a este aplicativo?",
    revokeHint: "Isso remove apenas a permissão salva do aplicativo nesta instalação do QwenPaw. As decisões de sessões existentes e as operações em andamento não são afetadas.",
    cancel: "Cancelar",
    empty: "Nenhum aplicativo tem permissão permanente.",
    approvalTitle: "Acesso ao aplicativo",
    unknownApplication: "Aplicativo desconhecido",
    risk: "Risco",
    allowAlways: "Sempre permitir este aplicativo",
    approvalHint: "Permita ou bloqueie o acesso a este aplicativo na sessão atual. Ao permitir, a operação pendente continuará.",
    persistentHint: "A permissão permanente salva o acesso ao aplicativo para todos os agentes desta instalação do QwenPaw até sua revogação em Uso do computador → Gerenciamento de acesso. A revogação não apaga decisões existentes das sessões nem interrompe operações em andamento.",
    failed: "Falha na ação.",
    accessManagement: "Gerenciamento de acesso",
    version: "Versão",
    decision: {
      deny: "Acesso ao aplicativo bloqueado nesta sessão.",
      session: "Acesso permitido nesta sessão.",
      always: "Aplicativo permitido permanentemente."
    },
    deny: "Bloquear aplicativo nesta sessão",
    allowSession: "Permitir aplicativo nesta sessão",
    submitting: "Enviando decisão…",
    waiting: "Aguardando confirmação",
    expired: "Solicitação expirada",
    unavailableRequest: "Solicitação já processada ou inválida",
    submitUnconfirmed: "Não foi possível confirmar a decisão. Verifique o status da solicitação antes de tentar novamente.",
    checkStatus: "Verificar status da solicitação",
    checkStatusFailed: "Não foi possível verificar o status da solicitação. Tente novamente.",
    submitRejected: "O servidor rejeitou esta decisão"
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
    disabledMsg: "Penggunaan Komputer dinonaktifkan; otomatisasi yang berjalan dihentikan",
    application: "Aplikasi",
    applicationId: "ID aplikasi",
    revoke: "Cabut akses",
    revokeConfirm: "Cabut akses aplikasi ini?",
    revokeHint: "Hanya izin aplikasi yang tersimpan pada instalasi QwenPaw ini yang dihapus. Keputusan sesi yang sudah ada dan operasi yang berjalan tidak terpengaruh.",
    cancel: "Batal",
    empty: "Belum ada aplikasi yang selalu diizinkan.",
    approvalTitle: "Akses aplikasi",
    unknownApplication: "Aplikasi tidak dikenal",
    risk: "Risiko",
    allowAlways: "Selalu izinkan aplikasi ini",
    approvalHint: "Izinkan atau blokir akses ke aplikasi ini selama sesi saat ini. Mengizinkan akses akan melanjutkan operasi yang tertunda.",
    persistentHint: "Izin permanen menyimpan akses aplikasi untuk semua agen dalam instalasi QwenPaw ini hingga dicabut melalui Penggunaan Komputer → Pengelolaan akses. Pencabutan tidak menghapus keputusan sesi yang ada atau menghentikan operasi yang sedang berjalan.",
    failed: "Tindakan gagal.",
    accessManagement: "Pengelolaan akses",
    version: "Versi",
    decision: {
      deny: "Akses aplikasi diblokir selama sesi ini.",
      session: "Akses diizinkan selama sesi ini.",
      always: "Aplikasi selalu diizinkan."
    },
    deny: "Blokir aplikasi selama sesi ini",
    allowSession: "Izinkan aplikasi selama sesi ini",
    submitting: "Mengirim keputusan…",
    waiting: "Menunggu konfirmasi",
    expired: "Permintaan kedaluwarsa",
    unavailableRequest: "Permintaan sudah ditangani atau tidak berlaku",
    submitUnconfirmed: "Keputusan belum dapat dikonfirmasi. Periksa status permintaan sebelum mencoba lagi.",
    checkStatus: "Periksa status permintaan",
    checkStatusFailed: "Status permintaan tidak dapat diperiksa. Coba lagi.",
    submitRejected: "Server menolak keputusan ini"
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
    revokeHint: "Thao tác này chỉ xóa quyền ứng dụng đã lưu trong bản cài đặt QwenPaw này. Các quyết định hiện có của phiên và thao tác đang chạy không bị ảnh hưởng.",
    cancel: "Hủy",
    empty: "Chưa có ứng dụng nào được cho phép vĩnh viễn.",
    approvalTitle: "Quyền truy cập ứng dụng",
    unknownApplication: "Ứng dụng không xác định",
    risk: "Rủi ro",
    allowAlways: "Luôn cho phép ứng dụng này",
    approvalHint: "Cho phép hoặc chặn quyền truy cập ứng dụng này trong phiên hiện tại. Khi được cho phép, thao tác đang chờ sẽ tiếp tục.",
    persistentHint: "Quyền truy cập vĩnh viễn được lưu cho tất cả Agent trong bản cài đặt QwenPaw này cho đến khi bị thu hồi tại Sử dụng máy tính → Quản lý quyền truy cập. Thu hồi không xóa các quyết định hiện có của phiên hoặc dừng thao tác đang chạy.",
    failed: "Thao tác thất bại.",
    accessManagement: "Quản lý quyền truy cập",
    version: "Phiên bản",
    decision: {
      deny: "Đã chặn quyền truy cập ứng dụng trong phiên này.",
      session: "Đã cho phép truy cập trong phiên này.",
      always: "Đã cho phép ứng dụng vĩnh viễn."
    },
    deny: "Chặn ứng dụng trong phiên này",
    allowSession: "Cho phép ứng dụng trong phiên này",
    submitting: "Đang gửi quyết định…",
    waiting: "Đang chờ xác nhận",
    expired: "Yêu cầu đã hết hạn",
    unavailableRequest: "Yêu cầu đã được xử lý hoặc không còn hiệu lực",
    submitUnconfirmed: "Không thể xác nhận quyết định. Hãy kiểm tra trạng thái yêu cầu trước khi thử lại.",
    checkStatus: "Kiểm tra trạng thái yêu cầu",
    checkStatusFailed: "Không thể kiểm tra trạng thái yêu cầu. Hãy thử lại.",
    submitRejected: "Máy chủ đã từ chối quyết định này"
  }
};
function _(e) {
  const i = e == null ? void 0 : e.toLowerCase().split("-")[0];
  return i === "pt" ? "pt-BR" : i === "zh" || i === "ja" || i === "ru" || i === "id" || i === "vi" ? i : "en";
}
function n(e, i) {
  if (i.startsWith("decision.")) {
    const t = i.slice(
      9
    );
    return L[e].decision[t];
  }
  return L[e][i];
}
const B = "1.0.1", N = {
  version: B
}, r = window.QwenPaw.host, a = r.React, {
  Badge: O,
  Button: j,
  Empty: z,
  Popconfirm: W,
  Space: M,
  Switch: J,
  Table: V,
  Tabs: G,
  Tooltip: Q,
  Typography: Y,
  message: b
} = r.antd, { DeleteOutlined: X, ReloadOutlined: Z } = r.antdIcons, { Text: m, Title: ee } = Y;
function ae() {
  try {
    return _(localStorage.getItem("language"));
  } catch {
    return _(void 0);
  }
}
async function v(e, i) {
  const t = r.fetch ? await r.fetch(e, i) : await fetch(r.getApiUrl(e), {
    ...i,
    headers: {
      ...(i == null ? void 0 : i.headers) || {},
      ...r.getApiToken() ? { Authorization: `Bearer ${r.getApiToken()}` } : {}
    }
  }), l = await t.text();
  let d = null;
  try {
    d = l ? JSON.parse(l) : null;
  } catch {
    d = null;
  }
  if (!t.ok) {
    const p = d && typeof d == "object" && "detail" in d ? d.detail : void 0;
    throw Object.assign(
      new Error(
        typeof p == "string" ? p : `HTTP ${t.status}`
      ),
      { status: t.status }
    );
  }
  return d;
}
function ne(e, i) {
  const t = e.toolParams.display_name;
  if (typeof t == "string" && t.trim())
    return t;
  const l = e.toolParams.canonical_app_id;
  return typeof l == "string" && l.trim() ? l : n(i, "unknownApplication");
}
function te(e) {
  const i = e.toolParams.canonical_app_id;
  if (typeof i != "string" || !i.trim())
    return "";
  const t = i.indexOf(":");
  return t !== -1 && i.slice(0, t) === "process" ? i.slice(t + 1) : i;
}
function ie({
  approval: e,
  onResolved: i
}) {
  var o;
  const t = _((o = r.useLocale) == null ? void 0 : o.call(r)), [l, d] = a.useState(null), p = a.useRef(!1), [u, y] = a.useState(null), [S, H] = a.useState(""), [A, E] = a.useState(!1), [P, w] = a.useState(Date.now), f = typeof e.createdAt == "number" && typeof e.timeoutSeconds == "number" ? (e.createdAt + e.timeoutSeconds) * 1e3 : 1 / 0, g = P >= f;
  a.useEffect(() => {
    const s = setInterval(() => w(Date.now()), 1e3);
    return () => clearInterval(s);
  }, [e.requestId]);
  const x = typeof e.toolParams.risk == "string" ? e.toolParams.risk : "", C = typeof e.toolParams.warning == "string" ? e.toolParams.warning : "", R = ne(e, t), h = te(e), T = async (s) => {
    if (!(p.current || u)) {
      if (Date.now() >= f) {
        w(Date.now());
        return;
      }
      p.current = !0, d(s);
      try {
        const c = await v(
          "/computer-use/session/pending/decision",
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              session_id: e.sessionId,
              request_id: e.requestId,
              decision: s
            })
          }
        );
        if (!c || typeof c != "object" || !("resolved" in c) || c.resolved !== !0) {
          y("unavailable");
          return;
        }
        y(s), b.success(n(t, `decision.${s}`)), i();
      } catch (c) {
        const k = c && typeof c == "object" && "status" in c ? c.status : void 0;
        k === 404 || k === 409 ? y("unavailable") : typeof k == "number" && k < 500 ? (H(
          c instanceof Error ? c.message : `HTTP ${k}`
        ), y("rejected")) : y("failed");
      } finally {
        p.current = !1, d(null);
      }
    }
  }, I = async () => {
    if (!(p.current || g)) {
      p.current = !0, d("check"), E(!1);
      try {
        const s = e.rootSessionId ? `?${new URLSearchParams({ session_id: e.rootSessionId })}` : "", c = await v(`/approval/list${s}`, {
          cache: "no-store"
        });
        if (!c || typeof c != "object" || !("pending_approvals" in c) || !Array.isArray(c.pending_approvals))
          throw new Error("Invalid approval list");
        const k = Date.now(), K = c.pending_approvals.some(
          (U) => (U == null ? void 0 : U.request_id) === e.requestId
        );
        w(k), y(K && k < f ? null : "unavailable");
      } catch {
        E(!0);
      } finally {
        p.current = !1, d(null);
      }
    }
  }, q = !g && (u === "failed" || u === "rejected");
  return a.createElement(
    r.antd.Card,
    { size: "small", bordered: !0, style: { borderRadius: 8 } },
    a.createElement(
      "div",
      { style: { display: "grid", gap: 14 } },
      a.createElement(
        "div",
        { style: { display: "grid", gap: 4 } },
        a.createElement(
          M,
          { size: 8 },
          a.createElement(
            m,
            { strong: !0 },
            n(t, "approvalTitle")
          )
        ),
        a.createElement(
          m,
          { strong: !0, style: { overflowWrap: "anywhere" } },
          R
        ),
        a.createElement(
          m,
          { type: "secondary" },
          n(t, "approvalHint")
        ),
        a.createElement(
          m,
          { type: "secondary" },
          n(t, "persistentHint")
        ),
        h && h !== R ? a.createElement(
          "div",
          {
            style: {
              display: "flex",
              alignItems: "center",
              gap: 6,
              minWidth: 0,
              maxWidth: "100%",
              padding: "2px 8px",
              borderRadius: 6,
              background: "rgba(140, 140, 140, 0.1)"
            }
          },
          a.createElement(
            m,
            {
              type: "secondary",
              copyable: { text: h },
              style: {
                fontSize: 12,
                minWidth: 0,
                overflowWrap: "anywhere",
                fontFamily: "'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace"
              }
            },
            h
          )
        ) : null,
        x ? a.createElement(
          m,
          { type: "secondary" },
          `${n(t, "risk")}: ${x}`
        ) : null,
        C ? a.createElement(m, { type: "warning" }, C) : null
      ),
      a.createElement(
        "p",
        { role: "status", "aria-live": "polite", style: { margin: 0 } },
        l === "check" ? n(t, "checkStatus") : l ? n(t, "submitting") : u === "unavailable" ? n(t, "unavailableRequest") : g && (u === "failed" || u === "rejected" || !u) ? n(t, "expired") : A ? n(t, "checkStatusFailed") : u === "failed" ? n(t, "submitUnconfirmed") : u === "rejected" ? `${n(t, "submitRejected")}: ${S}` : u ? n(t, `decision.${u}`) : n(t, "waiting")
      ),
      q ? a.createElement(
        j,
        {
          loading: l === "check",
          "aria-label": n(t, "checkStatus"),
          onClick: () => void I()
        },
        n(t, "checkStatus")
      ) : !u && !g ? a.createElement(
        "div",
        {
          "aria-busy": l !== null,
          style: {
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 160px), 1fr))",
            gap: 8
          }
        },
        ...["deny", "always", "session"].map(
          (s) => a.createElement(
            j,
            {
              key: s,
              type: s === "session" ? "primary" : "default",
              loading: l === s,
              disabled: l !== null,
              style: {
                whiteSpace: "normal",
                height: "auto",
                minHeight: 44,
                padding: "8px 12px"
              },
              onClick: () => void T(s)
            },
            n(
              t,
              s === "deny" ? "deny" : s === "always" ? "allowAlways" : "allowSession"
            )
          )
        )
      ) : null
    )
  );
}
function se() {
  var T, I, q;
  const e = _((T = r.useLocale) == null ? void 0 : T.call(r)), i = (I = r.useCurrentSession) == null ? void 0 : I.call(r), t = (i == null ? void 0 : i.id) ?? ((q = r.getCurrentSessionId) == null ? void 0 : q.call(r)) ?? null, [l, d] = a.useState(null), [p, u] = a.useState([]), [y, S] = a.useState(!0), [H, A] = a.useState(!1), [E, P] = a.useState(!0), [w, f] = a.useState(null), g = a.useCallback(async () => {
    P(!0);
    try {
      const [o, s] = await Promise.all([
        v("/computer-use/status"),
        v("/computer-use/access")
      ]);
      d(o), u(s.access || []), S(o.enabled !== !1);
    } catch (o) {
      b.error(
        o instanceof Error ? o.message : n(e, "failed")
      );
    } finally {
      P(!1);
    }
  }, [e]);
  a.useEffect(() => {
    g();
  }, [g]);
  const x = async (o) => {
    f(`revoke:${o.canonical_app_id}`);
    try {
      await v("/computer-use/access", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ canonical_app_id: o.canonical_app_id })
      }), await g();
    } catch (s) {
      b.error(
        s instanceof Error ? s.message : n(e, "failed")
      );
    } finally {
      f(null);
    }
  }, C = async (o) => {
    A(!0);
    try {
      await v("/computer-use/feature", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: o, session_id: t })
      }), S(o), b.success(n(e, o ? "enabledMsg" : "disabledMsg")), await g();
    } catch (s) {
      b.error(
        s instanceof Error ? s.message : n(e, "failed")
      );
    } finally {
      A(!1);
    }
  }, R = [
    {
      title: n(e, "application"),
      dataIndex: "display_name",
      key: "display_name",
      render: (o) => a.createElement(m, { strong: !0 }, o)
    },
    {
      title: n(e, "applicationId"),
      dataIndex: "canonical_app_id",
      key: "canonical_app_id",
      render: (o) => a.createElement(m, { code: !0 }, o)
    },
    {
      key: "actions",
      width: 56,
      render: (o, s) => a.createElement(
        W,
        {
          title: n(e, "revokeConfirm"),
          description: n(e, "revokeHint"),
          okText: n(e, "revoke"),
          cancelText: n(e, "cancel"),
          okButtonProps: { danger: !0 },
          styles: {
            root: { maxWidth: "min(360px, calc(100vw - 32px))" }
          },
          onConfirm: () => void x(s)
        },
        a.createElement(
          Q,
          { title: n(e, "revoke") },
          a.createElement(j, {
            type: "text",
            danger: !0,
            shape: "circle",
            icon: a.createElement(X),
            loading: w === `revoke:${s.canonical_app_id}`,
            "aria-label": n(e, "revoke")
          })
        )
      )
    }
  ], h = (l == null ? void 0 : l.runtime_available) === !0;
  return a.createElement(
    "main",
    {
      style: {
        maxWidth: 1080,
        margin: "24px auto",
        padding: "0 24px 40px",
        display: "grid",
        gap: 28
      }
    },
    a.createElement(
      "header",
      {
        style: {
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 16,
          paddingBottom: 16,
          borderBottom: "1px solid rgba(0, 0, 0, 0.08)"
        }
      },
      a.createElement(
        "div",
        { style: { display: "grid", gap: 6 } },
        a.createElement(
          M,
          { align: "baseline", size: 8 },
          a.createElement(
            ee,
            { level: 3, style: { margin: 0 } },
            n(e, "title")
          ),
          a.createElement(
            m,
            { type: "secondary", style: { fontSize: 12 } },
            `${n(e, "version")} ${N.version}`
          )
        ),
        a.createElement(O, {
          status: h ? "success" : "error",
          text: n(e, h ? "ready" : "unavailable")
        })
      ),
      a.createElement(
        M,
        { size: 8 },
        a.createElement(
          Q,
          { title: n(e, "refresh") },
          a.createElement(j, {
            type: "text",
            shape: "circle",
            icon: a.createElement(Z),
            loading: E,
            onClick: () => void g(),
            "aria-label": n(e, "refresh")
          })
        ),
        a.createElement(
          M,
          { size: 8, align: "center" },
          a.createElement(
            m,
            { type: "secondary", style: { fontSize: 13 } },
            n(e, "feature")
          ),
          a.createElement(J, {
            checked: y,
            loading: H,
            disabled: !h,
            onChange: (o) => void C(o),
            "aria-label": n(e, "feature")
          })
        )
      )
    ),
    a.createElement(G, {
      defaultActiveKey: "access",
      items: [
        {
          key: "access",
          label: n(e, "accessManagement"),
          children: a.createElement(V, {
            rowKey: "canonical_app_id",
            columns: R,
            dataSource: p,
            pagination: !1,
            size: "middle",
            locale: {
              emptyText: a.createElement(z, {
                image: z.PRESENTED_IMAGE_SIMPLE,
                description: n(e, "empty")
              })
            }
          })
        }
      ]
    })
  );
}
var D;
(D = window.QwenPaw.chat) == null || D.approval.render(
  "computer-use",
  "computer_use_app_access",
  ie
);
var $, F;
(F = ($ = window.QwenPaw).registerRoutes) == null || F.call($, "computer-use", [
  {
    path: "/plugin/computer-use",
    component: se,
    label: n(ae(), "routeLabel"),
    icon: "🖥️",
    priority: 43
  }
]);
export {
  ie as ComputerUseApprovalCard
};
