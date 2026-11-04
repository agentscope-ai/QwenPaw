# Opt-in shell memory protection

Scope: `execute_shell_command`, including commands run through the existing
sandbox backends and coding mode. Other tools and the QwenPaw process itself
are outside this change.

## Configuration

Set `QWENPAW_SHELL_MEMORY_LIMIT_MB` in the QwenPaw server environment, or edit
it in Console → Settings → Environment Variables → Live settings:

- Unset or `0`: disabled; no watchdog or process-tree sampling.
- Positive integer, e.g. `512`: per-command process-tree RSS limit in MiB.
- `auto`: half of host available memory at invocation, capped at 4096 MiB.

The existing environment registry owns metadata and validation; Console
uses its existing catalog, persistence, reset and hot-update APIs. The same
parser validates Console writes and shell invocations. A saved value takes
effect on the next shell call; active calls retain their initial budget.
Invalid Console writes are rejected without changing the effective value.
An invalid startup value rejects the invocation before starting a command. Explicit
limits are also capped at half of available memory at invocation to preserve
headroom. Concurrent invocations have separate limits; this is not an aggregate
application budget. Host availability may overestimate a container's allowance;
set an explicit limit appropriate to the deployment in containers.

## Mechanism and limits

A watchdog thread samples the shell and observed descendants every 250 ms. It
terminates the observed tree when its summed RSS exceeds the limit. Existing
execution backends still wait for and reap the command. RSS can count shared
pages more than once. Observed descendants are cleaned up when the call ends;
background jobs should use a dedicated process manager.

While enabled, sandbox pipe readers retain at most 1 MiB per stream. Combined
output over `QWENPAW_SHELL_MAX_OUTPUT_BYTES` (default 10 MiB) terminates the
command; direct shell output files are checked on the same sampling interval.
The tool reports an error with the protection reason while preserving the
backend's exit code and captured output. A watchdog kill is not a native OOM.

This is best-effort monitoring on Linux, macOS and Windows, not kernel memory
containment. Allocation bursts, descendants that escape between samples,
insufficient process permissions, concurrent calls and unrelated memory users
can still exhaust memory. The watchdog is independent of the asyncio event
loop but shares the interpreter and GIL. Protection does not guarantee the
QwenPaw process survives system OOM.

## Why this scope

No global allocator, daemon, separate settings UI, Python-tool wrapper, cgroup manager
or Windows Job memory policy is introduced. Those require distinct accounting,
permissions and lifecycle semantics. Keeping protection opt-in at the existing
shell boundary provides a reviewable first step without changing sandbox
permissions or normal execution defaults.

## Checklist

- [x] Start from current upstream/main in a separate worktree and branch.
- [x] Agree on shell-only, opt-in scope and monitoring semantics.
- [x] Implement memory monitoring and bounded output for shell backends.
- [x] Verify actual over-limit termination and existing shell behavior.
- [x] Add portable real-process regressions for the existing three-OS matrix.
- [x] Measure enabled/disabled overhead without exhausting host memory.
- [x] Register with Console environment management and verify hot updates.
- [x] Run relevant checks and prepare the repository PR template.

## Local performance observation

On the development macOS machine, Python 3.12 / psutil 7.2.2, after warm-up:

| Workload | Disabled | Enabled |
| --- | --- | --- |
| `true`, median of 30 runs | 7.1 ms wall | 11.0 ms wall |
| 3-second sleeper, parent CPU time | 5.2 ms | 184 ms |
| 10 sleeping descendants, parent CPU time | 7.2 ms | 164 ms |
| 50 sleeping descendants, parent CPU time | 5.8 ms | 230 ms |

Sleeper results average two runs; enabled monitoring used about 5–7% of one
CPU core on this machine. This includes process-tree enumeration and is not
representative of Linux, Windows or all macOS hosts. Each concurrent guarded
invocation has its own watchdog. The disabled environment check averaged
0.39 microseconds across 100,000 calls. Measurements are illustrative, not a
performance guarantee. Sandbox output-heavy workloads have additional copying
and accounting costs and were not included in this timing comparison.

## Prior art

[Codex execution](https://github.com/openai/codex/blob/main/codex-rs/core/src/exec.rs)
caps retained shell output to avoid OOM from runaway stdout/stderr and bounds
I/O draining. [Claude Code sandbox documentation](https://code.claude.com/docs/en/sandboxing)
describes shell filesystem/network isolation independently of permissions.
Neither of these references establishes a cross-platform aggregate memory
budget for the whole agent. This change follows the bounded-output and shell
boundary approach without claiming their sandboxing mechanisms enforce RSS.

## Validation

The portable shell regression runs real processes on the executing OS and is
included in the existing Windows/macOS/Linux nightly unit matrix. Two children
each stay below the memory ceiling but jointly exceed it. The test writes one
byte per page so Linux demand-zero allocation cannot produce a false pass.
It also checks output termination, preserved stderr, observed process cleanup,
watchdog cleanup and the disabled fast path. The environment API regression
covers catalog visibility, persisted overrides, invalid values and live reset.

Local validation used macOS: 482 backend tests passed, one platform-specific
skip; 12 existing Console environment tests passed. A native Seatbelt smoke
check and an API-to-real-shell hot-update check passed. Windows and Linux
native execution is left to CI; a local macOS pass does not establish it.
