# Event Stream Resilience Fix for Console Channel

## Problem

Console channel's `consume_one()` silently loses messages when the event stream is interrupted during processing. This occurs when:

- Memory compaction runs during response generation
- Playwright zombie processes cause hangs
- Any async generator interruption

**Symptom:** Agent processes request but user sees no output. Server logs show no error.

## Root Cause

```python
# Old code
async for event in self._process(request):
    # If stream breaks here, everything after is lost
    if status == RunStatus.Completed:
        self._print_parts(parts)  # Never reached
```

The `async for` loop had no exception handling - any interruption caused silent message loss.

## Solution

Added explicit exception handling and user notification:

1. **Catch stream exceptions:** Separately handle `StopAsyncIteration` (normal) vs actual errors
2. **Log partial results:** Report how many events were processed before interruption
3. **Inform user:** Print error message when content may be incomplete
4. **Always execute callbacks:** Ensure `on_reply_sent` fires even after interruption

## Files Changed

- `src/copaw/app/channels/console/channel.py` - Added event stream resilience to `consume_one()`

## Testing

This fix cannot be easily unit tested (requires memory pressure/compaction), but can be verified by:

1. Running with very low memory to trigger compaction
2. Monitoring logs for "stream interrupted after N events" messages
3. Confirming partial responses are now visible to users

## Related Issues

- PR #744 (console filter_tool_messages fix)
- `STREAM_INTERRUPTION_ANALYSIS.md` in CoPaw documentation

## Checklist

- [x] Code follows project style guidelines
- [x] Added appropriate exception handling
- [x] Updated docstring for consume_one()
- [x] Tested manually under memory pressure
