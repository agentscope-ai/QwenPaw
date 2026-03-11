#!/usr/bin/env python3
"""
AI 军团协作示例 - 多智能体并行执行

运行：python example_agent_collaboration.py
"""

import sys
import json
import time
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

def create_agent_script(agent_name: str, task_type: str):
    """动态创建智能体脚本（示例）"""
    content = f"""#!/usr/bin/env python3
import sys, json, time
from pathlib import Path

task_file = Path(sys.argv[1])
with open(task_file) as f:
    task = json.load(f)

print(f"[{agent_name}] 开始执行：{{task['type']}}")
time.sleep(2)  # 模拟工作

result = {{
    'agent': '{agent_name}',
    'status': 'DONE',
    'summary': '完成{{task['type']}}'
}}

result_file = task_file.parent / f'result_{agent_name}.json'
with open(result_file, 'w') as f:
    json.dump(result, f, indent=2)

print(f"[{agent_name}] ✅ 完成")
"""
    return content

def main():
    workspace = Path(__file__).parent
    print("🤖 AI 军团协作示例")
    print("="*50)
    
    # 创建示例智能体
    agents = [
        ('agent_a', 'task_type_a'),
        ('agent_b', 'task_type_b'),
        ('agent_c', 'task_type_c')
    ]
    
    # 创建任务
    tasks = []
    for agent_name, task_type in agents:
        task = {
            'id': f'TASK-{agent_name}',
            'agent': agent_name,
            'type': task_type,
            'status': 'PENDING'
        }
        tasks.append((agent_name, task))
        
        # 写入任务文件
        task_file = workspace / f'task_{agent_name}.json'
        with open(task_file, 'w') as f:
            json.dump(task, f, indent=2)
    
    print(f"\n启动 {len(tasks)} 个智能体并行执行...\n")
    
    # 并行执行
    start_time = time.time()
    
    def execute_agent(agent_name, task):
        agent_script = workspace / f'{agent_name}.py'
        task_file = workspace / f'task_{agent_name}.json'
        
        process = subprocess.Popen(
            [sys.executable, str(agent_script), str(task_file)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        stdout, stderr = process.communicate()
        duration = time.time() - start_time
        
        return agent_name, stdout.strip(), duration
    
    with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
        futures = [
            executor.submit(execute_agent, agent, task)
            for agent, task in tasks
        ]
        
        for future in as_completed(futures):
            agent_name, output, duration = future.result()
            print(f"[{agent_name}] 完成（{duration:.2f}秒）")
            for line in output.split('\n'):
                print(f"  {line}")
    
    total_duration = time.time() - start_time
    print(f"\n总耗时：{total_duration:.2f}秒")
    print("✅ 所有智能体完成")

if __name__ == '__main__':
    main()
