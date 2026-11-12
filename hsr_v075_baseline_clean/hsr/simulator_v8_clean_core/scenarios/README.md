# 场景输入

正式入口为 `ScenarioLoader → ScenarioSpec → ScenarioStateBuilder`；CLI、UI 与外部推演器共用它。
完整场景与固定操作见 [`../examples/cli/`](../examples/cli/)，命令见[CLI 操作](../CLI_MVP.md)。
场景声明内容、成品构筑、初始条件和操作，不声明新公式、状态行为、敌方 AI 或固定伤害答案。

## 根字段

| 字段 | 含义 |
| --- | --- |
| `scenario_id`、`version` | 场景身份与格式版本；现有正式示例使用 `v0_200` |
| `units` | 至少一个单位，通常声明正式角色，敌人由关卡波次装配 |
| `stage_ref`、`wave_index` | 来源关卡与起始波次 |
| `route` | 可选的旧场景内操作；CLI 固定操作通常放独立 `commands` 文件 |
| `battle_setup` | 资源、时间线、RNG、场景范围及已激活秘技等初始条件 |

## 角色与成品构筑

正式角色的 `build_mode` 为 `assembled_character_build`，提供 `character_build` 和 `initial_condition`。
`entity_ref` 例如 `avatar:1008`，卡片引用例如 `character_data_card:avatar:1008`。
等级、晋阶、星魂、已解锁行迹和装备来自构筑；技能等级由装配器计算。
不能同时提供手写 `panel`，也不能用构筑外的字段覆盖技能等级或伤害倍率。

装备键可写来源短 ID：例如 `light_cone.definition_key: "23002"`、遗器
`template_key: "61021"`、`slot_key: "HEAD"`。字段决定定义种类；也接受
`"light_cone::23002"` 或完整对象。`stable_id`、实例 `instance_fingerprint` 和装备
`build_fingerprint` 均可省略，由解析器生成；显式提供的错误值仍拒绝。
完整规范化输出仍包含这些身份。空装备可只给 `build_id` 与 `character_card_id`。

`initial_condition` 声明入场 HP、能量与允许的特殊资源；不是角色成长面板。
`kernel_fixture` 可为机制检查提供明确的局部面板，但不作为正式角色、敌人或实战对照输入。

## 初始战斗设置

```json
{
  "battle_setup": {
    "world_level": 1,
    "resources": {"skill_points": 3, "max_skill_points": 5},
    "timeline": {"mode": "runtime_initialize"},
    "rng": {"rng_state": "example-seed", "rng_choices": {}},
    "metadata": {"stage_scope": "wave_only"}
  }
}
```

- `stage_scope=wave_only` 只装配所选波次；`full_stage` 纳入关卡环境，其支持范围另按内容验证。
- 正式构筑使用 `runtime_initialize` 时，不能同时指定 `action_values/explicit_overrides`。
- `battle_setup.wave` 也可声明关卡波次；与根字段同时出现时必须一致。
- RNG 初始设置和操作选择进入同一确定性执行链，不由场景直接写结算结果。
- `techniques` 的元素为 `{"actor_id":"单位ID","action_ref":"正式秘技动作ID"}`，等级与参数取构筑。
- `initial_statuses` 只引用可执行的状态效果；`initial_summons` 只引用已准入的召唤定义，
  是否可用由对应领域系统判断，不能笼统认为所有 servant 都未支持。
- `objective` 用作搜索/展示元数据，不改变战斗规则。

## 共享编译范围

反复切换队伍或关卡时，在这些场景的 `battle_setup.metadata` 中配置同一个内容池：

```json
{
  "stage_scope": "wave_only",
  "compile_scope": {
    "avatar_ids": ["1008", "1105"],
    "stage_ids": ["200020050"],
    "light_cone_ids": ["23002", "23013"],
    "relic_template_ids": ["61021", "61022", "61023", "61024", "63025", "63026"],
    "include_stage_environment": false
  }
}
```

编译范围为内容池与当前场景的并集，怪物由这些关卡的实际波次补齐。
装备范围默认从实际构筑提取，与池中的光锥 ID、遗器模板 ID 取并集；遗器自动保留所需套装的
完整槽位/品质成员、词条组与阈值，装备能力保留跨文件引用闭包。
同池内换队、改等级或装备面板复用同一缓存；新增池外装备、角色或关卡会改变范围。
只有确实需要浏览完整装备目录时才设置 `include_equipment: true`，它会覆盖装备范围限制。
池只增加可查询规则，场上单位与合法行动仍由当前场景装配；池越大，冷编译与内存成本越高。
此配置随归档保存，回放能重建同一规则范围；默认仍只编译当前场景。

## 检查与边界

先使用 CLI `query` 验证正式装配和公开可选动作，再按需执行固定命令。
仅 JSON 能解析不等于所选角色、波次和机制已可战斗；当前限制以[交接](../../CODEX_HANDOFF.md)为准。
旧的 P1-8 说明保留在[历史场景文档](../docs/archive/usage/SCENARIOS_PRE_REFRESH_2026-11-12.md)，
不再把历史验证器作为唯一或默认场景入口。
