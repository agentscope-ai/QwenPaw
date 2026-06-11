#!/usr/bin/env python3
"""
Hook Claude Code: verifica se novos arquivos de skill/agente/plugin
têm contraparte pt-BR. Retorna exit code 1 e mensagem no stderr se faltar.

Uso: python3 scripts/check_ptbr.py <caminho_do_arquivo>
"""
import json
import sys
from pathlib import Path


def check(file_path: str) -> int:
    p = Path(file_path)

    if not p.exists():
        return 0

    # SKILL.md em pasta *-en ou *-zh
    if p.name == "SKILL.md":
        parent = p.parent
        dir_name = parent.name
        if dir_name.endswith("-en") or dir_name.endswith("-zh"):
            base = dir_name.rsplit("-", 1)[0]
            pt_sibling = parent.parent / f"{base}-pt" / "SKILL.md"
            if not pt_sibling.exists():
                print(
                    f"[check_ptbr] AVISO: {p} criado sem contraparte pt-BR.\n"
                    f"  Faltando: {pt_sibling}",
                    file=sys.stderr,
                )
                return 1
        return 0

    # PROFILE.md ou SOUL.md em pasta en/ ou zh/
    if p.name in ("PROFILE.md", "SOUL.md"):
        lang_dir = p.parent
        if lang_dir.name in ("en", "zh"):
            pt_sibling = lang_dir.parent / "pt" / p.name
            if not pt_sibling.exists():
                print(
                    f"[check_ptbr] AVISO: {p} criado sem contraparte pt-BR.\n"
                    f"  Faltando: {pt_sibling}",
                    file=sys.stderr,
                )
                return 1
        return 0

    # plugin.json com description_i18n
    if p.name == "plugin.json":
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return 0
        i18n = data.get("description_i18n", {})
        if i18n and "pt-BR" not in i18n:
            print(
                f"[check_ptbr] AVISO: {p} não tem entrada 'pt-BR' em description_i18n.\n"
                f"  Chaves presentes: {list(i18n.keys())}",
                file=sys.stderr,
            )
            return 1
        return 0

    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: check_ptbr.py <caminho>", file=sys.stderr)
        sys.exit(0)
    sys.exit(check(sys.argv[1]))
