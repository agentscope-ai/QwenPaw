"""Independent public schema-number, detachment and canonical-boundary controls."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pytest

from qwenpaw.channel_protocol.canonical import canonical_json
from qwenpaw.channel_protocol.errors import DescriptorValidationError
from qwenpaw.channel_protocol.shared import SharedChannelDescriptor

SOURCE=Path(__file__).resolve().parents[3]/'plugins/channel/imessage/channel.json'


def candidate(value):
    result=json.loads(SOURCE.read_text())
    result['config_schema']={'type':'object','properties':{'value':{'default':value}}}
    result['config_fields']=['value']
    return result


@pytest.mark.parametrize('value,want',[
    (1.0,1.0),(0.125,0.125),(Decimal('1.0'),1.0),
    (Decimal('0.1'),0.1),(Decimal('0.125'),0.125),
])
def test_schema_numbers_are_exact_native_json_values(value,want):
    descriptor=SharedChannelDescriptor.from_mapping(candidate(value))
    actual=descriptor.config_schema['properties']['value']['default']
    assert type(actual) is float and actual==want
    encoded=json.dumps(descriptor.to_mapping(),allow_nan=False)
    loaded=SharedChannelDescriptor.from_json(encoded)
    assert loaded.to_mapping()==descriptor.to_mapping()
    assert json.loads(encoded)['config_schema']['properties']['value']['default']==want


def test_schema_copy_deep_detaches_both_directions_and_preserves_scalars():
    source=candidate({'nested':[Decimal('0.125'),{'truth':True,'falsehood':False,'min':-(2**63),'max':2**63-1}], 'tuple':(1,2)})
    descriptor=SharedChannelDescriptor.from_mapping(source)
    output=descriptor.to_mapping()
    expected={'nested':[0.125,{'truth':True,'falsehood':False,'min':-9223372036854775808,'max':9223372036854775807}], 'tuple':[1,2]}
    actual=descriptor.config_schema['properties']['value']['default']
    assert actual==expected
    assert type(actual['nested'][1]['truth']) is bool
    assert type(actual['nested'][1]['falsehood']) is bool
    assert type(actual['nested'][1]['min']) is int
    assert type(actual['nested'][1]['max']) is int
    source['config_schema']['properties']['value']['default']['nested'][1]['truth']='changed source'
    output['config_schema']['properties']['value']['default']['nested'][1]['max']=0
    assert descriptor.config_schema['properties']['value']['default']==expected
    assert json.loads(json.dumps(descriptor.to_mapping()))['config_schema']['properties']['value']['default']==expected


@pytest.mark.parametrize('value',[
    Decimal('0.12345678901234567890123456789'),
    float('inf'),float('-inf'),float('nan'),Decimal('Infinity'),Decimal('NaN'),
    2**63,-(2**63)-1,
    {'é':1,'e\u0301':2},
])
def test_schema_invalid_or_unrepresentable_values_fail_closed(value):
    with pytest.raises(DescriptorValidationError):
        SharedChannelDescriptor.from_mapping(candidate(value))


def test_canonical_float_and_raw_duplicate_boundaries_remain_closed():
    with pytest.raises(DescriptorValidationError,match='Binary floats'):
        canonical_json({'default':0.125})
    raw=json.dumps(candidate(1))
    duplicate=raw.replace('"default": 1','"default": 1, "default": 2')
    assert duplicate!=raw
    with pytest.raises(DescriptorValidationError):
        SharedChannelDescriptor.from_json(duplicate)
    invalid=candidate(1); invalid['schema_version']=True
    with pytest.raises(DescriptorValidationError):
        SharedChannelDescriptor.from_mapping(invalid)
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()=='6bc76192fae74cfe3b5102c6af875dceadefb5b903ded97fc989f1beaa0a67e4'
