"""Frozen real SIPChannelConfig defaults; missing-artifact RED first."""
from voice_sip_artifact_support import check_payload, check_descriptor

CONFIG_DEFAULTS = {'enabled': False,
 'bot_prefix': '',
 'show_tool_calls': True,
 'show_tool_results': True,
 'tool_call_max_length': 200,
 'tool_result_max_length': 500,
 'show_thinking': True,
 'dm_policy': 'open',
 'group_policy': 'open',
 'allow_from': [],
 'deny_message': '',
 'require_mention': False,
 'no_text_debounce': True,
 'access_control_dm': False,
 'access_control_group': False,
 'dm_disabled': False,
 'group_disabled': False,
 'sip_mode': 'dev',
 'sip_host': '0.0.0.0',
 'sip_port': 5061,
 'sip_username': '',
 'sip_password': '',
 'sip_server': '',
 'sip_transport': 'UDP',
 'rtp_port_low': 10000,
 'rtp_port_high': 20000,
 'dashscope_api_key': '',
 'tts_provider': 'aliyun',
 'tts_voice': '',
 'stt_provider': 'aliyun',
 'language': 'zh-CN',
 'welcome_greeting': '你好，我是QwenPaw',
 'call_timeout': 120.0,
 'livekit_url': '',
 'livekit_api_key': '',
 'livekit_api_secret': '',
 'livekit_sip_trunk_id': '',
 'livekit_room_name': 'sip-inbound',
 'livekit_output_sample_rate': 24000,
 'max_concurrent_calls': 5}


def test_sip_installable_payload_and_real_shared_driver(monkeypatch):
    check_payload('sip', 'SIPDriver', monkeypatch)


def test_sip_descriptor_retains_complete_config_schema():
    check_descriptor('sip', 'SIPDriver', 'SIPChannelConfig', CONFIG_DEFAULTS)
