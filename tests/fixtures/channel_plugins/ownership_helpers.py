# -*- coding: utf-8 -*-
"""Read live Channel custody from the single generic runtime registry."""


def channel_leases(registry):
    return tuple(
        lease
        for lease in registry.runtime_owners.leases()
        if lease.key.kind == "channel"
    )


def channel_resources(registry):
    return [
        registry.runtime_owners.resource(lease)
        for lease in channel_leases(registry)
    ]


def channel_owner(registry, instance_id):
    (lease,) = (
        lease
        for lease in channel_leases(registry)
        if lease.instance_id == instance_id
    )
    return registry.runtime_owners.resource(lease)
