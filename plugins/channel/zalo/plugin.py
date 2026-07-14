# -*- coding: utf-8 -*-
# pylint: disable=too-many-locals
"""Zalo Bot channel plugin entry point for QwenPaw 2.0.

Exports the module-level ``plugin`` singleton. QwenPaw's plugin loader
calls ``plugin.register(api)`` once after import, passing a
``PluginApi`` instance, which we use to register the Zalo channel.
"""

from __future__ import annotations

import logging

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)


class ZaloChannelPlugin:
    """Zalo Bot channel plugin (polling-only, no webhook required)."""

    def register(self, api: PluginApi) -> None:
        """Register the Zalo Bot channel with QwenPaw.

        Field order mirrors the channel's ``__init__`` signature: bot
        token first (required), then API base, secret, typing, poll
        interval, retries, message length, plus the shared access-control
        fields that the framework renders for every channel.
        """
        from .channel import ZaloChannel

        api.register_channel(
            channel_class=ZaloChannel,
            label="Zalo Bot",
            description="Zalo Bot channel via long-polling (no public URL/webhook required)",
            icon="https://page.zalo.me/favicon.ico",
            doc_url={
                "en": (
                    "https://qwenpaw.agentscope.io/docs/channels/"
                    "?lang=en#Zalo-Bot"
                ),
                "zh": (
                    "https://qwenpaw.agentscope.io/docs/channels/"
                    "?lang=zh#Zalo-Bot"
                ),
            },
            config_fields=[
                {
                    "name": "bot_token",
                    "label": {
                        "zh-CN": "Bot Token",
                        "en-US": "Bot Token",
                        "ja-JP": "Bot Token",
                        "ru-RU": "Bot Token",
                        "pt-BR": "Bot Token",
                        "vi-VN": "Bot Token",
                        "id-ID": "Bot Token",
                    },
                    "type": "password",
                    "required": True,
                    "placeholder": "OA_ID:SECRET",
                    "help": {
                        "zh-CN": "在 Zalo Bot Platform > Settings > Bot Token 中获取。",
                        "en-US": "Get it from Zalo Bot Platform > Settings > Bot Token.",
                        "ja-JP": "Zalo Bot Platform の Settings > Bot Token で取得します。",
                        "ru-RU": "Получите в Zalo Bot Platform → Settings → Bot Token.",
                        "pt-BR": "Obtenha em Zalo Bot Platform > Settings > Bot Token.",
                        "vi-VN": "Lấy từ Zalo Bot Platform > Settings > Bot Token.",
                        "id-ID": "Dapatkan di Zalo Bot Platform > Settings > Bot Token.",
                    },
                },
                {
                    "name": "api_base_url",
                    "label": {
                        "zh-CN": "API 地址",
                        "en-US": "API Base URL",
                        "ja-JP": "API ベース URL",
                        "ru-RU": "Базовый URL API",
                        "pt-BR": "URL Base da API",
                        "vi-VN": "URL API",
                        "id-ID": "URL Dasar API",
                    },
                    "type": "text",
                    "required": False,
                    "default": "https://bot-api.zaloplatforms.com",
                    "placeholder": "https://bot-api.zaloplatforms.com",
                    "help": {
                        "zh-CN": "默认使用 Zalo Bot Platform 官方端点。仅在需要自定义端点时修改。",
                        "en-US": "Defaults to the official Zalo Bot Platform endpoint. Override only if using a different endpoint.",
                        "ja-JP": "デフォルトは Zalo Bot Platform の公式エンドポイントです。別のエンドポイントを使用する場合のみ変更してください。",
                        "ru-RU": "По умолчанию — официальный эндпоинт Zalo Bot Platform. Меняйте только при использовании другого эндпоинта.",
                        "pt-BR": "Padrão: endpoint oficial do Zalo Bot Platform. Altere apenas se usar um endpoint diferente.",
                        "vi-VN": "Mặc định dùng endpoint chính thức của Zalo Bot Platform. Chỉ đổi khi dùng endpoint khác.",
                        "id-ID": "Default: endpoint resmi Zalo Bot Platform. Ubah hanya jika menggunakan endpoint berbeda.",
                    },
                },
                {
                    "name": "secret_token",
                    "label": {
                        "zh-CN": "Secret Token",
                        "en-US": "Secret Token",
                        "ja-JP": "Secret Token",
                        "ru-RU": "Secret Token",
                        "pt-BR": "Secret Token",
                        "vi-VN": "Secret Token",
                        "id-ID": "Secret Token",
                    },
                    "type": "password",
                    "required": False,
                    "placeholder": "Auto-generated if empty",
                    "help": {
                        "zh-CN": "Webhook 校验密钥（轮询模式不用）。留空则自动生成。",
                        "en-US": "Webhook verification secret (unused in polling mode). Auto-generated if empty.",
                        "ja-JP": "Webhook 検証用シークレット（ポーリングモードでは未使用）。空なら自動生成されます。",
                        "ru-RU": "Секрет для проверки webhook (не используется в режиме опроса). Генерируется автоматически, если пусто.",
                        "pt-BR": "Segredo de verificação do webhook (não usado no modo polling). Gerado automaticamente se vazio.",
                        "vi-VN": "Secret xác thực webhook (không dùng ở chế độ polling). Tự sinh nếu để trống.",
                        "id-ID": "Rahasia verifikasi webhook (tidak dipakai di mode polling). Otomatis dibuat jika kosong.",
                    },
                },
                {
                    "name": "show_typing",
                    "label": {
                        "zh-CN": "显示输入中",
                        "en-US": "Show Typing",
                        "ja-JP": "入力中表示",
                        "ru-RU": "Показ «печатает»",
                        "pt-BR": "Mostrar Digitando",
                        "vi-VN": "Hiện đang gõ",
                        "id-ID": "Tampilkan Mengetik",
                    },
                    "type": "switch",
                    "required": False,
                    "default": True,
                    "help": {
                        "zh-CN": "开启后，Agent 思考时向 Zalo 发送输入中提示。",
                        "en-US": "Send a typing indicator to Zalo while the agent is thinking.",
                        "ja-JP": "有効にすると、Agent の思考中に Zalo へ入力中表示を送信します。",
                        "ru-RU": "Отправлять индикатор «печатает» в Zalo, пока агент обрабатывает запрос.",
                        "pt-BR": "Envia um indicador de «digitando» ao Zalo enquanto o agente processa.",
                        "vi-VN": "Gửi trạng thái «đang gõ» lên Zalo khi agent đang xử lý.",
                        "id-ID": "Kirim indikator «mengetik» ke Zalo saat agent memproses.",
                    },
                },
                {
                    "name": "poll_interval",
                    "label": {
                        "zh-CN": "轮询间隔（秒）",
                        "en-US": "Poll Interval (s)",
                        "ja-JP": "ポーリング間隔（秒）",
                        "ru-RU": "Интервал опроса (с)",
                        "pt-BR": "Intervalo de Polling (s)",
                        "vi-VN": "Chu kỳ poll (giây)",
                        "id-ID": "Interval Polling (detik)",
                    },
                    "type": "number",
                    "required": False,
                    "default": 30,
                    "placeholder": "30",
                    "help": {
                        "zh-CN": "轮询 getUpdates 的频率，最小 1 秒。",
                        "en-US": "How often to poll getUpdates. Minimum 1 second.",
                        "ja-JP": "getUpdates をポーリングする間隔。最小 1 秒。",
                        "ru-RU": "Как часто опрашивать getUpdates. Минимум 1 секунда.",
                        "pt-BR": "Com que frequência consultar getUpdates. Mínimo 1 segundo.",
                        "vi-VN": "Tần suất poll getUpdates. Tối thiểu 1 giây.",
                        "id-ID": "Seberapa sering menanyakan getUpdates. Minimum 1 detik.",
                    },
                },
                {
                    "name": "max_retries",
                    "label": {
                        "zh-CN": "最大重试次数",
                        "en-US": "Max Retries",
                        "ja-JP": "最大リトライ回数",
                        "ru-RU": "Максимум попыток",
                        "pt-BR": "Máx. de Tentativas",
                        "vi-VN": "Số thử lại tối đa",
                        "id-ID": "Maks. Percobaan",
                    },
                    "type": "number",
                    "required": False,
                    "default": 3,
                    "placeholder": "3",
                    "help": {
                        "zh-CN": "遇到 5xx / 网络错误时的最大 API 重试次数。",
                        "en-US": "Max API call retries on 5xx / network error.",
                        "ja-JP": "5xx / ネットワークエラー時の最大 API リトライ回数。",
                        "ru-RU": "Максимум повторов API-вызовов при 5xx / сетевых ошибках.",
                        "pt-BR": "Máximo de retentativas de API em erros 5xx / rede.",
                        "vi-VN": "Số thử lại API tối đa khi gặp lỗi 5xx / mạng.",
                        "id-ID": "Maksimum percobaan ulang API saat error 5xx / jaringan.",
                    },
                },
                {
                    "name": "max_message_len",
                    "label": {
                        "zh-CN": "消息最大长度",
                        "en-US": "Max Message Length",
                        "ja-JP": "メッセージ最大長",
                        "ru-RU": "Макс. длина сообщения",
                        "pt-BR": "Tamanho Máx. de Mensagem",
                        "vi-VN": "Độ dài tin nhắn tối đa",
                        "id-ID": "Panjang Maks. Pesan",
                    },
                    "type": "number",
                    "required": False,
                    "default": 2000,
                    "placeholder": "2000",
                    "help": {
                        "zh-CN": "Zalo Bot Platform 单条消息上限为 2000 字符。",
                        "en-US": "Zalo Bot Platform limit is 2000 chars per message.",
                        "ja-JP": "Zalo Bot Platform の 1 メッセージ上限は 2000 文字です。",
                        "ru-RU": "Лимит Zalo Bot Platform — 2000 символов на сообщение.",
                        "pt-BR": "O limite do Zalo Bot Platform é 2000 caracteres por mensagem.",
                        "vi-VN": "Giới hạn Zalo Bot Platform là 2000 ký tự mỗi tin nhắn.",
                        "id-ID": "Batas Zalo Bot Platform adalah 2000 karakter per pesan.",
                    },
                },
                {
                    "name": "share_session_in_group",
                    "label": {
                        "zh-CN": "群聊共享上下文",
                        "en-US": "Share Context in Group",
                        "ja-JP": "グループでコンテキスト共有",
                        "ru-RU": "Общий контекст в группе",
                        "pt-BR": "Compartilhar Contexto em Grupo",
                        "vi-VN": "Chia sẻ ngữ cảnh trong nhóm",
                        "id-ID": "Bagikan Konteks dalam Grup",
                    },
                    "type": "switch",
                    "required": False,
                    "default": True,
                    "help": {
                        "zh-CN": "开启时，群内所有成员共享同一会话上下文；关闭时，每位成员各自独立。",
                        "en-US": "When enabled, all group members share the same conversation context. When disabled, each member has an independent context.",
                        "ja-JP": "有効にすると、グループの全メンバーが同じ会話コンテキストを共有します。無効にすると、各メンバーが独立します。",
                        "ru-RU": "Если включено, все участники группы используют общий контекст разговора. Если выключено — у каждого независимый контекст.",
                        "pt-BR": "Quando ativado, todos os membros do grupo compartilham o mesmo contexto. Quando desativado, cada um tem contexto independente.",
                        "vi-VN": "Khi bật, mọi thành viên nhóm dùng chung ngữ cảnh. Khi tắt, mỗi người có ngữ cảnh riêng.",
                        "id-ID": "Saat aktif, semua anggota grup berbagi konteks yang sama. Saat nonaktif, masing-masing punya konteks independen.",
                    },
                },
                {
                    "name": "access_control_dm",
                    "label": {
                        "zh-CN": "私聊访问控制",
                        "en-US": "DM Access Control",
                        "ja-JP": "DM アクセス制御",
                        "ru-RU": "Контроль доступа в ЛС",
                        "pt-BR": "Controle de Acesso DM",
                        "vi-VN": "Kiểm soát truy cập DM",
                        "id-ID": "Kontrol Akses DM",
                    },
                    "type": "switch",
                    "required": False,
                    "default": False,
                    "help": {
                        "zh-CN": "开启后，仅白名单用户可在私聊中与 Bot 互动。",
                        "en-US": "When enabled, only whitelisted users can interact with the bot in direct messages.",
                        "ja-JP": "有効にすると、ホワイトリストのユーザーのみが DM で Bot と対話できます。",
                        "ru-RU": "При включении только пользователи из белого списка могут общаться с ботом в личных сообщениях.",
                        "pt-BR": "Quando ativado, apenas usuários na lista branca podem interagir com o bot em mensagens diretas.",
                        "vi-VN": "Khi bật, chỉ người dùng trong danh sách trắng mới tương tác được với bot qua tin nhắn riêng.",
                        "id-ID": "Saat aktif, hanya pengguna di daftar putih yang dapat berinteraksi dengan bot di pesan langsung.",
                    },
                },
                {
                    "name": "access_control_group",
                    "label": {
                        "zh-CN": "群聊访问控制",
                        "en-US": "Group Access Control",
                        "ja-JP": "グループ アクセス制御",
                        "ru-RU": "Контроль доступа в группах",
                        "pt-BR": "Controle de Acesso em Grupo",
                        "vi-VN": "Kiểm soát truy cập nhóm",
                        "id-ID": "Kontrol Akses Grup",
                    },
                    "type": "switch",
                    "required": False,
                    "default": False,
                    "help": {
                        "zh-CN": "开启后，仅白名单用户可在群聊中与 Bot 互动。",
                        "en-US": "When enabled, only whitelisted users can interact with the bot in group chats.",
                        "ja-JP": "有効にすると、ホワイトリストのユーザーのみがグループチャットで Bot と対話できます。",
                        "ru-RU": "При включении только пользователи из белого списка могут общаться с ботом в группах.",
                        "pt-BR": "Quando ativado, apenas usuários na lista branca podem interagir com o bot em chats de grupo.",
                        "vi-VN": "Khi bật, chỉ người dùng trong danh sách trắng mới tương tác được với bot trong nhóm chat.",
                        "id-ID": "Saat aktif, hanya pengguna di daftar putih yang dapat berinteraksi dengan bot di chat grup.",
                    },
                },
                {
                    "name": "require_mention",
                    "label": {
                        "zh-CN": "需要 @提及",
                        "en-US": "Require @Mention",
                        "ja-JP": "@メンション必須",
                        "ru-RU": "Требовать @упоминание",
                        "pt-BR": "Exigir @Menção",
                        "vi-VN": "Yêu cầu @Đề cập",
                        "id-ID": "Wajib @Sebut",
                    },
                    "type": "switch",
                    "required": False,
                    "default": False,
                    "help": {
                        "zh-CN": "开启后，群聊中仅在被 @提及 时才会回复。",
                        "en-US": "When enabled, the bot only responds in group chats when explicitly @mentioned.",
                        "ja-JP": "有効にすると、グループチャットでは明示的に @メンションされた場合のみ応答します。",
                        "ru-RU": "При включении бот отвечает в групповых чатах только при явном @упоминании.",
                        "pt-BR": "Quando ativado, o bot só responde em chats de grupo quando explicitamente @mencionado.",
                        "vi-VN": "Khi bật, bot chỉ trả lời trong nhóm khi được @đề cập rõ ràng.",
                        "id-ID": "Saat aktif, bot hanya merespons di chat grup saat secara eksplisit di-@sebut.",
                    },
                },
            ],
        )
        logger.info("✓ Zalo Bot channel registered")


# Module-level singleton the plugin loader expects to find.
plugin = ZaloChannelPlugin()
