"""Prepared real-worker controls; run only on root's combined source freeze."""
import os
from types import SimpleNamespace as NS
import pytest
from extension_process_suite import eventually
from semantic_event_host_suite import semantic_source
from raw_actor_test_support import raw_source, raw_policy_without_cap_source, actor_source, actor_without_cap_source, unknown_emit

pytest_plugins=['extension_process_suite']


def policy(mode):
    return {'room-A':{'streaming':False,'prepare':False,'completion_reaction':False,'raw_completed_text':mode}}


def request_for(channel):
    request=channel.build_agent_request_from_native({'sender_id':'known','session_id':'room-A','content_parts':[{'type':'text','text':'question'}],'meta':{}})
    return request,channel.get_to_handle_from_request(request)


@pytest.mark.asyncio
async def test_default_semantic_without_raw_optin_retains_presentation(runtime):
    from qwenpaw.schemas import Message, TextContent, RefusalContent
    rt=await runtime(source_factory=semantic_source)
    request,target=request_for(rt.channel)
    event=Message(object='message',type='reasoning',role='assistant',status='completed',content=[TextContent(text='alpha\n⟦ original ⟧'),RefusalContent(refusal='no')])
    meta={}
    async with rt.channel._response_scope(meta):
        await rt.channel.on_event_message_completed(request,target,event,meta)
    effects=(await rt.process.call('fixture.inspect',{}))['effects']
    sent=[x for x in effects if x['operation']=='message.create']
    assert len(sent)==1 and sent[0]['content_parts']==[{'type':'text','text':'alpha','role':'reasoning'}]
    assert sent[0]['pid']==rt.process.health_snapshot()['pid']!=os.getpid()


@pytest.mark.asyncio
async def test_raw_policy_without_descriptor_capability_rejected_before_effect(runtime):
    from qwenpaw.schemas import Message,TextContent
    from qwenpaw.channel_protocol.errors import ProtocolValidationError
    rt=await runtime(source_factory=raw_policy_without_cap_source,route_policies=policy('content'))
    request,target=request_for(rt.channel)
    with pytest.raises(ProtocolValidationError):
        await rt.channel.on_event_message_completed(request,target,Message(object='message',type='message',role='assistant',status='completed',content=[TextContent(text='original')]),{})
    state=await rt.process.call('fixture.inspect',{})
    assert not state['effects']


@pytest.mark.asyncio
@pytest.mark.parametrize('origin',['getter','top','nested'])
async def test_actual_worker_receives_lazy_raw_text_sources_and_provenance(runtime,origin):
    rt=await runtime(source_factory=raw_source,route_policies=policy('text_sources'))
    request,target=request_for(rt.channel)
    event=NS(object='message',type='message',role='assistant',status='completed',metadata={},content=[NS(type='refusal',refusal='do not speak')])
    if origin=='getter':
        event.get_text_content=lambda:[NS(text=' a '),NS(text='   '),NS(text=' b ')]
        values=[' a ','   ',' b '];getter_state='values'
    elif origin=='top':
        event.content=[NS(text=''),NS(text=' top '),NS(text='later')];values=[' top '];getter_state='absent'
    else:
        event.message=NS(content=[NS(text=' nested '),NS(text='later')]);values=[' nested '];getter_state='absent'
    meta={}
    async with rt.channel._response_scope(meta):
        await rt.channel.on_event_message_completed(request,target,event,meta)
    state=await rt.process.call('fixture.inspect',{})
    effects=[x for x in state['effects'] if x['operation']=='message.create']
    assert len(effects)==1 and effects[0]['pid']==state['pid']!=os.getpid()
    assert effects[0]['content_source']=='event'
    assert effects[0]['content_parts']==[{'type':'text','text':v,'role':'message'} for v in values]
    expected={'getter_state':getter_state,'getter_texts':[],'top_texts':[],'nested_texts':[]}
    expected[origin+'_texts']=values
    assert effects[0]['raw_completed_text_sources']==expected
    assert len(state['finish_calls'])==1


@pytest.mark.asyncio
async def test_unknown_open_and_open_with_historical_list_reach_actual_agent(runtime,monkeypatch):
    from real_host_runtime import bind_real_runtime
    rt=await runtime(source_factory=actor_source)
    host=await bind_real_runtime(rt,monkeypatch)
    rt.channel.allow_from={'historical-known-user'}
    ack=await rt.process.call('fixture.emit',{'event':unknown_emit(shared_admission=True)})
    assert ack['accepted_event_ids']==['unknown-event']
    await eventually(lambda:bool(host.calls) and bool(host.builds))
    # Existing fixture's bounded eventual helper is used; no timeout expansion.
    await eventually(lambda:any(e.get('object')=='response' and e.get('status')=='completed' for e in host.events))
    state=await rt.process.call('fixture.inspect',{})
    assert host.builds[0]['agent']=='QwenPawAgent' and host.calls[0]['pid']==os.getpid()
    assert rt.ws.requests[0].user_id=='' and rt.ws.requests[0].session_id=='voice:real-call-session'
    assert rt.ws.requests[0].channel_meta['actor_unknown'] is True
    actual=[x for x in state['effects'] if x['operation']=='message.create']
    assert actual and all(x['pid']==rt.process.health_snapshot()['pid']!=os.getpid() for x in actual)
    store=rt.channel._get_acl_store()
    assert not store.is_whitelisted(rt.key,'') and store.get_all_pending()==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('restriction',['dm_allowlist','group_allowlist','dm_acl','group_acl'])
