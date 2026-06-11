#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test the NEW AgentScope 2.0 features as wired into qwenpaw.

Exercises, through the real QwenPawAgent / provider stack, the 2.0 building
blocks that did not exist (or worked differently) in 1.x:

  1. streaming event system   -> Agent.reply_stream yields typed AgentEvents
  2. tool-call events         -> ToolCall*/ToolResult* events during a tool run
  3. thinking blocks          -> ThinkingBlock* events from a reasoning model
  4. structured output        -> ChatModel.generate_structured_output(pydantic)
  5. agent state (AgentState) -> state_dict() / load_state_dict() round-trip
  6. middleware (MiddlewareBase) -> qwenpaw middlewares wired on the agent

Writes a Markdown + JSON report under reports/agentscope-v2-features/.
Makes REAL API calls (dashscope). Run with PYTHONPATH=src.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import sys
import tempfile
import traceback
from pathlib import Path

import importlib.util as _u

# Reuse the agent builder from the model harness.
_spec = _u.spec_from_file_location(
    "amt", str(Path(__file__).with_name("agent_model_test.py"))
)
amt = _u.module_from_spec(_spec)
_spec.loader.exec_module(amt)

MODEL = "dashscope:qwen3-max"
THINKING_MODEL = "dashscope:qwen3-235b-a22b-thinking-2507"


def _msg(text: str):
    from agentscope.message import Msg, TextBlock

    return Msg(name="user", role="user", content=[TextBlock(type="text", text=text)])


async def _collect_events(agent, text, timeout):
    """Drive reply_stream and return the list of event class names seen."""
    seen = []
    last_text = ""
    agen = agent.reply_stream(_msg(text))

    async def _run():
        nonlocal last_text
        async for ev in agen:
            seen.append(type(ev).__name__)
            t = getattr(ev, "text", None) or getattr(ev, "delta", None)
            if isinstance(t, str):
                last_text += t

    await asyncio.wait_for(_run(), timeout=timeout)
    return seen, last_text


async def feat_streaming(timeout):
    """1. reply_stream emits the typed 2.0 event lifecycle."""
    pid, model = MODEL.split(":", 1)
    with tempfile.TemporaryDirectory() as wd:
        agent = amt._build_test_agent(pid, model, Path(wd), "feat-stream")
        seen, _ = await _collect_events(agent, "Diga 'olá' em uma palavra.", timeout)
    kinds = set(seen)
    needed = {"ReplyStartEvent", "ReplyEndEvent"}
    has_text = any("TextBlock" in k for k in kinds)
    ok = needed.issubset(kinds) and has_text
    return ok, f"{len(seen)} eventos; tipos: {sorted(kinds)[:8]}"


async def feat_tool_events(timeout):
    """2. ToolCall*/ToolResult* events fire during a real tool run."""
    pid, model = MODEL.split(":", 1)
    with tempfile.TemporaryDirectory() as wd:
        agent = amt._build_test_agent(pid, model, Path(wd), "feat-tool")
        seen, _ = await _collect_events(
            agent, "Que horas são? Use a ferramenta get_current_time.", timeout
        )
    kinds = set(seen)
    has_call = any("ToolCall" in k for k in kinds)
    has_result = any("ToolResult" in k for k in kinds)
    ok = has_call and has_result
    return ok, f"ToolCall={has_call} ToolResult={has_result}; tipos tool: {[k for k in sorted(kinds) if 'Tool' in k]}"


async def feat_thinking(timeout):
    """3. ThinkingBlock* events from a reasoning model."""
    pid, model = THINKING_MODEL.split(":", 1)
    with tempfile.TemporaryDirectory() as wd:
        agent = amt._build_test_agent(pid, model, Path(wd), "feat-think")
        seen, _ = await _collect_events(
            agent, "Quanto é 17 x 23? Pense passo a passo.", timeout
        )
    kinds = set(seen)
    has_think = any("ThinkingBlock" in k for k in kinds)
    return has_think, f"ThinkingBlock events: {[k for k in sorted(kinds) if 'Thinking' in k] or 'nenhum'}"


async def feat_structured_output(timeout):
    """4. ChatModel.generate_structured_output returns a validated pydantic obj."""
    from pydantic import BaseModel, Field
    from qwenpaw.providers.provider_manager import ProviderManager

    class City(BaseModel):
        nome: str = Field(description="nome da cidade")
        pais: str = Field(description="país")
        populacao_milhoes: float = Field(description="população em milhões")

    pid, model = MODEL.split(":", 1)
    pm = ProviderManager.get_instance()
    chat = pm.get_provider(pid).get_chat_model_instance(model)
    msgs = [_msg("Dê os dados de Tóquio.")]
    resp = await asyncio.wait_for(
        chat.generate_structured_output(messages=msgs, structured_model=City),
        timeout=timeout,
    )
    # StructuredResponse is a dataclass: .content holds the parsed dict.
    data = getattr(resp, "content", None)
    ok = isinstance(data, dict) and "nome" in data and "pais" in data
    return ok, f"obj estruturado: {json.dumps(data, ensure_ascii=False)[:120]}"


