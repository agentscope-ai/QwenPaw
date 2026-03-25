# CoPaw 年度报告自动化模板

## 自动生成与管理方案

1. 每年报告文件按 `YEARLY_REPORT_YYYY.md` 命名，统一存放于 docs/devops/。
2. 自动汇总本年度月报、周报、每日计划、路线图变更、upstream PR/issues、fork贡献、遗留问题。
3. 支持批量复盘、进度追踪、团队协作。
4. 可用脚本自动生成年度报告，便于管理者和团队成员查阅。

---

## 示例自动化脚本（Python伪代码）

```python
import datetime
import glob

today = datetime.date.today()
report_path = f'docs/devops/YEARLY_REPORT_{today.year}.md'

# 汇总本年度月报
monthly_files = glob.glob(f'docs/devops/MONTHLY_REPORT_{today.year}-*.md')
yearly_content = ''
for file in monthly_files:
    with open(file) as f:
        yearly_content += f.read() + '\n\n'

# 生成年度报告内容
with open(report_path, 'w') as f:
    f.write(f'# CoPaw 年度报告 {today.year}\n\n')
    f.write('## 本年度月报汇总\n')
    f.write(yearly_content)
    f.write('\n## 路线图变更、贡献、遗留问题\n- ...\n')
```

---

> 可根据实际需求扩展为 shell/Python/Node 脚本，支持自动生成、批量管理、历史复盘。
