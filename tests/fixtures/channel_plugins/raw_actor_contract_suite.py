"""Prepared against raw-actor-interface; execute only after complete source freeze."""
from types import SimpleNamespace as NS
import pytest


def sources(**changes):
    return {'getter_state':'absent','getter_texts':[],'top_texts':[],'nested_texts':[],**changes}


def inbound(**changes):
    return {'channel_key':'sample_chat','instance_id':'instance','generation':1,'event_id':'event','event_kind':'message',
            'conversation':{'id':'room','type':'dm','thread_id':None},'sender_id':'known','acl_sender_id':'known','sender_name':'',
            'content_parts':[{'type':'text','text':'hello'}],'metadata':{'user_id':'known','session_id':'call:room','debounce_key':'turn'},
            'response_handle':'sample:reply:one',**changes}


def test_raw_content_mode_keeps_empty_whitespace_and_refusal_without_accessors():
    from qwenpaw.channel_protocol.completed_text import project_completed_text
    class Event:
        content=[NS(type='text',text=''),NS(type='text',text='   '),NS(type='text',text=' x\n⟦ original ⟧ '),NS(type='refusal',refusal=' no ')]
        @property
        def get_text_content(self):raise AssertionError('content mode accessed getter')
        @property
        def message(self):raise AssertionError('content mode accessed fallback')
    parts,provenance=project_completed_text(Event(),'content')
    assert provenance is None
    assert parts==[{'type':'text','text':'','role':'message'},{'type':'text','text':'   ','role':'message'},
                   {'type':'text','text':' x\n⟦ original ⟧ ','role':'message'},{'type':'text','text':' no ','role':'refusal'}]


def test_getter_success_preserves_all_exact_values_and_never_reads_fallback():
    from qwenpaw.channel_protocol.completed_text import project_completed_text
    class Event:
        def get_text_content(self):return [NS(text=' a '),NS(text=''),NS(text='   '),NS(refusal='not text'),NS(text=' b ')]
        @property
        def content(self):raise AssertionError('successful getter read content')
        @property
        def message(self):raise AssertionError('successful getter read nested')
    parts,raw=project_completed_text(Event(),'text_sources')
    assert raw.to_mapping()==sources(getter_state='values',getter_texts=[' a ','   ',' b '])
    assert [p['text'] for p in parts]==[' a ','   ',' b ']


@pytest.mark.parametrize('getter_state',['absent','values'])
def test_empty_getter_fallback_top_first_truthy_then_nested(getter_state):
    from qwenpaw.channel_protocol.completed_text import project_completed_text
    event=NS(content=[NS(text=''),NS(refusal='never speak'),NS(text='   '),NS(text='later')],message=NS(content=[NS(text='nested')]))
    if getter_state=='values':event.get_text_content=lambda:[]
    parts,raw=project_completed_text(event,'text_sources')
    assert raw.to_mapping()==sources(getter_state=getter_state,top_texts=['   '])
    assert parts==[{'type':'text','text':'   ','role':'message'}]
    event.content=[NS(refusal='refusal-only')]
    parts,raw=project_completed_text(event,'text_sources')
    assert raw.to_mapping()==sources(getter_state=getter_state,nested_texts=['nested'])
    assert parts==[{'type':'text','text':'nested','role':'message'}]


def test_getter_error_is_explicit_and_does_not_fall_through():
    from qwenpaw.channel_protocol.completed_text import project_completed_text
    class Event:
        def get_text_content(self):raise RuntimeError('secret exception must not cross IPC')
        @property
        def content(self):raise AssertionError('must not fall through')
    parts,raw=project_completed_text(Event(),'text_sources')
    assert parts==[]
    assert raw.to_mapping()==sources(getter_state='error',error_source='getter')
    assert 'secret' not in repr(raw.to_mapping())


@pytest.mark.parametrize('value',[
    sources(extra=True),sources(getter_state='invalid'),sources(top_texts=['a','b']),sources(top_texts=['']),
    sources(getter_texts=['a']),sources(getter_state='values',getter_texts=['a'],top_texts=['b']),
    sources(top_texts=['a'],nested_texts=['b']),sources(getter_state='error'),
    sources(getter_state='error',error_source='getter',nested_texts=['b']),sources(error_source='wrong'),
])
def test_closed_sources_reject_invalid_values_or_precedence(value):
    from qwenpaw.channel_protocol.models import RawCompletedTextSources
    from qwenpaw.channel_protocol.errors import ProtocolValidationError
    with pytest.raises(ProtocolValidationError):RawCompletedTextSources.from_mapping(value)