async def feat_state_roundtrip(timeout):
    """5. AgentState state_dict() / load_state_dict() round-trips."""
    pid, model = MODEL.split(":", 1)
    with tempfile.TemporaryDirectory() as wd:
        a1 = amt._build_test_agent(pid, model, Path(wd), "feat-state-1")
        await asyncio.wait_for(a1.reply(_msg("Meu nome é Duo. Responda 'ok'.")), timeout=timeout)
        dumped = a1.state_dict()
        is_v2 = isinstance(dumped, dict) and "state" in dumped
        a2 = amt._build_test_agent(pid, model, Path(wd), "feat-state-2")
        a2.load_state_dict(dumped)
        restored = a2.state_dict()
        ok = is_v2 and restored.get("state") is not None
    return ok, f"state_dict 2.0={is_v2}; round-trip carregou={restored.get('state') is not None}"


async def feat_middleware(timeout):
    """6. qwenpaw MiddlewareBase chain is wired on the agent."""
    pid, model = MODEL.split(":", 1)
    with tempfile.TemporaryDirectory() as wd:
        agent = amt._build_test_agent(pid, model, Path(wd), "feat-mw")
        # AgentScope 2.0 stores middlewares per hook position.
        mws = []
        for attr in (
            "_reply_middlewares",
            "_reasoning_middlewares",
            "_acting_middlewares",
            "_model_call_middlewares",
            "_system_prompt_middlewares",
        ):
            mws.extend(getattr(agent, attr, None) or [])
        names = sorted({type(m).__name__ for m in mws})
    ok = len(names) > 0
    return ok, f"middlewares: {names}"


FEATURES = [
    ("1. streaming (reply_stream + AgentEvent)", feat_streaming),
    ("2. tool-call events (ToolCall*/ToolResult*)", feat_tool_events),
    ("3. thinking blocks (ThinkingBlock*)", feat_thinking),
    ("4. structured output (generate_structured_output)", feat_structured_output),
    ("5. agent state (AgentState round-trip)", feat_state_roundtrip),
    ("6. middleware (MiddlewareBase wiring)", feat_middleware),
]


async def main():
    timeout = 150.0
    print(f"== Testando {len(FEATURES)} features novas do AgentScope 2.0 no qwenpaw ==")
    results = []
    for title, fn in FEATURES:
        entry = {"feature": title, "ok": False, "note": "", "error": ""}
        try:
            ok, note = await fn(timeout)
            entry["ok"], entry["note"] = bool(ok), note
        except Exception as e:
            entry["error"] = f"{type(e).__name__}: {(str(e).splitlines() or [''])[0][:160]}"
            entry["note"] = "erro"
            entry["_tb"] = traceback.format_exc()[-800:]
        results.append(entry)
        mark = "OK " if entry["ok"] else ("ERR" if entry["error"] else "x  ")
        print(f"  [{mark}] {title}\n        {entry['note'] or entry['error']}")

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path("reports/agentscope-v2-features")
    out.mkdir(parents=True, exist_ok=True)
    run = {"generated_at": stamp, "installed_agentscope": _agentscope_version(),
           "results": results}
    (out / f"report-{stamp}.json").write_text(
        json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")

    md = [f"# AgentScope 2.0 — teste de features novas no qwenpaw ({stamp})", "",
          f"agentscope instalado: **{run['installed_agentscope']}** · "
          f"agente real `QwenPawAgent`, modelo `{MODEL}` (thinking: `{THINKING_MODEL}`).", "",
          "| Feature 2.0 | Resultado | Evidência |", "|---|---|---|"]
    for r in results:
        status = "✅ OK" if r["ok"] else ("⚠️ erro" if r["error"] else "❌ falhou")
        ev = (r["note"] or r["error"]).replace("|", "\\|")[:160]
        md.append(f"| {r['feature']} | {status} | {ev} |")
    passed = sum(1 for r in results if r["ok"])
    md += ["", f"**{passed}/{len(results)} features 2.0 verificadas OK.**"]
    md_path = out / f"report-{stamp}.md"
    md_path.write_text("\n".join(md), encoding="utf-8")
    print(f"\n== {passed}/{len(results)} OK ==\nRelatório: {md_path}")


def _agentscope_version():
    try:
        import agentscope
        return agentscope.__version__
    except Exception:
        return "?"


if __name__ == "__main__":
    asyncio.run(main())
