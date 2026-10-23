"""Installable third-party malformed-policy producer, never a WeChat Driver.

It inherits the existing executable sample and only changes its describe wire
output, using the same Loader/worker/protocol. No Process response is patched.
"""

import json

from extension_sample import sample_source


def malicious_policy_source(directory, key, *, capabilities=None):
    source = sample_source(directory, key, capabilities=capabilities)
    descriptor_path = source / "channel.json"
    descriptor = json.loads(descriptor_path.read_text())
    descriptor["config_schema"]["properties"]["raw_policy"] = {
        "type": "object",
        "additionalProperties": True,
    }
    descriptor["config_fields"].append("raw_policy")
    descriptor["entrypoint"]["module"] = key + ".policy_producer"
    descriptor["entrypoint"]["qualname"] = "MalformedPolicyProducer"
    descriptor_path.write_text(json.dumps(descriptor))
    (source / key / "policy_producer.py").write_text(
        '"""Adversarial third-party protocol input, not platform logic."""\n'
        "from .driver import Driver\n\n"
        "class MalformedPolicyProducer(Driver):\n"
        "    async def _describe(self, params, request):\n"
        "        self._identity(params)\n"
        "        return dict(self._config['raw_policy'])\n"
    )
    return source
