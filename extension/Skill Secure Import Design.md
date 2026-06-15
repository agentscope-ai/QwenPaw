# Skill Secure Import Design

## Purpose

Provide **Ed25519 detached-signature verification** before importing skill ZIP packages into the shared local skill pool. Unsigned or tampered packages are rejected (fail-closed). A companion **sign tool** lives under `extension/skill_sign/sign_tool/` for local signing and fixture generation.

This slice implements the deferred **source trust verification** entry for skill pool imports only (not ClawHub URL import in v1).

## Scope

| In scope | Out of scope |
|----------|--------------|
| Skill pool secure import API + Console button | Replacing existing unsigned ZIP upload |
| Ed25519 verify (raw bytes, base64 `.sig`) | ClawSec official key / advisory feed gating |
| Sign tool + valid/invalid examples | Workspace-scoped skill upload |
| Integrity delivery self-test net | Multi-signer trust stores |

## Trust model

- **Private key**: `extension/skill_sign/sign_tool/keys/` (gitignored). Generated locally via `gen_keypair.py`.
- **Public key**: `extension/skill_sign/trust/qwenpaw-skill-signing-public.pem` (committed, pinned in verifier).
- **Algorithm**: Ed25519 detached signature over the entire ZIP bytes (`crypto.verify(null, data, pub, sig)` / OpenSSL `pkeyutl -sign -rawin`).
- **Signature file**: single-line base64 (optional trailing newline), 64-byte raw signature when decoded.

## Backend layout (`extension/skill_sign/`)

| Module | Role |
|--------|------|
| `constants.py` | Paths, scheme id |
| `verifier.py` | Decode `.sig`, load pinned public key, verify |
| `pool_import.py` | Verify-then-import orchestration |
| `routes.py` | FastAPI `POST /pool/secure-import` |
| `upload.py` | ZIP upload validation helper |
| `host_bridge.py` | Stable exports + `get_router()` for core bridge |
| `sign_tool/sign_skill.py` | CLI: `sign`, `verify`, `gen-keypair`, `build-examples` |
| `sign_tool/examples/` | Committed fixtures: valid + tampered ZIP + sig |
| `tests/` | Unit + integration entry tests |

Core wiring (minimal host shell):

- `src/qwenpaw/security/skill_sign_bridge.py` — `get_skill_sign_router()` only
- `src/qwenpaw/app/routers/skills.py` — `router.include_router(get_skill_sign_router())` (one line)

Flow:

```
ZIP + .sig → verify_skill_package_signature → fail → 400
                                           → ok → SkillPoolService.import_from_zip
```

## Console layout (`console/src/extension/skill_sign/`)

| Module | Role |
|--------|------|
| `api/client.ts` | `uploadSkillPoolSecureImport(file, signatureFile, options?)` |
| `hooks/useSkillPoolSecureImport.ts` | Import flow (verify API, conflicts, scan warnings) |
| `components/SkillPoolSecureImportButton.tsx` | Button + hidden file input |
| `index.ts` | Public exports |

Host integration:

- `Settings/SkillPool/index.tsx` — renders `<SkillPoolSecureImportButton {...pool.secureImportShell} />`
- `useSkillPool.tsx` — exposes `secureImportShell` callbacks only (no secure-import business logic)

## Examples (testing)

```
extension/skill_sign/sign_tool/examples/
  valid/
    demo-skill/SKILL.md          # source
    demo-skill.zip               # signed package
    demo-skill.zip.sig           # valid signature
  invalid/
    tampered-skill.zip           # valid zip with 1 byte flipped
    tampered-skill.zip.sig       # signature from valid zip (mismatch)
```

Regenerate after key rotation:

```bash
python extension/skill_sign/sign_tool/sign_skill.py build-examples
```

## Test entrypoints

- `extension/skill-sign-selftest.manifest.json` — wired into `extension/integrity-delivery-selftest.manifest.json` as delivery `skill-sign`
- Backend: `extension/skill_sign/tests/test_verifier.py`, `test_integration_entry.py`
- Wiring: `extension/selftest/skill-sign-wiring.test.js`
- Frontend: `console/src/extension/skill_sign/api/client.test.ts`

## i18n keys

- `skillPool.secureImport` / `secureImportHint` / `secureImportSuccess` / `secureImportFailed` / `secureImportSigRequired`

## Future

- Optional second trust anchor (ClawSec official public key) for packages from `clawsec.prompt.security`
- URL import path calling the same verifier before pool install
