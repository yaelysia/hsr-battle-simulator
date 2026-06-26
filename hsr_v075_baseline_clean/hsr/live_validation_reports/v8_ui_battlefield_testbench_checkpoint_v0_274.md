# v8 UI 战场式测试台检查点 v0_274

## 本阶段做到哪里

- UI 测试台从 JSON/表格优先改为战场式入口：左侧行动条，中间敌我单位卡片，右侧事件回放，底部单位/事件详情抽屉。
- `/api/catalog` 增加 UI 动作槽位摘要，优先用角色卡 `action_set` 的 `Skill01/Skill02/Skill03`，再用 `ActionDefinitionIR.attack_type` 校验普攻、战技、终结技；缺角色卡时只退回 Canonical IR 的头像档案动作列表。
- `/api/run` 的报告增加 `battlefield_view`、`action_prompt`、`event_replay_view`，只用于展示和编排，不参与 runtime 规则计算。
- 点选路线采用“选择技能 -> 选择目标 -> 追加 route -> 从初始场景重跑”的无隐藏状态模式。

## 没做什么

- 第一版不接 TextMap，不提供官方中文名；显示名只来自 scenario 的 `metadata.ui_aliases`，缺失时显示原始 ID。
- 第一版暂时跳过敌方回合，不做敌方 AI 或敌方动作按钮。
- UI 不计算伤害、不补规则、不猜 action id；动作槽位缺来源时只显示未接通或禁用。
- 未实现完整角色、光锥、遗器、装备、关卡环境和波次系统装配。

## 距离最小可用战斗纵切还缺什么

- 需要更多真实角色卡动作槽位和可执行动作，保证常用测试角色能直接点普攻、战技、终结技。
- 需要更完整的目标模式展示，例如单体、扩散、群攻、自身、我方目标的 UI 约束。
- 需要把事件回放继续细分为更接近游戏调试流程的时间窗、触发器、状态来源和队列插队视图。

## 距离完整复刻还缺哪些大模块

- 完整面板装配：晋阶、行迹全量、装备、光锥、遗器、套装。
- 大量角色机制卡解释与验证。
- 敌方 AI、波次、召唤物、assistant、特殊模式。
- 光锥、遗器、环境、关卡机制。
- custom event、wave event 的真实事件源。

## 验证

- 本轮已运行并通过：
  - `PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui`
  - `PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_ui.validate --output-dir /tmp/hsr_v8_ui_v0_274`
  - `git diff --check`
