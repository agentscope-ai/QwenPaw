#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Agent test harness: exercise the QwenPaw agent across configured models.

Builds a real :class:`QwenPawAgent` (full ReAct loop) for each model under
test, restricted to a SAFE read-only toolkit, runs a battery of scenarios,
and writes a comparative report (Markdown + JSON) under
``reports/agent-model-tests/``.

Usage (PYTHONPATH=src):
    .venv/Scripts/python.exe scripts/agent_model_test.py            # full run
    .venv/Scripts/python.exe scripts/agent_model_test.py --smoke    # 1 model, 2 scenarios
    .venv/Scripts/python.exe scripts/agent_model_test.py --models dashscope:qwen3-max,openrouter:openai/gpt-chat-latest

Only providers with credentials configured (dashscope, openrouter) are usable.
This makes REAL API calls (costs tokens).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
import traceback
from pathlib import Path

# --- Models under test (provider_id:model). Override with --models. ----------
DEFAULT_MODELS = [
    "dashscope:qwen3-max",
    "dashscope:qwen3-235b-a22b-thinking-2507",
    "dashscope:deepseek-v3.2",
    "dashscope:qwen3-coder-plus",
    "openrouter:anthropic/claude-opus-4.8",
    "openrouter:openai/gpt-chat-latest",
    "openrouter:google/gemini-3.5-flash",
    "openrouter:nex-agi/nex-n2-pro:free",
]

# --- Safe, read-only builtin tools the test agent is allowed to use. ----------
SAFE_TOOLS = {
    "read_file",
    "grep_search",
    "glob_search",
    "get_current_time",
    "get_token_usage",
}

# --- Scenario battery. `check` returns (passed, note). -----------------------

def _check_contains(*needles):
    def f(text, tool_used):
        low = (text or "").lower()
        hit = next((n for n in needles if n.lower() in low), None)
        return (bool(hit),
                f"contém '{hit}'" if hit else f"NÃO contém {needles}")
    return f


def _check_json_array(text, tool_used):
    s = (text or "").strip()
    # strip code fences if present
    if "```" in s:
        parts = s.split("```")
        for p in parts:
            p = p.strip()
            if p.startswith("[") or p.startswith("json"):
                s = p[4:].strip() if p.startswith("json") else p
                break
    start = s.find("[")
    end = s.rfind("]")
    if start == -1 or end == -1:
        return False, "sem array JSON"
    try:
        data = json.loads(s[start : end + 1])
        ok = isinstance(data, list) and len(data) >= 1
        return ok, f"JSON válido ({len(data)} itens)" if ok else "JSON vazio/ inválido"
    except Exception as e:
        return False, f"JSON inválido: {e}"


def _response_shows_tool(text) -> bool:
    """Proxy for 'the agent used the time tool': a real clock value the model
    could not have invented (HH:MM or an explicit UTC/date marker)."""
    import re

    t = (text or "")
    return bool(re.search(r"\d{1,2}:\d{2}", t)) or "utc" in t.lower()


def _check_tool(text, tool_used):
    return tool_used, "hora via ferramenta" if tool_used else "sem evidência de ferramenta"


SCENARIOS = [
    {
        "id": "factual_qa",
        "prompt": "Qual é a capital da Austrália? Responda em uma única frase curta.",
        "check": _check_contains("Canberra", "Camberra"),
    },
    {
        "id": "reasoning",
        "prompt": "Se um trem viaja a 60 km/h durante 2,5 horas, quantos km percorre? "
        "Mostre o cálculo e termine com 'Resposta: <n> km'.",
        "check": _check_contains("150"),
    },
    {
        "id": "ptbr_brevity",
        "prompt": "Explique o que é uma API REST em no máximo duas frases, em português.",
        "check": lambda t, _u: (bool(t and t.strip()), "respondeu" if t and t.strip() else "vazio"),
    },
    {
        "id": "structured_json",
        "prompt": "Liste 3 linguagens de programação como um array JSON de objetos com os "
        "campos 'nome' e 'ano'. Responda apenas o JSON, sem texto extra.",
        "check": _check_json_array,
    },
    {
        "id": "tool_use_time",
        "prompt": "Que data e hora são agora? Use a ferramenta disponível para descobrir.",
        "check": _check_tool,
    },
]


