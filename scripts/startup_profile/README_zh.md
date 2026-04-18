# 🚀 QwenPaw 启动性能分析工具

一键分析 QwenPaw 启动性能，识别瓶颈，提供优化建议。

## 快速开始

```bash
# 1. 生成报告
python scripts/startup_profile/analyze.py

# 2. 启动本地服务器查看（推荐）
python scripts/startup_profile/serve.py
```

执行后：
1. 收集 import 时间数据
2. 收集函数执行追踪（可选）
3. 生成 JSON 数据
4. 使用 HTTP 服务器查看报告

**注意**：由于浏览器安全限制（CORS），直接用 `file://` 协议打开 HTML 无法加载数据。
请使用 `serve.py` 或手动启动 HTTP 服务器：
```bash
cd /path/to/QwenPaw
python -m http.server 8000
# 访问: http://localhost:8000/scripts/startup_profile/output/report.html
```

## 生成文件

```
output/
├── importtime.log         # Import 时间原始日志
├── execution_trace.json   # 函数执行追踪（如果成功）
├── analysis.json          # 分析数据（核心）
└── report.html            # 可视化报告 ⭐
```

## 报告功能

- **Import 时间分析** - QwenPaw 模块和第三方库导入耗时排名
- **函数执行时间** - Top 20 函数执行时间统计
- **函数调用树** - 完整的函数调用层级关系和耗时（限制深度 5 层，每层最多显示前 10 个调用）
- **交互式图表** - Chart.js 横向柱状图可视化
- **双语支持** - 中英文一键切换
- **性能标记** - 根据耗时自动标记快/中/慢函数（绿/黄/红）

## 工作原理

1. **数据收集**
   - 使用 Python `-X importtime` 收集 import 时间
   - 使用 `exec_tracer` 追踪函数调用

2. **数据分析**
   - 解析日志文件
   - 分类统计（QwenPaw/第三方/标准库）
   - 计算占比和性能指标

3. **可视化展示**
   - HTML 读取 JSON 数据
   - 交互式图表和表格
   - 支持搜索、排序、过滤

## 文件说明

- `analyze.py` - 数据收集和分析脚本
- `viewer.html` - 可视化界面（双语）
- `README.md` - 中文文档
- `README_EN.md` - 英文文档

## 常见问题

**Q: 为什么每次结果不同？**
A: Import 时间受系统负载影响，建议多次运行取平均值。

**Q: 如何对比优化前后？**
A: 保存 `output/` 目录，优化后重新运行对比。

**Q: 函数追踪失败怎么办？**
A: 正常现象，不影响 import 分析。可单独使用 `exec_tracer`。

## 技术细节

- Python 3.8+
- 无额外依赖（除了 QwenPaw 本身）
- 纯 JSON 数据输出
- HTML 独立运行，可离线查看

## 相关工具

- `src/qwenpaw/utils/startup_display.py` - 启动横幅显示

---

**版本**: 2.0.0
**作者**: QwenPaw Team
**更新**: 2026-04-17
