# -*- coding: utf-8 -*-
"""Azure Bot Service channel plugin entry point."""

import logging

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)


class AzureBotChannelPlugin:
    """Azure Bot Service channel plugin."""

    def register(self, api: PluginApi):
        """Register the Azure Bot channel.

        Field order below intentionally mirrors the original built-in
        channel form (app_id, app_password, tenant_id, http_host,
        http_port, media_dir, share_session_in_group) so the UI keeps
        the same layout as before.
        """
        from .channel import AzureBotChannel

        api.register_channel(
            channel_class=AzureBotChannel,
            label="Azure Bot",
            description="Azure Bot Service (Bot Framework) integration",
            icon=(
                "https://img.alicdn.com/imgextra/i2/"
                "O1CN01eo8rBj1pCuCWPQRrz_!!6000000005325-2-tps-3000-3000.png"
            ),
            doc_url={
                "zh": (
                    "https://qwenpaw.agentscope.io/docs/channels/"
                    "?lang=zh#Azure-BotMicrosoft-机器人服务"
                ),
                "en": (
                    "https://qwenpaw.agentscope.io/docs/channels/"
                    "?lang=en#Azure-Bot-Microsoft-Bot-Service"
                ),
            },
            config_fields=[
                {
                    "name": "app_id",
                    "label": "App ID",
                    "type": "text",
                    "required": True,
                    "placeholder": ("xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"),
                },
                {
                    "name": "app_password",
                    "label": "App Password",
                    "type": "password",
                    "required": True,
                    "placeholder": "App Password (Client Secret)",
                },
                {
                    "name": "tenant_id",
                    "label": "Tenant ID",
                    "type": "text",
                    "required": True,
                    "placeholder": ("xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"),
                },
                {
                    "name": "http_host",
                    "label": "HTTP Host",
                    "type": "text",
                    "required": False,
                    "placeholder": "0.0.0.0",
                    "default": "0.0.0.0",
                },
                {
                    "name": "http_port",
                    "label": "HTTP Port",
                    "type": "number",
                    "required": False,
                    "placeholder": "3978",
                    "default": 3978,
                },
                {
                    "name": "media_dir",
                    "label": {
                        "zh-CN": "媒体文件目录",
                        "en-US": "Media Directory",
                        "ja-JP": "メディアディレクトリ",
                        "ru-RU": "Директория медиафайлов",
                        "pt-BR": "Diretório de Mídia",
                        "vi-VN": "Thư mục media",
                        "id-ID": "Direktori Media",
                    },
                    "type": "text",
                    "required": False,
                    "help": {
                        "zh-CN": (
                            "默认为当前 agent 工作区下的 media "
                            "目录（workspaces/<agent_id>/media）。"
                        ),
                        "en-US": (
                            "Defaults to the current agent's workspace "
                            "media directory (workspaces/<agent_id>/media)."
                        ),
                        "ja-JP": (
                            "デフォルトは現在のエージェントのワークスペース内の "
                            "media ディレクトリ（workspaces/<agent_id>/media）です。"
                        ),
                        "ru-RU": (
                            "По умолчанию — каталог media рабочей области "
                            "текущего агента (workspaces/<agent_id>/media)."
                        ),
                        "pt-BR": (
                            "Padrão: diretório media do espaço de trabalho "
                            "do agente atual (workspaces/<agent_id>/media)."
                        ),
                        "vi-VN": (
                            "Mặc định là thư mục media trong workspace "
                            "của agent hiện tại (workspaces/<agent_id>/media)."
                        ),
                        "id-ID": (
                            "Default-nya adalah direktori media pada "
                            "workspace agen saat ini "
                            "(workspaces/<agent_id>/media)."
                        ),
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
                    "default": False,
                    "help": {
                        "zh-CN": ("启用时，群内所有成员共享同一会话上下文；" "禁用时，每位成员维护各自独立的会话。"),
                        "en-US": (
                            "When enabled, all group members share the "
                            "same conversation context. When disabled, "
                            "each member has their own independent context."
                        ),
                        "ja-JP": (
                            "有効にすると、グループの全メンバーが"
                            "同じ会話コンテキストを共有します。"
                            "無効にすると、各メンバーが"
                            "独立したコンテキストを持ちます。"
                        ),
                        "ru-RU": (
                            "Если включено, все участники группы "
                            "используют общий контекст разговора. "
                            "Если выключено, у каждого участника "
                            "независимый контекст."
                        ),
                        "pt-BR": (
                            "Quando ativado, todos os membros do grupo "
                            "compartilham o mesmo contexto de conversa. "
                            "Quando desativado, cada membro tem seu "
                            "próprio contexto independente."
                        ),
                        "vi-VN": (
                            "Khi bật, tất cả thành viên nhóm chia sẻ "
                            "cùng một ngữ cảnh hội thoại. Khi tắt, mỗi "
                            "thành viên có ngữ cảnh độc lập riêng."
                        ),
                        "id-ID": (
                            "Saat diaktifkan, semua anggota grup berbagi "
                            "konteks percakapan yang sama. Saat "
                            "dinonaktifkan, setiap anggota memiliki "
                            "konteks independennya sendiri."
                        ),
                    },
                },
                {
                    "name": "access_control_dm",
                    "label": {
                        "zh-CN": "私聊访问控制",
                        "en-US": "DM Access Control",
                        "ja-JP": "DM アクセス制御",
                        "ru-RU": "Контроль доступа в ЛС",
                        "pt-BR": "Controle de Acesso em DM",
                        "vi-VN": "Kiểm soát truy cập DM",
                        "id-ID": "Kontrol Akses DM",
                    },
                    "type": "switch",
                    "required": False,
                    "default": False,
                    "help": {
                        "zh-CN": "开启后，只有白名单用户可以通过私聊与机器人互动",
                        "en-US": (
                            "When enabled, only whitelisted users can "
                            "interact with the bot in direct messages"
                        ),
                        "ja-JP": ("有効にすると、ホワイトリストのユーザーのみ" "DMでBotと対話できます"),
                        "ru-RU": (
                            "При включении только пользователи из "
                            "белого списка могут общаться с ботом "
                            "в личных сообщениях"
                        ),
                        "pt-BR": (
                            "Quando ativado, apenas usuários na lista "
                            "branca podem interagir com o bot em "
                            "mensagens diretas"
                        ),
                        "vi-VN": (
                            "Khi bật, chỉ người dùng trong danh sách "
                            "trắng mới có thể tương tác với bot trong "
                            "tin nhắn trực tiếp"
                        ),
                        "id-ID": (
                            "Saat diaktifkan, hanya pengguna dalam daftar "
                            "putih yang dapat berinteraksi dengan bot di "
                            "pesan langsung"
                        ),
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
                        "zh-CN": "开启后，只有白名单用户可以在群聊中与机器人互动",
                        "en-US": (
                            "When enabled, only whitelisted users can "
                            "interact with the bot in group chats"
                        ),
                        "ja-JP": (
                            "有効にすると、ホワイトリストのユーザーのみ" "グループチャットでBotと対話できます"
                        ),
                        "ru-RU": (
                            "При включении только пользователи из "
                            "белого списка могут общаться с ботом "
                            "в групповых чатах"
                        ),
                        "pt-BR": (
                            "Quando ativado, apenas usuários na lista "
                            "branca podem interagir com o bot em chats "
                            "de grupo"
                        ),
                        "vi-VN": (
                            "Khi bật, chỉ người dùng trong danh sách "
                            "trắng mới có thể tương tác với bot trong "
                            "nhóm chat"
                        ),
                        "id-ID": (
                            "Saat diaktifkan, hanya pengguna dalam daftar "
                            "putih yang dapat berinteraksi dengan bot di "
                            "chat grup"
                        ),
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
                        "zh-CN": "开启后，群聊中仅在被 @提及 时才会回复",
                        "en-US": (
                            "When enabled, bot only responds in group "
                            "chats when explicitly @mentioned"
                        ),
                        "ja-JP": (
                            "有効にすると、グループチャットでは" "明示的に@メンションされた場合のみ応答します"
                        ),
                        "ru-RU": (
                            "Бот отвечает в групповых чатах только "
                            "при явном @упоминании"
                        ),
                        "pt-BR": (
                            "Quando ativado, o bot só responde em "
                            "chats de grupo quando explicitamente "
                            "@mencionado"
                        ),
                        "vi-VN": (
                            "Khi bật, bot chỉ trả lời trong nhóm chat "
                            "khi được @đề cập rõ ràng"
                        ),
                        "id-ID": (
                            "Saat diaktifkan, bot hanya merespons di "
                            "chat grup saat secara eksplisit di-@sebut"
                        ),
                    },
                },
            ],
        )
        logger.info("✓ Azure Bot channel registered")


# Export plugin instance
plugin = AzureBotChannelPlugin()
