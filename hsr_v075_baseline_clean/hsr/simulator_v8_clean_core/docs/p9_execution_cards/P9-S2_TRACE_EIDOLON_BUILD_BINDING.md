# P9-S2 行迹、星魂与最终构筑机制绑定执行卡

## 执行配置

- 对应问题：P9-I03；机制包 M02。
- 硬前置：P9-S1 已验收并形成检查点。
- 推荐：5.6 Sol / `max` / Goal 模式。
- 理由：覆盖 79 条角色的最终构筑选择、静态贡献和动态引用，必须防止重复生效和部分执行。

## 当前事实与阶段结果

当前诊断包括星魂槽无运行时来源、行迹节点无结构化来源、额外效果未准入、行迹 ability 未
消费和星魂 graph 歧义。它们在同一角色上重叠，根因是缺少统一内容绑定链，不是六套机制。

完成后，`CharacterBuildAssembler` 是最终技能等级、行迹和星魂选择的唯一解析者。静态贡献
进入通用账本，动态效果只保存 S1 graph 引用和准入诊断。下游语义尚未闭合时允许面板装配
成功但 battle admission blocked；不得静默忽略或部分执行。

## 详细目标

1. 将默认行迹、显式解锁节点、技能等级和星魂等级规范化为递归不可变构筑输入。
2. 按真实角色归属、逻辑 trace、等级替换和默认节点规则解析一次，拒绝重复与冲突。
3. 将静态属性、资源属性、技能等级变化和动态 ability 引用分别投影，不复制 effect payload。
4. 星魂每个槽位和额外效果唯一关联 S1 来源图；缺失/多义项形成结构化诊断。
5. assembly 与 battle admission 分离；blocked 结果不携带可执行动态引用或半成品 UnitState。
6. 移除 runtime 对 rank/skill-point build selector 的重复判断和旧 flags 双轨。

## 本阶段不做

- 不执行动态 ability、状态或事件；S4-S17 负责。
- 不模拟行迹/星魂获取、升级路线或材料。
- 不用文本说明补静态数值或 ability 关联。
- 不因下游机制未完成而丢弃已经可靠绑定的内容来源。

## 架构与负例

- 重复节点、默认节点显式重选、同逻辑多等级、跨角色节点、星魂越界全部拒绝。
- 静态与动态混合来源必须拆分且共享同一来源记录，不能二选一或重复执行。
- 正式构筑中旧 enabled/disabled flags、手填面板或手填机制引用必须拒绝。
- 装配结果 fingerprint 覆盖输入、贡献、机制引用和未准入诊断；篡改可检测。

## 目标与证据

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 最终选择唯一 | 默认、显式和等级替换无重复 | selection matrix |
| 内容绑定完整 | 当前行迹/星魂每项有静态、动态图或明确 gap | content binding ledger |
| 静动态分离 | 面板可重算，动态引用不携带第二套 payload | assembly samples |
| 准入诚实 | 未闭合动态效果阻止正式出生 | admission negatives |
| runtime 不重算 | 旧 flags/rank 检查不再改变已装配结果 | atomic migration check |

## 结构化通过谓词

```text
final_build_selection_recursively_immutable=true
default_and_explicit_trace_not_double_applied=true
trace_level_conflicts_rejected=true
cross_character_content_rejected=true
static_and_dynamic_sources_separated=true
trace_and_eidolon_bindings_fully_classified=true
unadmitted_dynamic_effect_blocks_battle=true
blocked_result_has_no_executable_channels=true
runtime_build_selector_fallback_absent=true
assembly_fingerprint_covers_diagnostics=true
```

## Gap 与停止条件

- S1 graph 存在但 S2 未绑定：本阶段 `lowering/admission_gap`，必须修。
- raw 只有文本或没有结构化效果：`source_gap_blocked`，不能合成 payload。
- 下游 graph 已绑定但 task family 未执行：记录责任阶段，不在 S2 提前实现。
- 需要保留新旧构筑双来源：停止并询问兼容裁决。

## 拟改范围

- `tbgd/character_cards.py`、`rules/ir.py`、`rules/rulebook.py`。
- `builds/models.py`、`builds/character_assembler.py`。
- 原子迁移 `scenarios/build_state.py` 中正式构筑消费；kernel fixture 保持显式隔离。
- 主验证 `tools/validate_p9_s2_trace_eidolon_build_binding.py` 和报告。

## 验证与资源

- 一次读取角色成长/行迹/星魂和 S1 来源图；不执行战斗 task。
- 主入口输出 content binding ledger、静态重算、动态诊断和负例；不写全角色 IR。
- direct 最多 2 项：只有实际触达正式 scenario admission 或通用账本时运行对应小切片。
- 预算：8 分钟、1 GiB、5 MiB、900 行；P8/P4 完整验证不跑。

## 唯一执行清单

- [ ] 最终技能、行迹和星魂选择规范化且不可变。
- [ ] 当前全部内容来源绑定为静态贡献、动态引用或诚实 gap。
- [ ] 静态/动态、assembly/admission 边界清晰且无部分执行。
- [ ] 重复、冲突、跨角色、旧 flags 和篡改负例 fail-closed。
- [ ] runtime 不再重复解释构筑选择。
- [ ] 主验证、必要 direct 和资源审计通过并提交 `ready_for_review`。
