# -*- coding: utf-8 -*-
"""Code Mode guidance, separate from the runtime-generated tool catalog."""

CODING_GUIDELINES = f"""## Code Mode
Use run_code for all tool actions. Batch independent calls, chain dependent
calls, and filter large results inside Python before returning evidence.
Use asyncio.gather(..., return_exceptions=True) for independent operations
whose successful results should survive a failure; inspect exceptions and
retry only what failed. Await dependent operations in order. Do not parallelize
operations that depend on each other or mutate the same files/state.
The run_code description lists enabled tools and their usage rules. Call
await tools.<name>(parameter=value); inspect describe_tool for exact arguments.
Use the available web search tool for current facts before shell fallbacks.
Read before editing, keep changes targeted, and run the relevant project
checks.
Tool media stays inside Python until explicitly shown with image(block),
audio(block), or video(block). text/print cannot show media to the model.
File paths and shell cwd default to the active project.
"""

CODE_DESCRIPTION = f"""Run Python source in a fresh CPython process.
Input: {{"code": "Python source"}}, without Markdown fences inside the string.
Top-level await and the Python standard library are supported. No variables
persist across calls. Use enabled tools for host files, processes and network;
permissions and execution hooks apply. OS sandboxing follows the global
security.sandbox_enabled setting and is disabled by default.

Calling and discovering tools:
- await tools.<name>(parameter=value): keyword arguments only. Names and real
  input schemas appear below. Never call a tool as a bare global function.
- ALL_TOOLS lists available names, Python names and descriptions.
- await search_tools(query="web") searches names/descriptions. It is a literal
  search, not semantic intent routing. An empty "weather" match does not imply
  web search is unavailable; inspect ALL_TOOLS or search for "web".
- await describe_tool(name) returns the full schema and native result contract.
- Each tool resolves to {{content: [native blocks], metadata: object or null,
  state: string}}. Text blocks contain {{type: "text", text: str}}; text is not
  automatically parsed as JSON. Use json.loads only when the tool returns JSON.
- Failed or denied calls raise an exception. Permissions and native execution
  middleware apply to every nested call. Skills, tasks and controls use tools.*
  too. Use only enabled names in the catalog, and follow their usage rules.

Compose operations:
- Batch independent calls with import asyncio and await asyncio.gather(...).
- For partial success use return_exceptions=True, inspect each result with
  isinstance(result, Exception), and emit successful evidence and errors.
- For dependencies await the first result, derive the next arguments, then call
  the next tool. Filter, sort, deduplicate or aggregate before emitting output.
- text(value), print(...), and the final expression output text/JSON only.
  They do not show images, play audio, or send video to the model.
- image(block), audio(block), video(block) output native data blocks with
  matching image/*, audio/*, video/* source.media_type. Text and media retain
  their output order. Intermediate tool results stay inside the script.
- Calling view_image/view_audio/view_video alone does not show media to the
  model. Explicitly output the returned data blocks with the matching helper.
  Read local/remote media through tools first; do not fabricate file URLs.
- Audio auto-transcription returns text: output block["text"] with text().
  Native audio/video perception still requires a model supporting that input.

Example: inspect two available contracts concurrently and emit only their
names:
import asyncio
requests = [describe_tool(t["name"]) for t in ALL_TOOLS[:2]]
results = await asyncio.gather(*requests, return_exceptions=True)
for result in results:
    if isinstance(result, Exception):
        text({{"error": str(result)}})
    else:
        text(result["name"])

Example when view_image is enabled:
r = await tools.view_image(image_path="/path/to/image.png")
for block in r["content"]:
    if block["type"] == "data":
        image(block)
    elif block["type"] == "text":
        text(block["text"])
Use the same loop with tools.view_audio(audio_path=...) and audio(block),
or tools.view_video(video_path=...) and video(block). Preserve text hints too.

The worker has time, memory and output limits. Await every task. Unfinished
host calls are cancelled when the script exits; effects completed before an
error are not rolled back. A failed script keeps selected partial output
and a traceback.
"""
