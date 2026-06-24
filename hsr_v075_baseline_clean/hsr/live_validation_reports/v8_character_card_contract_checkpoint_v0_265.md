# v8 v0_265 Character Data Card Contract Checkpoint

## Summary

本阶段把角色接入入口收束为 `CharacterDataCardIR`。技能文本、参数、Ability 图、状态监听、额外行动、行迹和星魂接口都在角色卡构建层解释成结构化槽位；runtime 继续只消费 Canonical IR，不读取 TextMap、TBGD raw schema，也不按角色名写逻辑。

希儿作为用户指定示例卡接入：普攻、战技、终结技可从角色卡公式槽位产生伤害；再现链路从真实“造成击杀”事件进入状态监听、队列、额外回合并执行非终结技动作。

## Implemented

- 扩展 `CharacterDataCardIR` 合同：卡片版本、动作集、机制槽、行迹节点、星魂槽、合同红线。
- 新增角色卡机制槽：
  - `formula_slot`
  - `bounce_policy`
  - `status_callback`
  - `queue_intent`
  - `extra_action_policy`
  - `skill_continuation`
  - `trace_static_stat_bonus`
  - `trace_ability_hook`
- 新增 `CharacterTraceNodeIR` 和 `CharacterEidolonSlotIR`。
- RuleBook 增加角色机制槽、行迹节点、星魂槽查询。
- lowering 将 ability/status/queue/extra-action/continuation 来源反挂回角色卡。
- 新增 `validate_v0_265`。

## Seele Example

- 希儿卡：`character_data_card:avatar:1102`
- 普攻、战技、终结技均通过角色卡公式槽位执行。
- 再现链路：
  - 希儿自己的伤害造成击杀。
  - 触发 `unit.defeated`。
  - 命中希儿状态监听。
  - 写入动态值。
  - after skill 监听入队额外回合。
  - scheduler drain 后执行 route 选择的非终结技动作。
- 额外回合未触发普通 turn begin/end，未消耗普通 buff 持续时间。
- 非致死伤害不会触发再现。

## Still Out Of Scope

- 完整角色面板组装。
- 行迹静态属性实际写入面板。
- 星魂机制执行。
- 遗器、光锥、队伍环境组合。
- 敌方 AI、波次系统。

这些没有在 runtime 里硬补。相关槽位保留 source trace 和明确 blocker，后续由角色面板/装备/星魂模块接入。

## Validation

已通过：

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_265 --output-dir /tmp/hsr_v8_v0_265
```

关键结果：

- `ok=true`
- `character_data_card_count=92`
- `character_mechanism_slot_count=12986`
- `character_trace_node_count=5246`
- `character_eidolon_slot_count=552`
- 希儿卡 JSON roundtrip 通过。
- runtime 边界检查通过。
- 希儿普攻、战技、终结技执行通过。
- 希儿再现击杀额外回合链路通过。
- source audit、settlement traceability、snapshot replay 通过。
