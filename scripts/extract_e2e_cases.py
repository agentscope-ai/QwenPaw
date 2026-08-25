#!/usr/bin/env python3
"""
Extract E2E test case information from Playwright test files.
Generates a markdown catalog with test_id, purpose, steps, and checkpoints.
"""
import ast
import os
import re
from pathlib import Path
from typing import Dict, List, Optional


def extract_test_cases(test_dir: str) -> List[Dict]:
    """Extract test case info from all test_*.py files in test_dir."""
    cases = []
    test_path = Path(test_dir)
    
    for py_file in sorted(test_path.glob("test_*.py")):
        module_name = py_file.stem.replace("test_", "")
        
        with open(py_file, "r", encoding="utf-8") as f:
            source = f.read()
        
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            print(f"Warning: Failed to parse {py_file}: {e}")
            continue
        
        # Extract module-level docstring
        module_doc = ast.get_docstring(tree) or ""
        
        # Extract priority from module docstring
        priority = "unknown"
        if "P0" in module_doc:
            priority = "P0"
        elif "P1" in module_doc:
            priority = "P1"
        elif "P2" in module_doc:
            priority = "P2"
        
        # Walk through classes and methods
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_doc = ast.get_docstring(node) or ""
                
                # Extract test_id from class docstring
                test_id_match = re.search(r'(P\d{3}-\d+|TEST-\d+)', class_doc)
                test_id = test_id_match.group(1) if test_id_match else None
                
                # Extract coverage points
                coverage_points = []
                in_coverage = False
                for line in class_doc.split("\n"):
                    line = line.strip()
                    if line.startswith("Coverage:"):
                        in_coverage = True
                        continue
                    if in_coverage:
                        if line and (line[0].isdigit() or line.startswith("-")):
                            coverage_points.append(line.lstrip("0123456789.- "))
                        else:
                            in_coverage = False
                
                # Extract business scenario
                scenario = ""
                in_scenario = False
                for line in class_doc.split("\n"):
                    line = line.strip()
                    if line.startswith("Business scenario:"):
                        in_scenario = True
                        continue
                    if in_scenario:
                        if line:
                            scenario += line + " "
                        else:
                            break
                scenario = scenario.strip()
                
                # Extract test methods
                for method in node.body:
                    if isinstance(method, ast.FunctionDef) and method.name.startswith("test_"):
                        method_doc = ast.get_docstring(method) or ""
                        
                        # Extract steps from method docstring
                        steps = []
                        in_steps = False
                        for line in method_doc.split("\n"):
                            line = line.strip()
                            if line.startswith("Steps:"):
                                in_steps = True
                                continue
                            if in_steps:
                                if line and (line[0].isdigit() or line.startswith("-")):
                                    steps.append(line.lstrip("0123456789.- "))
                                else:
                                    in_steps = False
                        
                        # Extract verification points (assert statements)
                        checkpoints = []
                        for stmt in ast.walk(method):
                            if isinstance(stmt, ast.Assert):
                                # Try to extract assertion message
                                if stmt.msg and isinstance(stmt.msg, ast.Constant):
                                    checkpoints.append(str(stmt.msg.value))
                                else:
                                    checkpoints.append("Assertion check")
                        
                        case = {
                            "file": py_file.name,
                            "module": module_name,
                            "class": node.name,
                            "method": method.name,
                            "test_id": test_id or method.name,
                            "priority": priority,
                            "purpose": method_doc.split("\n")[0] if method_doc else "",
                            "coverage": coverage_points,
                            "scenario": scenario,
                            "steps": steps,
                            "checkpoints": checkpoints[:5],  # Limit to 5
                        }
                        cases.append(case)
    
    return cases


def generate_markdown(cases: List[Dict], output_file: str):
    """Generate markdown catalog from extracted cases."""
    # Group by module
    by_module = {}
    for case in cases:
        module = case["module"]
        if module not in by_module:
            by_module[module] = []
        by_module[module].append(case)
    
    lines = [
        "# E2E 测试用例目录",
        "",
        f"**总计**: {len(cases)} 条用例",
        "",
        "---",
        "",
    ]
    
    for module in sorted(by_module.keys()):
        module_cases = by_module[module]
        lines.append(f"## {module.upper()} 模块")
        lines.append("")
        lines.append(f"用例数：{len(module_cases)}")
        lines.append("")
        lines.append("| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |")
        lines.append("|------|--------|--------|----------|--------|")
        
        for case in module_cases:
            test_id = case["test_id"]
            name = case["method"]
            priority = case["priority"]
            purpose = case["purpose"][:50] + "..." if len(case["purpose"]) > 50 else case["purpose"]
            coverage = ", ".join(case["coverage"][:3])
            
            lines.append(f"| {test_id} | {name} | {priority} | {purpose} | {coverage} |")
        
        lines.append("")
        lines.append("### 详细用例")
        lines.append("")
        
        for case in module_cases:
            lines.append(f"#### {case['test_id']}: {case['method']}")
            lines.append("")
            lines.append(f"**优先级**: {case['priority']}")
            lines.append("")
            lines.append(f"**测试目的**: {case['purpose']}")
            lines.append("")
            
            if case["scenario"]:
                lines.append(f"**业务场景**: {case['scenario']}")
                lines.append("")
            
            if case["steps"]:
                lines.append("**测试流程**:")
                lines.append("")
                for i, step in enumerate(case["steps"], 1):
                    lines.append(f"{i}. {step}")
                lines.append("")
            
            if case["checkpoints"]:
                lines.append("**校验点**:")
                lines.append("")
                for cp in case["checkpoints"]:
                    lines.append(f"- {cp}")
                lines.append("")
            
            lines.append("---")
            lines.append("")
    
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    
    print(f"Generated {output_file} with {len(cases)} cases")


if __name__ == "__main__":
    import sys
    
    test_dir = sys.argv[1] if len(sys.argv) > 1 else "tests"
    output_file = sys.argv[2] if len(sys.argv) > 2 else "test_cases_e2e.md"
    
    cases = extract_test_cases(test_dir)
    generate_markdown(cases, output_file)
