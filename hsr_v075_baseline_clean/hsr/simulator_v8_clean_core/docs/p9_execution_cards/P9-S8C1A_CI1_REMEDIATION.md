# P9-S8C1A CI-1 验收整改治理补充

- 状态：`ready_for_execution(remediation)`
- 性质：验收 `return_for_fix` 的最小卡面治理补充，不是重规划。
- 适用对象：现有 PR #1 / `exec/p9-s8c1a-weighted-selection-ir`。
- 原执行卡：`P9-S8C1A_WEIGHTED_SELECTION_IR_CONTRACT.md`。
- 固定 PR base：`f7ca8b02d670a574e09066c874ede61eebf8bc27`。

## 唯一授权增量

原卡的生产范围、生产允许写集合、非目标和 deferred 全部保持不变。

本整改只额外授权现有验证基础设施路径：

```text
.github/workflows/p9-s8c1a-pr1-fast.yml
```

该授权仅用于让 PR #1 在 GitHub Actions 中执行原卡已经规定的三条 fast；不得借 CI 整改修改业务代码、验证语义、生产范围、S8C1B/S8C1C deferred、总计划、checklist 或其他执行卡，也不得新增第二个 workflow。

## CI 契约

workflow 必须 checkout PR #1 的当前 head，并且只执行原卡既有三条 fast：

1. `compileall`：原命令不变；
2. `validate_p9_s8c1a_weighted_selection_ir`：原命令不变；
3. `git diff --check`：检查范围必须显式为固定 base 到当前 PR head 的已提交差异。

第三条不得使用裸：

```bash
git diff --check
```

因为 Actions 的干净 checkout 会使该命令只检查空工作树，不能证明 PR 已提交 diff 无 whitespace error。

整改后的等价要求为：

```bash
git diff --check f7ca8b02d670a574e09066c874ede61eebf8bc27 HEAD
```

其中 `HEAD` 必须是 workflow 已 checkout 的 `github.event.pull_request.head.sha`。允许用等价的 shell 变量写法，但比较端点必须仍是上述固定 base 与当前 PR head；不得改成 merge commit、默认分支浮动 ref、空工作树或其他范围。

## 完成条件

- 仅修改 `.github/workflows/p9-s8c1a-pr1-fast.yml` 完成本次 remediation；
- CI checkout 的是 PR #1 当前 head；
- 三条 fast 均通过；
- `git diff --check` 实际比较 `f7ca8b02d670a574e09066c874ede61eebf8bc27` 与当前 head，而非检查空工作树；
- 不产生业务 diff，不扩大原卡写集合中的生产文件，不改变任何 deferred；
- 完成后回传 `ready_for_review`，等待独立验收复核。

## 停止条件

若修复需要第四条业务验证、第二个 workflow、业务代码修改、base 变化、生产范围扩大或 deferred 变化，停止并回传 `needs_replan`；不得自行扩展整改。
