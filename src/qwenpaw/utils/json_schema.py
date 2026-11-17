# -*- coding: utf-8 -*-
"""JSON Schema validation against bundled and supplied resources only."""

from collections.abc import Mapping
from functools import lru_cache
import json

from jsonschema.validators import validator_for
from jsonschema_specifications import REGISTRY as SPECIFICATIONS
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable
from referencing.jsonschema import specification_with

# No retrieve callback: even an HTTP/file URI must identify an in-memory resource.
_REGISTRY = Registry().with_resources(SPECIFICATIONS.items())


def check_schema_references(schema, *, validator_class=None):
    """Check schema structure and resolve references without acquiring resources."""
    cls = validator_class or validator_for(schema)
    cls.check_schema(schema)

    def resource(contents, validator):
        return Resource(
            contents,
            specification_with(validator.ID_OF(validator.META_SCHEMA)),
        )

    root = resource(schema, cls)
    uri = root.id() or ""
    registry = _REGISTRY.with_resource(uri, root).crawl()
    pending = [(root, registry.resolver(uri), cls)]
    seen = set()
    try:
        while pending:
            current, resolver, validator = pending.pop()
            contents = current.contents
            # The same Python subschema can occur under different URI bases.
            key = (id(contents), resolver._base_uri)
            if not isinstance(contents, Mapping) or key in seen:
                continue
            seen.add(key)
            for keyword in ("$ref", "$dynamicRef", "$recursiveRef"):
                if keyword in contents and keyword in validator.VALIDATORS:
                    resolved = resolver.lookup(contents[keyword])
                    target = validator_for(
                        resolved.contents,
                        default=validator,
                    )
                    pending.append(
                        (
                            resource(resolved.contents, target),
                            resolved.resolver,
                            target,
                        ),
                    )
            specification = specification_with(
                validator.ID_OF(validator.META_SCHEMA),
            )
            for child in specification.subresources_of(contents):
                target = validator_for(child, default=validator)
                child_resource = resource(child, target)
                pending.append(
                    (
                        child_resource,
                        resolver.in_subresource(child_resource),
                        target,
                    ),
                )
    except Unresolvable:
        raise ValueError(
            "JSON Schema reference is not available locally",
        ) from None


def schema_validator(schema, *, validator_class=None):
    """Return a checked validator with no implicit network or file retrieval."""
    cls = validator_class or validator_for(schema)
    check_schema_references(schema, validator_class=cls)
    return cls(schema, registry=_REGISTRY)


@lru_cache(maxsize=128)
def _checked_schema(serialized, validator_class):
    """Retain only content-bound check evidence, never mutable validators."""
    check_schema_references(
        json.loads(serialized),
        validator_class=validator_class,
    )


def prepared_schema_validator(schema, *, validator_class=None):
    """Prepare a private JSON snapshot; async callers offload this CPU work."""
    serialized = json.dumps(
        schema,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    snapshot = json.loads(serialized)
    cls = validator_class or validator_for(snapshot)
    _checked_schema(serialized, cls)
    return cls(snapshot, registry=_REGISTRY)
