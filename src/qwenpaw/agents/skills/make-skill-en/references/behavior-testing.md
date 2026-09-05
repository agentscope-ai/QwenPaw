# Behavior testing

Run only the mode approved in the plan:

- `off`: perform static, security, and package validation; do not execute the draft.
- `smoke`: run one minimal end-to-end attempt with the draft Skill.
- `eval`: run one representative case once without the Skill and once with it. Add cases only when the approved plan explicitly requires them.

For eval, give both executors the same natural task and input artifacts. The only experimental difference is that the with-Skill executor receives the draft path; the baseline must not access that path. Use isolated contexts and output directories without hiding legitimate task files under a broader forbidden directory.

Run the two arms in parallel only when tool scratch files and other side effects are isolated per executor; otherwise run them sequentially against the same frozen inputs. If infrastructure interference invalidates the comparison, discard and report the pair. After fixing isolation, rerun both arms from empty output directories rather than rerunning only the affected arm.

Treat the draft as immutable during testing. Tell each executor to attempt the task once, return evidence, and never edit the Skill or retry after a failure. Do not reveal expected answers, suspected failures, or scoring conclusions.

Judge only the observable target approved in the plan. Use direct assertions for objective artifacts and a short reviewable rubric for subjective work. Do not substitute fixed headings, wording, or body length for behavior.

Behavior testing is independent of whether the workflow uses Batch. Do not add a test merely because `batch: true`, and do not disable a useful test merely because `batch: false`. Keep fixtures, traces, stdout, and reports under `.qwenpaw/make-skill/runs/<draft-id>/`, outside the final package. Put eval assets in `evals/` only when they have durable maintenance value and appear in the approved file tree.

If the target fails or the with-Skill result regresses, retain the draft and report the evidence. Correct and revalidate the Skill when the failure gives a clear fix; otherwise ask the user rather than inventing a workaround. If both eval attempts pass without a clear observed gain, publication may continue while reporting that the single comparison did not establish improvement.
