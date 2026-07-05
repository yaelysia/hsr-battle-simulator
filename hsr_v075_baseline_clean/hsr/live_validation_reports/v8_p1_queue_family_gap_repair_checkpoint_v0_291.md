# v8 P1 queue family gap repair checkpoint v0.291

日期：2026-07-05

## 结论

本检查点修正 P1-9 的一个验收口径假阳性：P1-5 queue family gap 扫描不能只按 `QueueWindowIR.window_family == counter/follow_up` 判断来源是否存在。

当前 Canonical IR 中存在 counter 语义来源，但它们结构上仍落在通用 `insert_ability` queue window，并通过 `window_policy.text_hints` / `source_basis.text_hints` 暴露 counter 语义：

```text
insert_ability:counter:executable = 10
insert_ability:counter:blocked = 5
```

因此 `p1_5.counter` 不能再标为 `source_absent_not_required`。在没有 admitted `window_family=counter` 正例或专门 counter 语义正例前，它必须标为 `admission_gap`，并阻塞 `phase1_minimum_battle_slice`。

## 修复内容

- `validate_p1_5_queue_window_system` 的 family gap row 现在同时统计：
  - 结构 family：`QueueWindowIR.window_family`
  - 语义 family：`window_policy.text_hints` / `source_basis.text_hints`
  - admitted family executable count
  - semantic executable source count
- `executable_count` 仍只表示该 family 自身已 admitted 为可执行 family，避免把 `insert_ability` 的可执行误报为 counter family 完成。
- `validate_p1_9_phase1_aggregate` 现在读取 P1-5 的 `admission_gap` / `validation_gap` / `lowering_gap` 分类，并把这些状态纳入 `phase1_minimum_battle_slice_blocker`。
- `p1_9_done_eligible` 现在跟随 `phase1_minimum_battle_slice`，避免 minimum false 时仍显示 done eligible。

## 当前 P1-9 输出

```text
ok=True
p1_9_done_eligible=False
phase1_repair_substrate_accepted=True
phase1_minimum_battle_slice=False
phase1_minimum_battle_slice_blocked_by=["p1_5.counter"]
```

P1-9 source-gap matrix 中：

- `p1_5.follow_up`: `source_absent_not_required`
- `p1_5.counter`: `admission_gap`
- `p1_5.assistant`: `boundary_only`

## 验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_5_queue_window_system --output-dir /tmp/hsr_v8_p1_5_queue_family_gap_repair
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_queue_family_gap_repair_done_field
```

## 尚未完成

本检查点只修正验收口径和 gap 分类，不宣称 counter 语义已经 executable。要解除 `p1_5.counter` blocker，后续必须补上真实来源驱动的 counter 语义正例或 admitted counter queue family/runtime 纵切。