def test_error_only_event_is_narrow_and_existing_empty_message_stays_invalid():
    from qwenpaw.channel_protocol.models import SendParams
    from qwenpaw.channel_protocol.errors import ProtocolValidationError
    base={'channel_key':'sample_chat','instance_id':'instance','generation':1,'delivery_id':'delivery','to_handle':'sample:reply:one',
          'operation':'message.create','content_parts':[],'content_source':'event'}
    error=sources(getter_state='error',error_source='getter')
    parsed=SendParams.from_mapping({**base,'raw_completed_text_sources':error})
    assert parsed.to_mapping()['raw_completed_text_sources']==error
    for change in [{},{'raw_completed_text_sources':sources()},{'content_source':'direct','raw_completed_text_sources':error},
                   {'operation':'message.edit','raw_completed_text_sources':error}]:
        with pytest.raises(ProtocolValidationError):SendParams.from_mapping({**base,**change})


@pytest.mark.parametrize('value',[True,False,1,'raw','',{},[]])
def test_raw_policy_is_closed_not_truthy_coercion(value):
    from qwenpaw.channel_protocol.response_policy import ResponsePolicy
    from qwenpaw.channel_protocol.errors import ProtocolValidationError
    with pytest.raises(ProtocolValidationError):ResponsePolicy.from_mapping({'streaming':False,'prepare':False,'completion_reaction':False,'raw_completed_text':value})


def test_old_policy_and_known_actor_wire_unchanged_metadata_cannot_forge_unknown():
    from qwenpaw.channel_protocol.response_policy import ResponsePolicy
    from qwenpaw.channel_protocol.models import InboundEvent
    from qwenpaw.channel_protocol.normalization import normalize_inbound_event
    assert 'raw_completed_text' not in ResponsePolicy().to_mapping()
    event=InboundEvent.from_mapping(inbound(metadata={'user_id':'known','session_id':'session','debounce_key':'turn','actor_unknown':True}))
    assert 'actor_unknown' not in event.to_mapping()
    normalized=normalize_inbound_event(event)
    assert 'actor_unknown' not in normalized and 'actor_unknown' not in normalized['meta']
    assert normalized['sender_id']==normalized['acl_sender_id']==normalized['user_id']=='known'


@pytest.mark.parametrize('change',[
    {'actor_unknown':False},{'actor_unknown':1},{'sender_id':'CallSid'},{'acl_sender_id':'display'},
    {'metadata':{'user_id':'CallSid','session_id':'s','debounce_key':'d'}},{'event_kind':'approval'},
])
def test_unknown_actor_requires_explicit_true_double_empty_and_empty_user(change):
    from qwenpaw.channel_protocol.models import InboundEvent
    from qwenpaw.channel_protocol.errors import ProtocolValidationError
    value=inbound(actor_unknown=True,sender_id='',acl_sender_id='',metadata={'user_id':'','session_id':'s','debounce_key':'d'})
    with pytest.raises(ProtocolValidationError):InboundEvent.from_mapping({**value,**change})


def test_unknown_actor_normalization_has_no_sender_fallback_and_still_requires_session():
    from qwenpaw.channel_protocol.models import InboundEvent
    from qwenpaw.channel_protocol.normalization import normalize_inbound_event
    from qwenpaw.channel_protocol.errors import ProtocolValidationError
    event=InboundEvent.from_mapping(inbound(actor_unknown=True,sender_id='',acl_sender_id='',metadata={'user_id':'','session_id':'real-session','debounce_key':'turn'}))
    wire=event.to_mapping();assert wire['actor_unknown'] is True
    payload=normalize_inbound_event(event)
    assert payload['sender_id']==payload['acl_sender_id']==payload['user_id']==''
    assert payload['session_id']=='real-session' and payload['meta']['actor_unknown'] is True
    for key in ['session_id','debounce_key']:
        broken=InboundEvent.from_mapping({**wire,'metadata':{**wire['metadata'],key:''}})
        with pytest.raises(ProtocolValidationError):normalize_inbound_event(broken)
