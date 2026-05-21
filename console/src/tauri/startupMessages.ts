interface StartupMessages {
  starting: string;
  checking: string;
  error: string;
  errorHint: string;
  errorDetails: string;
  timeout: (seconds: number) => string;
  timeoutHint: string;
  retry: string;
}

const MESSAGES: Record<string, StartupMessages> = {
  en: {
    starting: "Starting backend...",
    checking: "Connecting to backend...",
    error: "Backend failed to start.",
    errorHint:
      "The backend process could not be launched. Check application logs for details.",
    errorDetails: "Show error details",
    timeout: (seconds) => `Backend failed to start within ${seconds} seconds.`,
    timeoutHint:
      "Backend failed to start. Please retry, or check application logs for details.",
    retry: "Retry",
  },
  id: {
    starting: "Memulai backend...",
    checking: "Menghubungkan ke backend...",
    error: "Backend gagal dimulai.",
    errorHint:
      "Proses backend tidak dapat dijalankan. Periksa log aplikasi untuk detail.",
    errorDetails: "Tampilkan detail error",
    timeout: (seconds) => `Backend gagal dimulai dalam ${seconds} detik.`,
    timeoutHint:
      "Backend gagal dimulai. Coba lagi, atau periksa log aplikasi untuk detail.",
    retry: "Coba lagi",
  },
  ja: {
    starting: "バックエンドを起動中...",
    checking: "バックエンドに接続中...",
    error: "バックエンドの起動に失敗しました。",
    errorHint:
      "バックエンドプロセスを起動できませんでした。詳細はアプリケーションログを確認してください。",
    errorDetails: "エラーの詳細を表示",
    timeout: (seconds) =>
      `${seconds} 秒以内にバックエンドの起動に失敗しました。`,
    timeoutHint:
      "バックエンドの起動に失敗しました。再試行するか、アプリケーションのログを確認してください。",
    retry: "再試行",
  },
  "pt-BR": {
    starting: "Iniciando backend...",
    checking: "Conectando ao backend...",
    error: "Falha ao iniciar o backend.",
    errorHint:
      "Nao foi possivel iniciar o processo do backend. Verifique os logs do aplicativo para detalhes.",
    errorDetails: "Mostrar detalhes do erro",
    timeout: (seconds) => `O backend nao iniciou em ${seconds} segundos.`,
    timeoutHint:
      "Falha ao iniciar o backend. Tente novamente ou verifique os logs do aplicativo.",
    retry: "Tentar novamente",
  },
  ru: {
    starting: "Запуск сервера...",
    checking: "Подключение к серверу...",
    error: "Не удалось запустить сервер.",
    errorHint:
      "Не удалось запустить процесс сервера. Проверьте журналы приложения.",
    errorDetails: "Показать сведения об ошибке",
    timeout: (seconds) =>
      `Не удалось запустить сервер за ${seconds} секунд.`,
    timeoutHint:
      "Не удалось запустить бэкенд. Повторите попытку или проверьте журналы приложения.",
    retry: "Повторить",
  },
  zh: {
    starting: "正在启动后端服务...",
    checking: "正在连接后端...",
    error: "后端服务启动失败。",
    errorHint: "无法启动后端进程，请检查应用日志了解详情。",
    errorDetails: "显示错误详情",
    timeout: (seconds) => `后端服务在 ${seconds} 秒内未能启动。`,
    timeoutHint: "后端启动失败，请重试，或检查应用日志了解详情。",
    retry: "重试",
  },
};

export function getStartupMessages(language?: string): StartupMessages {
  const normalized = (language || "").toLowerCase();
  if (normalized.startsWith("zh")) return MESSAGES.zh;
  if (normalized.startsWith("ja")) return MESSAGES.ja;
  if (normalized.startsWith("id")) return MESSAGES.id;
  if (normalized.startsWith("pt-br") || normalized.startsWith("pt")) {
    return MESSAGES["pt-BR"];
  }
  if (normalized.startsWith("ru")) return MESSAGES.ru;
  return MESSAGES.en;
}
