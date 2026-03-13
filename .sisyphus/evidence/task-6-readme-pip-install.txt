=== SCENARIO 1: README pip install instructions updated ===

Evidence of successful pip install boostclaw refactoring across 3 README files.

Test 1: Check for stale "pip install copaw" references
Command: grep -rn 'pip install copaw' README.md README_zh.md README_ja.md
Result: 0 matches (PASS)

Test 2: Check for stale "pip install 'copaw[" references
Command: grep -rn "pip install 'copaw\[" README.md README_zh.md README_ja.md
Result: 0 matches (PASS)

Test 3: Count boostclaw pip install references in README.md
Command: grep -c 'pip install boostclaw' README.md
Result: 1 match (PASS)

Updated pip install instructions in all 3 README files:
- README.md line 102: pip install boostclaw
- README.md lines 342-344: pip install 'boostclaw[llamacpp|mlx|ollama]'
- README_zh.md line 102: pip install boostclaw
- README_zh.md lines 346-348: pip install 'boostclaw[llamacpp|mlx|ollama]'
- README_ja.md line 102: pip install boostclaw
- README_ja.md lines 342-344: pip install 'boostclaw[llamacpp|mlx|ollama]'

VERDICT: ALL TESTS PASS ✓
