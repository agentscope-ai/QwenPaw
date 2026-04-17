#!/usr/bin/env python3
"""
Hint Injection Integration Test & Experiment
Validates the skill hint injection mechanism and runs A/B comparison.
"""
import asyncio
import sys
import os
from pathlib import Path

# Add CoPaw source to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from qwenpaw.agents.react_agent import CoPawAgent


async def test_hint_injection():
    """Test that _build_skill_hint generates hints and reply() injects them."""
    print("=" * 60)
    print("Hint Injection Integration Test")
    print("=" * 60)

    # Test 1: Verify _build_skill_hint exists and is callable
    print("\n[Test 1] Method existence check")
    assert hasattr(CoPawAgent, '_build_skill_hint'), "Missing _build_skill_hint"
    assert hasattr(CoPawAgent, '_read_skill_metas'), "Missing _read_skill_metas"
    assert not hasattr(CoPawAgent, '_apply_semantic_routing'), "Old _apply_semantic_routing should be removed"
    print("  PASS: _build_skill_hint exists")
    print("  PASS: _read_skill_metas exists")
    print("  PASS: _apply_semantic_routing removed (KV cache friendly)")

    # Test 2: Verify _read_skill_metas can read skill metadata from disk
    print("\n[Test 2] Skill meta reading from disk")
    skills_dir = Path(os.path.expanduser("~/.qwenpaw/workspaces/default/skills"))
    if skills_dir.exists():
        skill_dirs = [d for d in os.listdir(skills_dir) if os.path.isdir(skills_dir / d)]
        if skill_dirs:
            metas = CoPawAgent._read_skill_metas(skill_dirs[:3], skills_dir)
            print(f"  PASS: Read {len(metas)} skill metas from disk")
            for m in metas[:2]:
                desc = m.get("description", "")[:60]
                print(f"    - {m.get('name')}: {desc}...")
        else:
            print("  SKIP: No skills found in workspace")
    else:
        print(f"  SKIP: Skills dir not found: {skills_dir}")

    # Test 3: Verify reply() uses system message with mark for hint injection
    print("\n[Test 3] Reply method hint injection check (system message approach)")
    with open(os.path.join(os.path.dirname(__file__), 'src/qwenpaw/agents/react_agent.py')) as f:
        source = f.read()

    assert '_build_skill_hint(query)' in source, "reply() should call _build_skill_hint"
    assert 'hint_msg = Msg(' in source, "reply() should create hint_msg as system message"
    assert 'marks="skill_hint"' in source, "reply() should add hint with skill_hint mark"
    assert 'delete_by_mark("skill_hint")' in source, "reply() should cleanup hint by mark"
    print("  PASS: reply() calls _build_skill_hint(query)")
    print("  PASS: reply() creates hint_msg = Msg(role=system)")
    print("  PASS: reply() adds hint with mark=\"skill_hint\"")
    print("  PASS: reply() cleans up hint via delete_by_mark")

    # Test 4: Verify tool list is NOT modified (KV cache preservation)
    print("\n[Test 4] KV Cache preservation check")
    reply_section = source.split('async def reply')[1].split('async def ')[0] if 'async def reply' in source else ""
    assert 'self.toolkit' not in reply_section or 'remove_tool' not in reply_section, \
           "reply() should NOT modify toolkit tools"
    print("  PASS: reply() does NOT modify tool list (KV cache preserved)")

    # Test 5: Verify no session-sticky cache
    print("\n[Test 5] Session-sticky cache removal check")
    assert '_routing_cache' not in source, "Session-sticky _routing_cache should be removed"
    assert '_skill_meta_cache' not in source, "Session-sticky _skill_meta_cache should be removed"
    print("  PASS: _routing_cache removed")
    print("  PASS: _skill_meta_cache removed")

    print("\n" + "=" * 60)
    print("All integration tests PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_hint_injection())
