# v0_286 已有底层 mutation 的状态监听事件源补齐

## 本阶段完成

- 新增 `systems/mutation_events.py`，把已提交的 `Mutation` 统一转换为 process-only `GameEvent`。
- mutation-backed event payload 统一包含：
  - `before`、`after`、`delta`
  - `mutation_id`、`mutation_path`
  - `source`、`source_kind`、`source_trace`
  - `target_id`、`actor_id`、`source_id`
- `StatusEventFamilyIR` 矩阵补齐以下已有底层 mutation 支撑的事件源：
  - HP/治疗：`OnHPChange`、`OnListenHPChange`、`OnAfterBeingHeal`、`OnAfterDealHeal`、可证明溢出的 `OnHPOverflow`
  - 护盾：`OnShieldChange`、`OnListenShieldChange`、`OnListenInitShield`
  - 资源：`OnSPChange`、`OnBeforeEnergyPointChange`、`OnEnergyPointChange`
  - 韧性/击破：`OnBeforeBeingStanceDamage`、`OnBeingStanceDamage`、`OnListenBreak`
  - 状态生命周期别名：`OnAddModifierSuc`、`OnListenModifierAdd`、`OnListenModifierRemove`、`OnModifierOnStack`、`OnListenModifierOnStack`、`OnModifierDotAdd`
  - 行动延后：`OnActionDelayEffect`、`OnActionDelayEffectAll`、`OnListenGlobalActionDelayChanged`
- `EventDispatchSystem` 放开 mutation-backed 全局 listen 路由，但 listener 仍必须通过原本的 callback admission 才能产生 mutation。
- before 类事件已可见、可路由、可审计，但当前会以 `pre_mutation_listener_recompute_not_admitted` 阻塞执行，避免 listener 在没有重算 ledger 的情况下改写同一路径。
- `CombatExecutor` 接入行动资源、伤害 HP mutation、击杀回能、韧性 before 事件和 ability/effect 事件分发。
- `EffectRegistry` 接入治疗、护盾、SP/能量 effect mutation 的事件生成。
- `StatusCallbackSystem` 接入 listener 内部行动延后 mutation 的事件生成。
- `ToughnessSystem` 给已有 `toughness.hit` 事件补充 mutation payload，不重复发第二套削韧事件。
- `BreakSystem` 给已有 `break.triggered` 补齐 listen 别名、目标和来源信息。

## 明确仍 blocked 的范围

以下不是“底层已有但忘了接”，而是当前缺核心语义或缺安全 payload，继续 blocked/process-only：

- 驱散：`OnDispel`、`OnListenModifierDispel`
- 抵抗：`OnResistModifier`、`OnListenModifierResist`
- 锁血阈值：`OnLockHPThresholdReached`
- 红韧性、弱点叠加、特殊条和特殊玩法事件
- 波次、自定义事件：`OnWaveMonster`、`OnCustomEvent`
- 缺目标、缺 payload 字段、缺来源、unsupported callback task
- before 类监听改写当前 pending mutation 同一路径且没有重算 ledger 的情况

## 验证结果

在 `hsr_v075_baseline_clean/hsr` 下已通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_286 --output-dir /tmp/hsr_v8_mutation_events_v0_286_rerun
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_282 --output-dir /tmp/hsr_v8_regression_v0_282_after_v0_286_scope
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_283 --output-dir /tmp/hsr_v8_regression_v0_283_after_v0_286_scope
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_284 --output-dir /tmp/hsr_v8_regression_v0_284_after_v0_286_scope
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_285 --output-dir /tmp/hsr_v8_regression_v0_285_after_v0_286_scope
git diff --check
```

结果均为通过，其中 `validate_v0_286` 输出 `ok=True`。

`validate_v0_286` 核心断言：

- 当前 200 个 `status_event_families` 仍全量存在。
- 本轮补齐的事件族全部 `coverage_status=executable`，且都有 runtime event source。
- HP damage、治疗、治疗溢出、护盾初始化、SP、能量、行动延后均产生 mutation-backed process-only event。
- 行动 SP/能量、终结技能量与击杀回能这类当前 engine convention 资源 mutation 的事件 payload 标明 `source_kind=engine_convention`。
- TBGD effect 产生的治疗/护盾/资源 mutation 的事件 payload 标明 `source_kind=tbgd_effect`。
- before 韧性事件可路由到 `OnBeforeBeingStanceDamage`，但执行被安全阻塞且 state unchanged。
- 驱散、抵抗、锁血阈值、自定义事件、波次事件继续 blocked。

## 距离最小可用战斗纵切还缺什么

- 怪物固定序列动作、技能伤害、技能附带状态、状态监听反击、资源变化事件源已经能形成更完整的敌方行动测试链路。
- 仍需要补控制类状态的真实效果、抵抗/命中/免疫、驱散、状态刷新/叠层的完整规则。
- before 类监听若要真正执行改写 pending mutation，需要为对应路径建立可重算 ledger。
- 敌方阶段切换、召唤、波次、关卡倍率仍未接。

## 距离完整复刻还缺什么

- 全角色数据卡、光锥、内外圈遗器与套装机制。
- 全怪物技能、被动、阶段切换、召唤、波次和关卡环境。
- 完整状态系统：控制、抵抗、命中、刷新、叠层、驱散、免疫、持续时间和所有事件族的真实执行 admission。
- 资源、护盾、治疗、伤害修改、行动条、队列插队等跨系统监听的全量来源审计和更多正负例。
