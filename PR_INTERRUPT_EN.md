# Pull Request: Add Session Interrupt Mechanism

## 📝 Description

**Title**: feat: Add session interrupt mechanism to allow users to stop agent execution

**Type**: Feature Request / Enhancement

---

## 🎯 Background and Motivation

### Problem Statement

When CoPaw Agent executes long-running tasks (downloading large datasets, generating complex reports, browsing multiple web pages, etc.), users cannot interrupt the current execution. This leads to:

1. **Poor User Experience**: Even if the instruction is wrong, users must wait for task completion
2. **Resource Waste**: Wrong tasks continue executing, wasting API quotas and time
3. **Inability to Adjust**: Users cannot provide new requirements until current task finishes

### Real-World Scenario

```
User: Download stock data for the past 1 year
Agent: Starting download... (estimated 5 minutes)
[After 1 minute]
User: (Realizes only need past 1 month, but cannot interrupt)
[Must wait 5 minutes]
User: Stop, I only need the past 1 month
Agent: OK, downloading now... (another 5 minutes wasted)
```

---

## ✨ Solution

Add a session interrupt mechanism that allows users to interrupt agent execution with simple commands:

### Supported Interrupt Commands

- `stop`
- `停下来` (Stop - Chinese, recommended)
- `停下` (Stop - Chinese)
- `停止` (Stop - Chinese)
- `别做了` (Don't do it - Chinese)
- `别继续` (Don't continue - Chinese)
- `取消` (Cancel - Chinese)
- `中断` (Interrupt - Chinese)

### User Experience

```
User: Download stock data for the past 1 year
Agent: 🔄 Connecting to Tushare...
Agent: 📊 Downloaded 1000 stocks...
[Executing...]
User: 停下来 (Stop)
Agent: 🫡 Stopped!

Brother Chao, what needs adjustment?
User: Only need the past 1 month
Agent: OK, downloading data for the past 1 month...
```

---

## 🔧 Technical Implementation

### Modified Files

- `src/copaw/agents/react_agent.py` (approximately 80 lines added)

### Core Changes

```python
async def reply(self, msg: Msg | list[Msg] | None = None, ...) -> Msg:
    # ... existing code ...
    
    # Check for interrupt keywords (session interrupt)
    if query and self._is_interrupt_keyword(query):
        logger.info(f"Received interrupt command: {query}")
        return await self._handle_interrupt()
    
    # Normal message processing
    return await super().reply(msg=msg, structured_model=structured_model)

def _is_interrupt_keyword(self, query: str) -> bool:
    """Check if the query is an interrupt keyword"""
    interrupt_keywords = [
        "stop", "停下来", "停下", "停止",
        "别做了", "别继续", "取消", "中断"
    ]
    # ... intelligent matching logic ...

async def _handle_interrupt(self) -> Msg:
    """Handle interrupt command"""
    # 1. Create response message
    # 2. Cancel executing task
    # 3. Clean up resources
    # 4. Return friendly prompt
```

### Design Principles

1. **Non-intrusive**: Detect at the beginning of `reply()`, doesn't affect existing logic
2. **Intelligent Matching**: Supports exact and short-sentence matching to avoid false triggers
3. **Graceful Interruption**: Cancels tasks and cleans up resources
4. **Friendly Response**: Uses emoji and friendly language to maintain conversation flow

---

## 🧪 Testing

### Unit Tests

Created 16 test cases covering all interrupt keywords and edge cases:

```bash
python3 test_interrupt.py
```

**Test Results**:
```
✅ 'stop' -> True
✅ '停下来' -> True
✅ '停下' -> True
✅ '停止' -> True
✅ '别做了' -> True
✅ '别继续' -> True
✅ '取消' -> True
✅ '中断' -> True
✅ '停下来停下来' -> True
✅ '先停下来' -> True
✅ '帮我停下来' -> True
✅ '继续工作' -> False (avoid false trigger)
✅ '帮我写个文件' -> False
✅ '搜索新闻' -> False
✅ '' -> False
✅ 'None' -> False

Total: 16 passed, 0 failed
```

### Integration Testing

Verified in actual usage:
- ✅ Interrupt during file download
- ✅ Interrupt during web browsing
- ✅ Interrupt during data analysis
- ✅ Interrupt in multi-turn conversation

---

## 📊 Impact Assessment

### Positive Impacts

1. **Improved UX**: Users can interrupt anytime, more control
2. **Resource Savings**: Prevents wrong tasks from continuing
3. **Efficiency**: Adjust direction immediately, reduce waiting
4. **Flexibility**: Supports more natural conversation interaction

### Potential Risks

1. **False Triggers**: Avoided through intelligent matching (long sentences don't match)
2. **Resource Cleanup**: Implemented graceful interruption and resource release
3. **Backward Compatibility**: Fully compatible with existing features, no breaking changes

---

## 📚 Documentation

### User Documentation

Created detailed usage guide: `docs/interrupt_feature.md`

Includes:
- List of supported interrupt commands
- Usage examples
- Notes and considerations
- Technical implementation details

### Code Comments

All new code has detailed Chinese comments and docstrings.

---

## 🎨 User Experience Comparison

### Before
```
User: Stop
Agent: [Continues executing, no response]
```

### After
```
User: Stop
Agent: 🫡 Stopped!

Brother Chao, what needs adjustment?
```

---

## 📈 Future Optimization Suggestions

1. **Custom Keywords**: Allow users to configure their own interrupt commands
2. **Interrupt Confirmation**: Ask for confirmation for important tasks
3. **Resume from Breakpoint**: Support continuing from breakpoint after interrupt
4. **Interrupt History**: Record interrupt count and reasons for optimization

---

## 🙏 Summary

This feature addresses a pain point from actual usage. The implementation is simple but significantly improves user experience. Small code changes (~80 lines), thorough testing (16 test cases), complete documentation, recommended for merge.

**Core Value**: Let users control the conversation rhythm, not be led by the Agent.

---

## ✅ Checklist

- [x] Code implementation complete
- [x] Unit tests passed
- [x] Integration tests verified
- [x] Documentation complete
- [x] Code comments complete
- [x] Backward compatibility verified
- [x] Git commit follows conventions

---

**Related Issue**: (Link related issues if any)

**Breaking Change**: No

**Test Environment**: macOS + Python 3.13

---

**Contributor**: Xiao Chao (AI Butler) 🦞
**Date**: 2026-03-09
