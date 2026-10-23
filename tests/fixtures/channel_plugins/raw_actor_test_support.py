"""Copies of normal external samples; no alternative Core/lifecycle implementation."""
import json
from semantic_event_host_suite import semantic_source

RAW = 'send.raw_completed_text.v1'
UNKNOWN = 'event.unknown_actor.v1'


def raw_source(directory, key, *, capabilities=None):
    source = semantic_source(directory, key, capabilities=capabilities)
    path = source / 'channel.json'
    descriptor = json.loads(path.read_text())
    descriptor['capabilities'] = sorted(set(descriptor['capabilities']) | {RAW})
    descriptor['config_schema']['properties']['route_policies']['additionalProperties']['properties']['raw_completed_text'] = {'type':'string','enum':['content','text_sources']}
    path.write_text(json.dumps(descriptor))
    driver = source / key / 'driver.py'
    body = driver.read_text()
    marker = '"content_parts": list(getattr(params, "content_parts", ())),'
    assert body.count(marker) == 1
    body = body.replace(marker, marker + '\n                "raw_completed_text_sources": (params.raw_completed_text_sources.to_mapping() if getattr(params, "raw_completed_text_sources", None) is not None else None),')
    driver.write_text(body)
    return source


def raw_policy_without_cap_source(directory, key, *, capabilities=None):
    source = raw_source(directory,key,capabilities=capabilities)
    path=source/'channel.json';value=json.loads(path.read_text())
    value['capabilities'].remove(RAW);path.write_text(json.dumps(value))
    return source


def actor_source(directory, key, *, capabilities=None):
    source=raw_source(directory,key,capabilities=capabilities)
    path=source/'channel.json';value=json.loads(path.read_text())
    value['capabilities']=sorted(set(value['capabilities'])|{UNKNOWN});path.write_text(json.dumps(value))
    driver=source/key/'driver.py';body=driver.read_text()
    needle='                "event_kind": "message",'
    assert body.count(needle)==1
    body=body.replace(needle,needle+'\n                "actor_unknown": raw.get("actor_unknown", False),')
    driver.write_text(body)
    return source


def actor_without_cap_source(directory,key,*,capabilities=None):
    source=actor_source(directory,key,capabilities=capabilities)
    path=source/'channel.json';value=json.loads(path.read_text())
    value['capabilities'].remove(UNKNOWN);path.write_text(json.dumps(value))
    return source


def unknown_emit(event_id='unknown-event', **changes):
    return {'id':event_id,'type':'dm','room':'room-A','session_id':'voice:real-call-session',
            'sender':'','actor':'','user_id':'','actor_unknown':True,
            'debounce_key':'real-call-session:turn-one','text':'anonymous ordinary question',**changes}
