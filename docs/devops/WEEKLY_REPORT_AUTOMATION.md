# CoPaw 周报自动化模板

## 自动生成与管理方案

1. 每周计划文件按 `WEEKLY_REPORT_YYYY-WW.md` 命名，统一存放于 docs/devops/。
2. 自动汇总本周每日计划、路线图变更、upstream PR/issues、fork贡献、遗留问题。
3. 支持批量复盘、进度追踪、团队协作。
4. 可用脚本自动生成周报，便于管理者和团队成员查阅。

---

## 示例自动化脚本（Python伪代码）

```python
import datetime
import glob

today = datetime.date.today()
week = today.isocalendar()[1]
report_path = f'docs/devops/WEEKLY_REPORT_{today.year}-{week:02d}.md'

# 汇总本周每日计划
plan_files = glob.glob(f'docs/devops/DAILY_PLAN_{today.year}-*-*.md')
weekly_content = ''
for file in plan_files:
    with open(file) as f:
        weekly_content += f.read() + '\n\n'

# 生成周报内容
with open(report_path, 'w') as f:
    f.write(f'# CoPaw 周报 {today.year}-W{week:02d}\n\n')
    f.write('## 本周每日计划汇总\n')
    f.write(weekly_content)
    f.write('\n## 路线图变更、贡献、遗留问题\n- ...\n')
```

---

> 可根据实际需求扩展为 shell/Python/Node 脚本，支持自动生成、批量管理、历史复盘。