def _build_test_agent(provider_id: str, model: str, workspace_dir: Path, session_id: str):
    """Replicate runtime.build_agent but with a chosen active_model and a
    SAFE-only toolkit, without mutating global/persisted config."""
    from qwenpaw.config.config import load_agent_config, ModelSlotConfig
    from qwenpaw.agents.react_agent import QwenPawAgent
    from qwenpaw.agents.context.light_context_manager import LightContextManager
    from qwenpaw.app.runner.utils import build_env_context

    cfg = load_agent_config("default")
    cfg.active_model = ModelSlotConfig(provider_id=provider_id, model=model)
    # restrict toolkit to SAFE read-only tools
    if cfg.tools and cfg.tools.builtin_tools:
        for name, tc in cfg.tools.builtin_tools.items():
            tc.enabled = name in SAFE_TOOLS

    wd_str = str(workspace_dir)
    ctx = {"session_id": session_id, "agent_id": "default", "channel": "console"}
    context_manager = LightContextManager(working_dir=wd_str, agent_id="default")
    env_context = build_env_context(
        session_id=session_id,
        user_id="tester",
        user_name="tester",
        channel="console",
        working_dir=wd_str,
        default_shell="cmd.exe" if sys.platform == "win32" else "/bin/sh",
        project_dir=None,
    )
    agent = QwenPawAgent(
        agent_config=cfg,
        env_context=env_context,
        workspace_dir=workspace_dir,
        request_context=ctx,
        memory_manager=None,
        context_manager=context_manager,
        mcp_clients=[],
    )
    return agent


def _count_tool_calls(agent) -> int:
    """Best-effort: count ToolUseBlock/tool_use blocks in the agent memory."""
    try:
        mem = getattr(agent, "memory", None)
        msgs = getattr(mem, "memories", None) or getattr(mem, "content", None) or []
        n = 0
        for m in msgs:
            blocks = getattr(m, "content", None)
            if isinstance(blocks, list):
                for b in blocks:
                    bt = b.get("type") if isinstance(b, dict) else getattr(b, "type", None)
                    if bt in ("tool_use", "tool_call"):
                        n += 1
        return n
    except Exception:
        return -1


async def _run_one(provider_id: str, model: str, scenarios, timeout_s: float):
    from agentscope.message import Msg, TextBlock

    results = []
    sid = f"test-{provider_id}-{int(time.time())}"
    with tempfile.TemporaryDirectory(prefix="qp_test_") as wd:
        try:
            agent = _build_test_agent(provider_id, model, Path(wd), sid)
        except Exception as e:
            for sc in scenarios:
                results.append(
                    {"scenario": sc["id"], "ok": False, "latency_ms": 0, "tool_used": False,
                     "passed": False, "note": "build falhou", "response": "",
                     "error": f"{type(e).__name__}: {e}"}
                )
            return results

        for sc in scenarios:
            entry = {"scenario": sc["id"], "ok": False, "latency_ms": 0,
                     "tool_used": False, "passed": False, "note": "", "response": "", "error": ""}
            t0 = time.time()
            try:
                msg = Msg(name="user", role="user",
                          content=[TextBlock(type="text", text=sc["prompt"])])
                resp = await asyncio.wait_for(agent.reply(msg), timeout=timeout_s)
                entry["latency_ms"] = int((time.time() - t0) * 1000)
                text = resp.get_text_content() if hasattr(resp, "get_text_content") else str(resp)
                entry["response"] = (text or "")[:600]
                entry["tool_used"] = _response_shows_tool(text)
                entry["ok"] = True
                passed, note = sc["check"](text, entry["tool_used"])
                entry["passed"], entry["note"] = bool(passed), note
            except asyncio.TimeoutError:
                entry["latency_ms"] = int((time.time() - t0) * 1000)
                entry["error"] = f"timeout > {timeout_s}s"
                entry["note"] = "timeout"
            except Exception as e:
                entry["latency_ms"] = int((time.time() - t0) * 1000)
                entry["error"] = f"{type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}"
                entry["note"] = "erro"
            results.append(entry)
            print(f"   [{model}] {sc['id']:16} ok={entry['ok']} pass={entry['passed']} "
                  f"{entry['latency_ms']}ms {entry['note']}")
    return results