async def test_unknown_restricted_rejected_before_pending_or_queue(runtime,restriction):
    rt=await runtime(source_factory=actor_source,capture_ingress=True)
    is_group=restriction.startswith('group')
    rt.channel.allow_from={'','known'}
    if restriction.endswith('allowlist'):setattr(rt.channel,'group_policy' if is_group else 'dm_policy','allowlist')
    else:setattr(rt.channel,'access_control_group' if is_group else 'access_control_dm',True)
    store=rt.channel._get_acl_store();before=store.get_all_pending()
    ack=await rt.process.call('fixture.emit',{'event':unknown_emit(type='group' if is_group else 'dm')})
    assert ack['accepted_event_ids']==[]
    assert ack['rejected_events'][0]['reason_code']=='ACCESS_DENIED'
    assert not rt.ws.received and not rt.ws.requests
    assert store.get_all_pending()==before and not store.is_whitelisted(rt.key,'')


@pytest.mark.asyncio
async def test_known_actor_whitelist_positive_negative_and_unknown_approvals_stay_strict(runtime):
    rt=await runtime(source_factory=actor_source,capture_ingress=True)
    rt.channel.access_control_dm=True;store=rt.channel._get_acl_store();store.set_whitelist(rt.key,['known'])
    known=unknown_emit('known-event',actor_unknown=False,sender='known',actor='known',user_id='known')
    ack=await rt.process.call('fixture.emit',{'event':known})
    assert ack['accepted_event_ids']==['known-event'] and rt.ws.received[0]['acl_sender_id']=='known'
    rejected=await rt.process.call('fixture.emit',{'event':{**known,'id':'unlisted','sender':'other','actor':'other','user_id':'other'}})
    assert rejected['accepted_event_ids']==[] and rejected['rejected_events'][0]['reason_code']=='ACCESS_DENIED'
    for command in ['/approve pending','/deny pending','/approval approve pending']:
        with pytest.raises(ValueError,match='APPROVAL_OPERATOR_UNAVAILABLE'):
            rt.channel.build_agent_request_from_native({'sender_id':'','acl_sender_id':'','session_id':'voice:call',
                'content_parts':[{'type':'text','text':command}],'meta':{'actor_unknown':True,'user_id':''}})


@pytest.mark.asyncio
async def test_nonoptin_shared_driver_and_host_each_reject_unknown_actor(runtime):
    from qwenpaw.channel_protocol.errors import RpcError
    rt=await runtime(source_factory=actor_without_cap_source,capture_ingress=True)
    with pytest.raises(RpcError):await rt.process.call('fixture.emit',{'event':unknown_emit('driver-check',shared_admission=True)})
    ack=await rt.process.call('fixture.emit',{'event':unknown_emit('host-check')})
    assert ack['accepted_event_ids']==[] and ack['rejected_events'][0]['reason_code']=='CAPABILITY_REQUIRED'
    assert not rt.ws.received


@pytest.mark.asyncio
async def test_unknown_same_session_stays_workspace_scoped_and_old_generation_rejected(runtime):
    first=await runtime(source_factory=actor_source,capture_ingress=True,workspace_name='unknown-one')
    second=await runtime(existing_loader=first.loader,capture_ingress=True,workspace_name='unknown-two')
    event=unknown_emit('same-native-id')
    a=await first.process.call('fixture.emit',{'event':event})
    b=await second.process.call('fixture.emit',{'event':event})
    assert a['accepted_event_ids']==b['accepted_event_ids']==['same-native-id']
    assert len(first.ws.received)==len(second.ws.received)==1
    assert first.channel._identity().instance_id!=second.channel._identity().instance_id
    assert first.channel._runtime_lease.key.scope_id!=second.channel._runtime_lease.key.scope_id
    old=second.channel._identity().to_mapping()
    await second.loader.lifecycle.set_enabled(second.key,False)
    await second.loader.lifecycle.set_enabled(second.key,True)
    second.channel=await second.manager.get_channel(second.key)
    second.process=second.channel.channel_process
    current=second.channel._identity().to_mapping()
    assert current['instance_id']==old['instance_id'] and current['generation']>old['generation']
    rejected=await second.process.call('fixture.emit',{'event':unknown_emit('old-generation',identity=old)})
    assert rejected['accepted_event_ids']==[] and rejected['rejected_events'][0]['reason_code']=='STALE_GENERATION'
    assert len(first.ws.received)==len(second.ws.received)==1


@pytest.mark.asyncio
async def test_raw_provenance_changes_fingerprint_unknown_never_replays(runtime):
    rt=await runtime(source_factory=raw_source,route_policies=policy('text_sources'))
    _,target=request_for(rt.channel);meta={}
    await rt.channel._response_policy(target,meta)
    identity=rt.channel._identity().to_mapping()
    params={**identity,'delivery_id':'raw-unknown-once','to_handle':meta['response_handle'],'operation':'message.create',
            'content_source':'event','content_parts':[{'type':'text','text':' x ','role':'message'}],
            'raw_completed_text_sources':{'getter_state':'absent','getter_texts':[],'top_texts':[' x '],'nested_texts':[]}}
    await rt.process.call('fixture.fault',{'mode':'unknown'})
    result=await rt.process.call('channel.send',params)
    assert result['state']=='unknown'
    assert await rt.process.call('channel.send',params)==result
    changed={**params,'raw_completed_text_sources':{'getter_state':'values','getter_texts':[' x '],'top_texts':[],'nested_texts':[]}}
    conflict=await rt.process.call('channel.send',changed)
    assert conflict['state']=='failed' and conflict['reason_code']=='DELIVERY_CONFLICT'
    await rt.process.call('channel.response.finish',{**identity,'response_handle':meta['response_handle'],'outcome':'completed'})
    assert await rt.process.call('channel.send',params)==result
    state=await rt.process.call('fixture.inspect',{})
    effects=[row for row in state['effects'] if row['operation']=='message.create']
    assert len(effects)==1 and effects[0]['pid']==state['pid']!=os.getpid()
