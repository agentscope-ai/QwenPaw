# Skill Sign Tool

Local Ed25519 signing utility for QwenPaw skill pool **secure import**.

## Quick start

```bash
# 1. Generate keypair (private key stays gitignored under keys/)
python extension/skill_sign/sign_tool/sign_skill.py gen-keypair

# 2. Sign a ZIP
python extension/skill_sign/sign_tool/sign_skill.py sign --input my-skill.zip

# 3. Verify locally
python extension/skill_sign/sign_tool/sign_skill.py verify \
  --input my-skill.zip --sig my-skill.zip.sig

# 4. Regenerate committed examples (valid + tampered)
python extension/skill_sign/sign_tool/sign_skill.py build-examples
```

## Layout

| Path | Committed | Purpose |
|------|-----------|---------|
| `keys/` | No (gitignored) | Local private key |
| `../trust/qwenpaw-skill-signing-public.pem` | Yes | Pinned verification key |
| `examples/valid/` | Yes | Passes verification |
| `examples/invalid/` | Yes | Tampered ZIP, valid sig (must fail) |

## Console

Use **Settings → Skill Pool → 安全导入** and select both `.zip` and `.sig`.

See `extension/Skill Secure Import Design.md`.
