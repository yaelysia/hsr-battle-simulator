# v0_285 完整状态监听事件族路由与安全执行

## 本阶段完成

- 新增 `StatusEventFamilyIR`，从已 lower 的 `StatusCallbackIR.event` 全量生成状态监听事件族矩阵。
- `CanonicalIR` 与 `RuleBook` 接入 `status_event_families`，支持按 callback event 和 runtime event source 查询。
- `EventDispatchSystem` 主路径改为读取 `StatusEventFamilyIR` 路由；旧 `CANONICAL_EVENT_ALIASES` 只保留为 fallback。
- 当前 TBGD lowering 统计结果：
  - `status_callbacks`: 29078
  - callback event 种类：200
  - `status_event_families`: 200
  - 有真实 runtime event source 的事件族：27
  - blocked/process-only 事件族：173
- 已接真实事件源的主要事件族包括：
  - 行动窗口：`OnBeforeSkillUse`、`OnBeforeAttack`、`OnAfterAttack`、`OnAfterSkillUse`、`OnActionEnd`
  - 命中窗口：`OnBeforeHit`、`OnBeforeHitAll`、`OnAfterHit`、`OnAfterHitAll`、`OnAfterBeingAttacked`、`OnBeingHit`
  - 回合/队列/死亡/击破：`OnListenTurnEnd`、`OnListenAllowAction`、队列插队前后、死亡、击破相关事件
  - 状态生命周期：`OnCreate`、`OnDestroy`、`OnStack`、`OnModifierAdd`、`OnModifierRemove`
- 补齐 `damage.before_hit` 运行时事件源，发生在 damage mutation 前。
- 状态系统在 add/remove/tick/expire lifecycle mutation 后产出 `status.lifecycle` process-only 事件，供事件分发系统统一路由。
- ability effect 与 ability task 管道补充事件传递，executor 会分发有真实战斗含义的 ability-emitted events。
- `OnCustomEvent`、`OnWaveMonster`、特殊玩法/波次/自定义事件保持 blocked/process-only，不造假事件源。

## 未完成内容

- “完整事件族”本阶段指完整路由、完整覆盖统计和安全 blocked 审计，不代表 200 种事件、95330 个 callback task 全部可执行。
- 资源变化类事件族，例如 HP、护盾、能量、战技点变化，仍需逐个 mutation payload admission 后才能放开。
- 波次、自定义事件、特殊玩法事件没有真实事件源，继续 blocked。
- 状态 stack/refresh 的完整游戏语义还未 admission；当前只在已有 lifecycle mutation 成立时发出对应 process-only 事件。
- standalone ability 内部事件已能返回，但复杂递归监听触发仍需按事件族逐步验证，不能把未 admission task 自动放开。

## 验证结果

在 `hsr_v075_baseline_clean/hsr` 下已通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_285 --output-dir /tmp/hsr_v8_status_event_families_v0_285
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_282 --output-dir /tmp/hsr_v8_regression_v0_282
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_283 --output-dir /tmp/hsr_v8_regression_v0_283
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_284 --output-dir /tmp/hsr_v8_regression_v0_284
git diff --check
```

结果均为通过，其中 `validate_v0_285` 输出 `ok=True`。

## 距离最小可用战斗纵切还缺什么

- 怪物固定序列动作已经能给候选，但还需要 UI/推演器选择目标后覆盖更多怪物技能样例。
- 怪物状态监听事件族已建底座，下一步应优先补资源变化类事件、控制类状态效果和常见怪物状态回调。
- 关卡等级倍率、波次、召唤物仍未接，敌方完整行动纵切还不完整。

## 距离完整复刻还缺什么

- 全角色数据卡、光锥、内外圈遗器与套装机制。
- 全怪物技能、被动、阶段切换、召唤、波次和关卡环境。
- 完整状态系统：控制、抵抗、命中、刷新、叠层、驱散、免疫、持续时间和所有事件族的真实执行 admission。
- 资源、护盾、治疗、伤害修改、行动条、队列插队等跨系统监听的全量来源审计。
