export interface BaseChannelConfig {
  enabled: boolean;
  bot_prefix: string;
  filter_tool_messages?: boolean;
  filter_thinking?: boolean;
  dm_policy?: "open" | "allowlist";
  group_policy?: "open" | "allowlist";
  allow_from?: string[];
  require_mention?: boolean;
}

export interface IMessageChannelConfig extends BaseChannelConfig {
  db_path: string;
  poll_sec: number;
}

export interface DiscordConfig extends BaseChannelConfig {
  bot_token: string;
  http_proxy: string;
  http_proxy_auth: string;
  accept_bot_messages?: boolean;
}

export interface DingTalkConfig extends BaseChannelConfig {
  client_id: string;
  client_secret: string;
  message_type: string;
  card_template_id: string;
  card_template_key: string;
  robot_code: string;
}

export interface FeishuConfig extends BaseChannelConfig {
  app_id: string;
  app_secret: string;
  encrypt_key: string;
  verification_token: string;
  media_dir: string;
  domain?: "feishu" | "lark";
}

export interface QQConfig extends BaseChannelConfig {
  app_id: string;
  client_secret: string;
}

export interface TelegramConfig extends BaseChannelConfig {
  bot_token: string;
  http_proxy: string;
  http_proxy_auth: string;
  show_typing?: boolean;
}

export interface MQTTConfig extends BaseChannelConfig {
  host: string;
  port: number;
  transport: string;
  clean_session: boolean;
  qos: number;
  username: string;
  password: string;
  subscribe_topic: string;
  publish_topic: string;
  tls_enabled?: boolean;
  tls_ca_certs?: string;
  tls_certfile?: string;
  tls_keyfile?: string;
}

export interface MatrixConfig extends BaseChannelConfig {
  homeserver: string;
  user_id: string;
  access_token: string;
}

export interface MattermostConfig extends BaseChannelConfig {
  url: string;
  bot_token: string;
  media_dir?: string;
  show_typing?: boolean;
  thread_follow_without_mention?: boolean;
}

export interface WecomConfig extends BaseChannelConfig {
  bot_id: string;
  secret: string;
  media_dir?: string;
  welcome_text?: string;
  max_reconnect_attempts?: number;
}

export type ConsoleConfig = BaseChannelConfig;

export interface VoiceChannelConfig extends BaseChannelConfig {
  twilio_account_sid: string;
  twilio_auth_token: string;
  phone_number: string;
  phone_number_sid: string;
  tts_provider: string;
  tts_voice: string;
  stt_provider: string;
  language: string;
  welcome_greeting: string;
}

export interface XiaoYiConfig extends BaseChannelConfig {
  ak: string;
  sk: string;
  agent_id: string;
  ws_url: string;
  task_timeout_ms?: number;
}

export interface OneBotConfig extends BaseChannelConfig {
  ws_host: string;
  ws_port: number;
  access_token: string;
  share_session_in_group: boolean;
}

export interface SACPChannelConfig
  extends Omit<BaseChannelConfig, "bot_prefix"> {
  bot_prefix?: string;
  sensitive_md?: string;
}

export interface ChannelConfig {
  imessage: IMessageChannelConfig;
  discord: DiscordConfig;
  dingtalk: DingTalkConfig;
  feishu: FeishuConfig;
  qq: QQConfig;
  telegram: TelegramConfig;
  mqtt: MQTTConfig;
  matrix: MatrixConfig;
  mattermost: MattermostConfig;
  wecom: WecomConfig;
  console: ConsoleConfig;
  voice: VoiceChannelConfig;
  xiaoyi: XiaoYiConfig;
  onebot: OneBotConfig;
  sacp: SACPChannelConfig;
}

export type SingleChannelConfig =
  | IMessageChannelConfig
  | DiscordConfig
  | DingTalkConfig
  | FeishuConfig
  | QQConfig
  | ConsoleConfig
  | TelegramConfig
  | MQTTConfig
  | MatrixConfig
  | MattermostConfig
  | WecomConfig
  | VoiceChannelConfig
  | XiaoYiConfig
  | OneBotConfig
  | SACPChannelConfig;
