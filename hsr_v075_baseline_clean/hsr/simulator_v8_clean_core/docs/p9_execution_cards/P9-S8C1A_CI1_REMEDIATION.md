# P9-S8C1A CI-1 验收整改治理补充

- 状态：`historical_evidence`
- 性质：原验收 `return_for_fix` 期间形成的最小治理补充；不再是执行入口。
- 适用对象：PR #1 / `exec/p9-s8c1a-weighted-selection-ir` 的 CI-1/CI-2 历史整改。
- 原执行卡：`P9-S8C1A_WEIGHTED_SELECTION_IR_CONTRACT.md`。
- 固定 PR base：`f7ca8b02d670a574e09066c874ede61eebf8bc27`。

用户后续已明确治理规则：仅为既有 fast 提供的 PR-scoped CI、环境/验证自救属于执行层可逆修复，
不要求规划补卡；执行报告记录授权和实际证据即可。因此本文件只保留当次 Finding 与 CI-2 修复的
可追溯事实，不得据此创建新的 remediation 或扩大后续卡范围。

## 当时的授权增量

原卡的生产范围、生产允许写集合、非目标和 deferred 全部保持不变。

当时仅额外使用现有验证基础设施路径：

```text
.github/workflows/p9-s8c1a-pr1-fast.yml
```

该 workflow 仅用于让 PR #1 在 GitHub Actions 中执行原卡已经规定的三条 fast；未借 CI 整改修改
业务代码、验证语义、生产范围、S8C1B/S8C1C deferred、总计划、checklist 或后续业务卡，也未新增
第二个 workflow。

## CI-2 闭合事实

workflow checkout PR #1 的当前 head，并只执行原卡既有三条 fast：

1. `compileall`：原命令不变；
2. `validate_p9_s8c1a_weighted_selection_ir`：原命令不变；
3. `git diff --check`：显式检查固定 base 到触发 PR head 的已提交差异。

CI-2 不再使用裸：

```bash
git diff --check
```

而使用固定 base 到触发 head 的等价检查，避免干净 Actions checkout 只检查空工作树产生假阳性。
最终独立复审确认该 Finding 已闭合。

## 历史完成条件

- PR-scoped workflow 只承载既有三条 fast；
- CI checkout PR #1 触发时的真实 head；
- 三条 fast 均通过；
- `git diff --check` 比较固定 base 与触发 head，而非空工作树；
- 无业务 diff、无 deferred 变化、无第二个 workflow；
- P9-S8C1A 最终由独立验收判定 `accepted`。

本文件现在仅为 `historical_evidence`，不得作为 `ready_for_execution` 卡使用。