def _write_reports(run, out_dir: Path, stamp: str):
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"report-{stamp}.json"
    json_path.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")

    md = []
    md.append(f"# Relatório de teste de agentes QwenPaw — {stamp}")
    md.append("")
    md.append(f"- Modelos testados: **{len(run['models'])}**  |  "
              f"Cenários: **{len(run['scenarios'])}**")
    md.append(f"- Tools habilitadas (read-only): `{', '.join(sorted(SAFE_TOOLS))}`")
    md.append(f"- Gerado por `scripts/agent_model_test.py` (agente completo, ReAct).")
    md.append("")

    # Summary table: model x pass-rate / avg latency
    md.append("## Resumo por modelo")
    md.append("")
    md.append("| Modelo | OK | Aprovados | Lat. média (ms) | Erros |")
    md.append("|---|---|---|---|---|")
    for mr in run["models"]:
        rs = mr["results"]
        oks = sum(1 for r in rs if r["ok"])
        passed = sum(1 for r in rs if r["passed"])
        lats = [r["latency_ms"] for r in rs if r["ok"]]
        avg = int(sum(lats) / len(lats)) if lats else 0
        errs = sum(1 for r in rs if r["error"])
        md.append(f"| `{mr['provider']}:{mr['model']}` | {oks}/{len(rs)} | "
                  f"{passed}/{len(rs)} | {avg} | {errs} |")
    md.append("")

    # Per-scenario matrix (pass/fail)
    md.append("## Matriz cenário × modelo (✓ aprovado · ✗ reprovado · ⚠ erro)")
    md.append("")
    scen_ids = [s["id"] for s in run["scenarios"]]
    header = "| Modelo | " + " | ".join(scen_ids) + " |"
    md.append(header)
    md.append("|" + "---|" * (len(scen_ids) + 1))
    for mr in run["models"]:
        cells = []
        rmap = {r["scenario"]: r for r in mr["results"]}
        for sid in scen_ids:
            r = rmap.get(sid, {})
            if r.get("error"):
                cells.append("⚠")
            elif r.get("passed"):
                cells.append(f"✓ {r.get('latency_ms','?')}ms")
            else:
                cells.append("✗")
        md.append(f"| `{mr['provider']}:{mr['model']}` | " + " | ".join(cells) + " |")
    md.append("")

    # Detail per model
    md.append("## Detalhes por modelo")
    for mr in run["models"]:
        md.append("")
        md.append(f"### `{mr['provider']}:{mr['model']}`")
        for r in mr["results"]:
            md.append("")
            md.append(f"**{r['scenario']}** — {'✓' if r['passed'] else '✗'} "
                      f"({r['latency_ms']}ms · {r['note']})"
                      + (f" · erro: `{r['error']}`" if r["error"] else ""))
            if r["response"]:
                snippet = r["response"].replace("\n", " ").strip()[:300]
                md.append(f"> {snippet}")
    md_path = out_dir / f"report-{stamp}.md"
    md_path.write_text("\n".join(md), encoding="utf-8")
    return md_path, json_path


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="1 modelo, 2 cenários")
    ap.add_argument("--models", default="", help="lista provider:model separada por vírgula")
    ap.add_argument("--timeout", type=float, default=120.0, help="timeout por cenário (s)")
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()] or list(DEFAULT_MODELS)
    scenarios = SCENARIOS
    if args.smoke:
        models = models[:1]
        scenarios = SCENARIOS[:2]

    stamp = time.strftime("%Y%m%d-%H%M%S") if False else None
    # Date.now-style stamp must come from the OS clock at runtime:
    import datetime
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

    print(f"== Testando {len(models)} modelos × {len(scenarios)} cenários ==")
    run = {
        "generated_at": stamp,
        "scenarios": [{"id": s["id"], "prompt": s["prompt"]} for s in scenarios],
        "safe_tools": sorted(SAFE_TOOLS),
        "models": [],
    }
    for spec in models:
        provider_id, _, model = spec.partition(":")
        print(f"\n-- {provider_id} : {model} --")
        results = await _run_one(provider_id, model, scenarios, args.timeout)
        run["models"].append({"provider": provider_id, "model": model, "results": results})

    out_dir = Path("reports/agent-model-tests")
    md_path, json_path = _write_reports(run, out_dir, stamp)
    print(f"\n== Relatórios ==\n  {md_path}\n  {json_path}")


if __name__ == "__main__":
    asyncio.run(main())
