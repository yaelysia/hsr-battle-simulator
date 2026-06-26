# v8 怪物被动槽位 checkpoint v0_281

## 本阶段完成

- 新增通用 `PassiveMechanismSlotIR`，并接入 `CanonicalIR` 与 `RuleBook`。
- `MonsterDataCardIR` 新增 `passive_mechanism_slot_ids`，用于 UI、审计和 scenario 初始化定位。
- 怪物被动来源只承认 `MonsterConfig.AbilityNameList`。
- `MonsterSkill.ModifierList` 保持为技能槽字段，不进入被动槽位。
- 被动 ability name 通过结构化索引唯一定位 `Config/ConfigAbility/Monster/**/*.json`；缺失或歧义 blocked。
- 第一阶段只允许根级 `OnStart + AddModifier` 常驻被动进入候选。
- 如果根级 `OnStart` 混有本阶段未 admission 的 task，即使同一个 ability 里还有 `AddModifier`，也整体 blocked，禁止半截执行。
- 当前真实数据中没有一个 `AbilityNameList` 槽位满足完整可执行 admission 条件，因此本阶段没有 runtime 被动 mutation。
- 后续若出现完整 admission 的开场常驻被动，会复用现有链路：
  `StandaloneAbilityGraphIR -> AbilityTaskIR -> EffectIR(AddModifier) -> StatusSystem.apply_add_modifier`。
- 带事件 trigger 的 modifier 被 blocked，避免事件类被动在未 admission 时进入可触发状态。
- scenario 构建阶段只会把 executable passive slot 转为 startup spec；当前所有真实怪物 passive slot 都保持 blocked。

## 样例结果

纠偏样例输出：

`simulator_v8_clean_core/examples/monster_cards/monster_passive_blocked_display_marker_example_v0_281.json`

当前结构化选择实际选中一个反例：

- 怪物：`银鬃尉官 / Silvermane Lieutenant`
- `MonsterID=100301004`
- 被动来源：`MonsterConfig.AbilityNameList[0]`
- ability：`Monster_Common_BossInfoBar`
- 被动槽位：`passive_mechanism_slot:monster:100301004:ability:0:Monster_Common_BossInfoBar`
- 判定结果：blocked。
- 阻塞原因：根级 `OnStart` 包含 `ShowBossInfoBar`，本阶段未 admission。
- 初始化结果：不挂 `modifier:MCommon_BOSSInfoBar_Active`，不产生 startup trace，不产生 mutation。

该反例按结构化谓词选择，不按固定 MonsterID、ability name 或展示名驱动 runtime。

## 覆盖统计

`validate_v0_281` 当前统计：

- `AbilityNameList` 引用降出的 passive slot：309。
- executable 开场常驻被动：0。
- blocked：309。
- missing ability：20。
- ability graph not executable：232。
- 无可 admission 的 `OnStart/AddModifier`：29。
- 根级 `OnStart` 混有未 admission task：28。
- 因 modifier 带事件 trigger 被 blocked 的 task：42。
- `ShowBossInfoBar` blocked task：9。

## 验证结果

命令：

```bash
cd hsr_v075_baseline_clean/hsr
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_281 --output-dir /tmp/hsr_v8_monster_passive_v0_281 --example-output simulator_v8_clean_core/examples/monster_cards/monster_passive_blocked_display_marker_example_v0_281.json
```

当前已完成：

- `compileall simulator_v8_clean_core` 通过。
- `validate_v0_281` 通过，`ok=true`。
- `BossInfoBar` 信息条不再进入状态列表。

## 未完成

- 事件类被动未执行，只降槽位和 blocked 记录。
- 阶段、召唤、锁血、插队、波次相关被动未执行。
- 带动态值请求的怪物开场被动还没有结构化动态值绑定 admission。
- 角色、光锥、遗器尚未迁移到 `PassiveMechanismSlotIR`，本阶段只建立通用接口并接怪物。
- 敌方自动行动仍未接入 scheduler 固定序列。

## 距离最小敌方行动纵切还缺

- scheduler 读取怪物卡固定序列并生成敌方动作候选。
- 目标仍由 route/推演器枚举，复杂 AI 继续 blocked。
- 敌方行动前后的被动事件窗口需要逐个 admission，例如受击、死亡、行动开始/结束。

## 距离完整复刻还缺

- 全怪物被动事件族 admission。
- 复杂 AI、阶段内/跨阶段序列、随机、冷却、目标选择策略。
- 波次系统、关卡面板装配、HardLevelGroup/Level 公式。
- 召唤物、assistant、特殊玩法怪物、环境机制。
- 光锥、内外圈遗器及套装机制。
