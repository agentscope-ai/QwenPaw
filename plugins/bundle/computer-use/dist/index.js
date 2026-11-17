const _ = {
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
    submitUnconfirmed: "Could not confirm the decision. Refresh the page to check the request before trying again.",
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
    submitUnconfirmed: "未能确认提交结果，请刷新页面核对请求状态后再操作。",
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
    submitUnconfirmed: "送信結果を確認できませんでした。ページを更新してリクエストの状態を確認してから再試行してください。",
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
    submitUnconfirmed: "Не удалось подтвердить результат отправки. Обновите страницу и проверьте состояние запроса перед повторной попыткой.",
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
    submitUnconfirmed: "Não foi possível confirmar o resultado do envio. Atualize a página e verifique o estado da solicitação antes de tentar novamente.",
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
    submitUnconfirmed: "Hasil pengiriman belum dapat dikonfirmasi. Muat ulang halaman dan periksa status permintaan sebelum mencoba lagi.",
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
    submitUnconfirmed: "Không thể xác nhận kết quả gửi. Hãy tải lại trang và kiểm tra trạng thái yêu cầu trước khi thử lại.",
    submitRejected: "Máy chủ đã từ chối quyết định này"
  }
};
function M(a) {
  const t = a == null ? void 0 : a.toLowerCase().split("-")[0];
  return t === "pt" ? "pt-BR" : t === "zh" || t === "ja" || t === "ru" || t === "id" || t === "vi" ? t : "en";
}
function n(a, t) {
  if (t.startsWith("decision.")) {
    const i = t.slice(
      9
    );
    return _[a].decision[i];
  }
  return _[a][t];
}
const D = "1.0.1", B = {
  version: D
}, s = window.QwenPaw.host, e = s.React, {
  Badge: $,
  Button: q,
  Empty: j,
  Popconfirm: N,
  Space: T,
  Switch: O,
  Table: K,
  Tabs: W,
  Tooltip: z,
  Typography: J,
  message: A
} = s.antd, { DeleteOutlined: F, ReloadOutlined: G } = s.antdIcons, { Text: p, Title: V } = J;
function Y() {
  try {
    return M(localStorage.getItem("language"));
  } catch {
    return M(void 0);
  }
}
async function E(a, t) {
  const i = s.fetch ? await s.fetch(a, t) : await fetch(s.getApiUrl(a), {
    ...t,
    headers: {
      ...(t == null ? void 0 : t.headers) || {},
      ...s.getApiToken() ? { Authorization: `Bearer ${s.getApiToken()}` } : {}
    }
  }), l = await i.text();
  let d = null;
  try {
    d = l ? JSON.parse(l) : null;
  } catch {
    d = null;
  }
  if (!i.ok) {
    const g = d && typeof d == "object" && "detail" in d ? d.detail : void 0;
    throw Object.assign(
      new Error(
        typeof g == "string" ? g : `HTTP ${i.status}`
      ),
      { status: i.status }
    );
  }
  return d;
}
function X(a, t) {
  const i = a.toolParams.display_name;
  if (typeof i == "string" && i.trim())
    return i;
  const l = a.toolParams.canonical_app_id;
  return typeof l == "string" && l.trim() ? l : n(t, "unknownApplication");
}
function Z(a) {
  const t = a.toolParams.canonical_app_id;
  if (typeof t != "string" || !t.trim())
    return "";
  const i = t.indexOf(":");
  return i !== -1 && t.slice(0, i) === "process" ? t.slice(i + 1) : t;
}
function ee({
  approval: a,
  onResolved: t
}) {
  var v;
  const i = M((v = s.useLocale) == null ? void 0 : v.call(s)), [l, d] = e.useState(null), g = e.useRef(!1), [m, f] = e.useState(null), [P, I] = e.useState(""), [x, S] = e.useState(Date.now), b = typeof a.createdAt == "number" && typeof a.timeoutSeconds == "number" ? (a.createdAt + a.timeoutSeconds) * 1e3 : 1 / 0, R = x >= b;
  e.useEffect(() => {
    const r = setInterval(() => S(Date.now()), 1e3);
    return () => clearInterval(r);
  }, [a.requestId]);
  const w = typeof a.toolParams.risk == "string" ? a.toolParams.risk : "", y = typeof a.toolParams.warning == "string" ? a.toolParams.warning : "", C = X(a, i), k = Z(a), H = async (r) => {
    if (!(g.current || m)) {
      if (Date.now() >= b) {
        S(Date.now());
        return;
      }
      g.current = !0, d(r);
      try {
        const c = await E(
          "/computer-use/session/pending/decision",
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              session_id: a.sessionId,
              request_id: a.requestId,
              decision: r
            })
          }
        );
        if (!c || typeof c != "object" || !("resolved" in c) || c.resolved !== !0) {
          f("unavailable");
          return;
        }
        f(r), A.success(n(i, `decision.${r}`)), t();
      } catch (c) {
        const h = c && typeof c == "object" && "status" in c ? c.status : void 0;
        h === 404 || h === 409 ? f("unavailable") : typeof h == "number" && h < 500 ? (I(
          c instanceof Error ? c.message : `HTTP ${h}`
        ), f("rejected")) : f("failed");
      } finally {
        g.current = !1, d(null);
      }
    }
  };
  return e.createElement(
    s.antd.Card,
    { size: "small", bordered: !0, style: { borderRadius: 8 } },
    e.createElement(
      "div",
      { style: { display: "grid", gap: 14 } },
      e.createElement(
        "div",
        { style: { display: "grid", gap: 4 } },
        e.createElement(
          T,
          { size: 8 },
          e.createElement(
            p,
            { strong: !0 },
            n(i, "approvalTitle")
          )
        ),
        e.createElement(
          p,
          { strong: !0, style: { overflowWrap: "anywhere" } },
          C
        ),
        e.createElement(
          p,
          { type: "secondary" },
          n(i, "approvalHint")
        ),
        e.createElement(
          p,
          { type: "secondary" },
          n(i, "persistentHint")
        ),
        k && k !== C ? e.createElement(
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
          e.createElement(
            p,
            {
              type: "secondary",
              copyable: { text: k },
              style: {
                fontSize: 12,
                minWidth: 0,
                overflowWrap: "anywhere",
                fontFamily: "'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace"
              }
            },
            k
          )
        ) : null,
        w ? e.createElement(
          p,
          { type: "secondary" },
          `${n(i, "risk")}: ${w}`
        ) : null,
        y ? e.createElement(p, { type: "warning" }, y) : null
      ),
      e.createElement(
        "p",
        { role: "status", "aria-live": "polite", style: { margin: 0 } },
        l ? n(i, "submitting") : m === "failed" ? n(i, "submitUnconfirmed") : m === "rejected" ? `${n(i, "submitRejected")}: ${P}` : m === "unavailable" ? n(i, "unavailableRequest") : m ? n(i, `decision.${m}`) : R ? n(i, "expired") : n(i, "waiting")
      ),
      !m && !R ? e.createElement(
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
          (r) => e.createElement(
            q,
            {
              key: r,
              type: r === "session" ? "primary" : "default",
              loading: l === r,
              disabled: l !== null,
              style: {
                whiteSpace: "normal",
                height: "auto",
                minHeight: 44,
                padding: "8px 12px"
              },
              onClick: () => void H(r)
            },
            n(
              i,
              r === "deny" ? "deny" : r === "always" ? "allowAlways" : "allowSession"
            )
          )
        )
      ) : null
    )
  );
}
function ae() {
  var r, c, h;
  const a = M((r = s.useLocale) == null ? void 0 : r.call(s)), t = (c = s.useCurrentSession) == null ? void 0 : c.call(s), i = (t == null ? void 0 : t.id) ?? ((h = s.getCurrentSessionId) == null ? void 0 : h.call(s)) ?? null, [l, d] = e.useState(null), [g, m] = e.useState([]), [f, P] = e.useState(!0), [I, x] = e.useState(!1), [S, b] = e.useState(!0), [R, w] = e.useState(null), y = e.useCallback(async () => {
    b(!0);
    try {
      const [o, u] = await Promise.all([
        E("/computer-use/status"),
        E("/computer-use/access")
      ]);
      d(o), m(u.access || []), P(o.enabled !== !1);
    } catch (o) {
      A.error(
        o instanceof Error ? o.message : n(a, "failed")
      );
    } finally {
      b(!1);
    }
  }, [a]);
  e.useEffect(() => {
    y();
  }, [y]);
  const C = async (o) => {
    w(`revoke:${o.canonical_app_id}`);
    try {
      await E("/computer-use/access", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ canonical_app_id: o.canonical_app_id })
      }), await y();
    } catch (u) {
      A.error(
        u instanceof Error ? u.message : n(a, "failed")
      );
    } finally {
      w(null);
    }
  }, k = async (o) => {
    x(!0);
    try {
      await E("/computer-use/feature", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: o, session_id: i })
      }), P(o), A.success(n(a, o ? "enabledMsg" : "disabledMsg")), await y();
    } catch (u) {
      A.error(
        u instanceof Error ? u.message : n(a, "failed")
      );
    } finally {
      x(!1);
    }
  }, H = [
    {
      title: n(a, "application"),
      dataIndex: "display_name",
      key: "display_name",
      render: (o) => e.createElement(p, { strong: !0 }, o)
    },
    {
      title: n(a, "applicationId"),
      dataIndex: "canonical_app_id",
      key: "canonical_app_id",
      render: (o) => e.createElement(p, { code: !0 }, o)
    },
    {
      key: "actions",
      width: 56,
      render: (o, u) => e.createElement(
        N,
        {
          title: n(a, "revokeConfirm"),
          description: n(a, "revokeHint"),
          okText: n(a, "revoke"),
          cancelText: n(a, "cancel"),
          okButtonProps: { danger: !0 },
          styles: {
            root: { maxWidth: "min(360px, calc(100vw - 32px))" }
          },
          onConfirm: () => void C(u)
        },
        e.createElement(
          z,
          { title: n(a, "revoke") },
          e.createElement(q, {
            type: "text",
            danger: !0,
            shape: "circle",
            icon: e.createElement(F),
            loading: R === `revoke:${u.canonical_app_id}`,
            "aria-label": n(a, "revoke")
          })
        )
      )
    }
  ], v = (l == null ? void 0 : l.runtime_available) === !0;
  return e.createElement(
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
    e.createElement(
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
      e.createElement(
        "div",
        { style: { display: "grid", gap: 6 } },
        e.createElement(
          T,
          { align: "baseline", size: 8 },
          e.createElement(
            V,
            { level: 3, style: { margin: 0 } },
            n(a, "title")
          ),
          e.createElement(
            p,
            { type: "secondary", style: { fontSize: 12 } },
            `${n(a, "version")} ${B.version}`
          )
        ),
        e.createElement($, {
          status: v ? "success" : "error",
          text: n(a, v ? "ready" : "unavailable")
        })
      ),
      e.createElement(
        T,
        { size: 8 },
        e.createElement(
          z,
          { title: n(a, "refresh") },
          e.createElement(q, {
            type: "text",
            shape: "circle",
            icon: e.createElement(G),
            loading: S,
            onClick: () => void y(),
            "aria-label": n(a, "refresh")
          })
        ),
        e.createElement(
          T,
          { size: 8, align: "center" },
          e.createElement(
            p,
            { type: "secondary", style: { fontSize: 13 } },
            n(a, "feature")
          ),
          e.createElement(O, {
            checked: f,
            loading: I,
            disabled: !v,
            onChange: (o) => void k(o),
            "aria-label": n(a, "feature")
          })
        )
      )
    ),
    e.createElement(W, {
      defaultActiveKey: "access",
      items: [
        {
          key: "access",
          label: n(a, "accessManagement"),
          children: e.createElement(K, {
            rowKey: "canonical_app_id",
            columns: H,
            dataSource: g,
            pagination: !1,
            size: "middle",
            locale: {
              emptyText: e.createElement(j, {
                image: j.PRESENTED_IMAGE_SIMPLE,
                description: n(a, "empty")
              })
            }
          })
        }
      ]
    })
  );
}
var U;
(U = window.QwenPaw.chat) == null || U.approval.render(
  "computer-use",
  "computer_use_app_access",
  ee
);
var L, Q;
(Q = (L = window.QwenPaw).registerRoutes) == null || Q.call(L, "computer-use", [
  {
    path: "/plugin/computer-use",
    component: ae,
    label: n(Y(), "routeLabel"),
    icon: "🖥️",
    priority: 43
  }
]);
export {
  ee as ComputerUseApprovalCard
};
