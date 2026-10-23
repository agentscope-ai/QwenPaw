"""Frozen real VoiceChannelConfig defaults; missing-artifact RED first."""
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
 'twilio_account_sid': '',
 'twilio_auth_token': '',
 'phone_number': '',
 'phone_number_sid': '',
 'tts_provider': 'google',
 'tts_voice': 'en-US-Journey-D',
 'stt_provider': 'deepgram',
 'language': 'en-US',
 'welcome_greeting': 'Hi! This is QwenPaw. How can I help you?'}


def test_voice_installable_payload_and_real_shared_driver(monkeypatch):
    check_payload('voice', 'VoiceDriver', monkeypatch)


def test_voice_descriptor_retains_complete_config_schema():
    check_descriptor('voice', 'VoiceDriver', 'VoiceChannelConfig', CONFIG_DEFAULTS)
