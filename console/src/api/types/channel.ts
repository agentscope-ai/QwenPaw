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
}

export interface DingTalkConfig extends BaseChannelConfig {
  client_id: string;
  client_secret: string;
}

export interface FeishuConfig extends BaseChannelConfig {
  app_id: string;
  app_secret: string;
  encrypt_key: string;
  verification_token: string;
  media_dir: string;
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

export interface ChannelConfig {
  imessage: IMessageChannelConfig;
  discord: DiscordConfig;
  dingtalk: DingTalkConfig;
  feishu: FeishuConfig;
  qq: QQConfig;
  telegram: TelegramConfig;
  mqtt: MQTTConfig;
  console: ConsoleConfig;
  voice: VoiceChannelConfig;
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
  | ConsoleConfig
  | VoiceChannelConfig;
