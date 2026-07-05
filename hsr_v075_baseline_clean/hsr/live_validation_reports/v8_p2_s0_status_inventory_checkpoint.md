# v8 P2-S0 状态全量盘点和覆盖矩阵检查点

日期：2026-07-05

## 本步完成

- 新增 `simulator_v8_clean_core.tools.p2_status_coverage`，作为 P2 状态覆盖矩阵共享 builder。
- 新增 `validate_p2_s0_status_inventory`，默认只输出 summary、family matrix 和少量样例，不写完整 Canonical IR 或 transition dump。
- 矩阵覆盖状态定义、AddModifier、RemoveModifier、RemoveSelfModifier、DispelStatus、生命周期字段、叠层刷新字段、chance/resist/immunity 字段、状态 callback event family、数值绑定和状态伤害来源。
- raw TBGD 只在工具层用于来源盘点；runtime 仍只读 Canonical IR / RuleBook。

## 关键计数

```text
status_definition_total=3711
raw_status_effect_nodes=37722
ir_status_effect_nodes=69793
raw_callback_count=29078
ir_status_callback_count=29078
status_event_family_count=200
unclassified_count=0
```

Family classification 当前 10 项均有可执行来源，但矩阵仍保留 blocked 子计数：

```text
source_item_counts.raw_total=85527
source_item_counts.ir_total=270515
source_item_counts.executable_total=246885
source_item_counts.blocked_total=12305
```

这表示 S0 盘点完成，不表示 P2 全状态系统完成；blocked 子项会在 S1-S12 继续分层审计、实现或证明 boundary/source absent。

## 验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p2_s0_status_inventory --output-dir /tmp/hsr_v8_p2_s0_status_inventory
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

关键输出：

```text
v8 p2_s0_status_inventory validation ok=True
```

## 剩余范围

- S1 需要继续审计状态 IR / RuleBook 来源完整性。
- S2-S10 需要把已有 runtime 语义逐项绑定到 P2 矩阵的正例、负例、replay 和 source audit。
- S11/S12 才能判断 P2 全状态来源是否清零未覆盖与 gap。
