# 行为测试

只运行计划中批准的模式：

- `off`：运行静态、安全和 package 校验，不执行 draft。
- `smoke`：使用 draft Skill 做一次最小端到端尝试。
- `eval`：默认选择一个代表性 case，无 Skill 与有 Skill 各执行一次。只有批准计划明确要求时才增加 case。

Eval 的两个 executor 使用相同的自然任务和输入素材。唯一实验差异是 with-Skill executor 获得 draft 路径；baseline 不得访问该路径。上下文和输出目录相互隔离，但不要因为目录范围过大而屏蔽合法任务文件。

只有工具的临时文件和其他副作用也能按 executor 隔离时才并行运行两边；否则在同一组冻结输入上顺序运行。基础设施干扰使比较失效时，丢弃整对结果并如实报告；修复隔离后如需重跑，应从空输出目录重跑两边，而不是只重跑受影响的一边。

测试期间 draft 不可变。明确要求每个 executor 只尝试一次、返回证据，不修改 Skill，也不在失败后重试。不要向执行者泄露预期答案、怀疑点或评分结论。

只验收计划批准的可观察目标：客观产物使用直接 assertion，主观产物使用简短、可审阅 rubric。不要用固定标题、措辞或正文长度代替行为结果。

行为测试与 workflow 是否使用 Batch 相互独立。不要仅因 `batch: true` 增加测试，也不要仅因 `batch: false` 关闭有价值的测试。fixture、trace、stdout 和 report 放在 `.qwenpaw/make-skill/runs/<draft-id>/`，不进入最终 package。只有长期维护确有价值且已出现在批准文件树中的 eval 资产才放入 `evals/`。

未达到目标或相对 baseline 回归时，保留 draft 并报告证据。失败给出明确修正方向时，修正 Skill 后重新校验；否则询问用户，不发明 workaround。两次 eval 都通过但未观察到明显提升时，可以发布，但应说明本次单例比较没有证明增益。
