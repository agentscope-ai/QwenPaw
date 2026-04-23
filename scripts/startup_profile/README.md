# 🚀 QwenPaw Startup Performance Analyzer

One-click analysis of QwenPaw startup performance, identify bottlenecks, and provide optimization suggestions.

## Quick Start

```bash
# 1. Generate report
python scripts/startup_profile/analyze.py

# 2. Start local server to view (recommended)
python scripts/startup_profile/serve.py
```

After execution:
1. Collect import time data
2. Collect function execution trace (optional)
3. Generate JSON data
4. View report via HTTP server

**Note**: Due to browser security restrictions (CORS), opening HTML directly with `file://` protocol cannot load data.
Please use `serve.py` or manually start an HTTP server:
```bash
cd /path/to/QwenPaw
python -m http.server 8000
# Visit: http://localhost:8000/scripts/startup_profile/output/report.html
```

## Generated Files

```
output/
├── importtime.log         # Import time raw log
├── execution_trace.json   # Function execution trace (if successful)
├── analysis.json          # Analysis data (core)
└── report.html            # Visual report ⭐
```

## Report Features

- **Import Time Analysis** - QwenPaw modules and third-party library import time ranking
- **Function Execution Time** - Top 20 function execution time statistics
- **Function Call Tree** - Complete function call hierarchy and timing (limited to 5 levels deep, top 10 calls per level)
- **Interactive Charts** - Chart.js horizontal bar chart visualization
- **Bilingual Support** - Chinese/English one-click toggle
- **Performance Markers** - Auto-mark fast/medium/slow functions based on timing (green/yellow/red)

## How It Works

1. **Data Collection**
   - Use Python `-X importtime` to collect import time
   - Use `exec_tracer` to track function calls

2. **Data Analysis**
   - Parse log files
   - Categorize statistics (QwenPaw/third-party/stdlib)
   - Calculate percentages and performance metrics

3. **Visualization**
   - HTML reads JSON data
   - Interactive charts and tables
   - Supports search, sort, filter

## File Description

- `analyze.py` - Data collection and analysis script
- `viewer.html` - Visualization interface (bilingual)
- `README.md` - Chinese documentation
- `README_EN.md` - English documentation

## FAQ

**Q: Why do results vary each run?**
A: Import time is affected by system load. Run multiple times and take average.

**Q: How to compare before/after optimization?**
A: Save `output/` directory, re-run after optimization and compare.

**Q: Function trace fails?**
A: Normal, doesn't affect import analysis. Can use `exec_tracer` separately.

## Technical Details

- Python 3.8+
- No extra dependencies (except QwenPaw itself)
- Pure JSON data output
- HTML runs standalone, viewable offline

## Related Tools

- `src/qwenpaw/utils/startup_display.py` - Startup banner display

---

**Version**: 2.0.0
**Author**: QwenPaw Team
**Updated**: 2026-04-17
