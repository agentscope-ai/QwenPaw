# QwenPaw Local

Install and enable this plugin from Plugin Manager to manage local models.

See the [Piccolo runtime guide](PICCOLO.md) for build and release instructions, the inference contract, and checkpoint verification.

Run its tests from the repository root:

```sh
python -m pip install -e ".[test]" -r plugins/provider/local-llamacpp/requirements.txt
python -m pytest tests/plugins/local_model -q
```
