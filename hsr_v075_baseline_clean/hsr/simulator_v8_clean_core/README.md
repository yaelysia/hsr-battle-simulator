# simulator_v8_clean_core

`simulator_v8_clean_core` 是《崩坏：星穹铁道》战斗模拟器的 v8 主线内核。

v8 是 TBGD-first 的干净重写线，事实来源固定为：

```text
turnbasedgamedata-main -> TBGD compiler/lowering -> Canonical IR -> Combat Core
```

当前检查点：

```text
v0_289 target expression sequence filter retarget
最近代码检查点提交：f1fe9ce
```

## 基本规则

- runtime 只读取 Canonical IR / 数据卡 IR，不读取 raw TBGD、TextMap、旧 v7、旧 model pack。
- TBGD raw schema 只能在 compiler/lowering/discovery/审计工具层读取。
- UI、游戏观测值、TextMap 名称、技能说明只能用于展示或验证，不能作为 runtime 规则来源。
- 所有状态变化都必须通过 `Mutation` 表达。
- 每次动作必须输出 `BattleTransition`，包含 before/after snapshot、目标解析、mutation、settlement、source audit、replay 信息。
- `blocked`、`audit_only`、`discovered_only`、placeholder 只能产生 process-only 记录，不能产生 mutation。
- 不允许按角色名、怪物名、技能名、固定 ID、固定文件名、固定 hash 或观测数值驱动规则。

详细红线见：

- `FORBIDDEN.md`
- `PROJECT_GOALS.md`
- `../CODEX_HANDOFF.md`

## 当前已落地范围

- Canonical IR、RuleBook、snapshot/replay、settlement/source audit。
- action/event/ability task/effect/status callback/queue/timeline 等核心骨架。
- direct、DoT、hp loss、break、break DoT、super-break、弹射、目标组、多段、击杀归因等伤害底座的当前可信范围。
- 普通状态生命周期、buff/debuff 共用 unit-attached status lifecycle、动态值绑定、资源、队列、额外行动语义、事件分发。
- 角色数据卡边界、加强版希儿示例卡、行迹/星魂通用接口。
- 怪物卡规范、`MonsterDataCardIR`、普通怪物技能动作、固定序列行动候选、怪物技能附带状态。
- 状态监听事件族矩阵、mutation-backed 事件源、银鬃尉官基础反击纵切。
- 目标表达式 IR 与安全解析子集：简单别名、明确群体、上下文目标列表、`TargetSequence`、`TargetFilter`、确定性 `Retarget`。
- P1-0 action availability 查询边界：外部推演器可查询当前普通动作、queue mandatory/selectable、pending turn end、enemy fixed-sequence candidate 和 summon blocked。
- 本地 UI 测试台 `simulator_v8_ui/`，作为测试编排与审计展示层，不作为规则系统。

## 当前仍未完整落地的大块

- 完整角色面板装配：晋阶、全量角色行迹、光锥、内圈/外圈遗器及套装效果。
- 大量角色卡人工解释、结构化 admission 与验证。
- 完整状态系统：叠层、刷新、概率、失败分支、持续时间、tick、DoT tick、控制、抵抗、免疫、驱散。
- 完整目标系统：排序、随机、fetch、相邻目标、唯一实体、召唤物/servant 目标、特殊玩法目标。
- 全怪物技能、被动、阶段切换、召唤、波次、关卡倍率。
- 完整敌方行动推演策略、波次系统、召唤物/assistant、特殊战斗模式。
- 光锥、遗器、环境、关卡机制。

## 推荐验证

在 `hsr_v075_baseline_clean/hsr` 下运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_0_action_boundary --output-dir /tmp/hsr_v8_p1_0_action_boundary
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_289 --output-dir /tmp/hsr_v8_target_expression_v0_289
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_288 --output-dir /tmp/hsr_v8_target_expression_v0_288
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_287 --output-dir /tmp/hsr_v8_status_target_audit_v0_287
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_286 --output-dir /tmp/hsr_v8_mutation_events_v0_286
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_284 --output-dir /tmp/hsr_v8_monster_attached_status_v0_284
git diff --check
```

当前期望：

- `compileall` 通过。
- 验证输出 `ok=true`。
- replay/source audit/settlement traceability 通过。
- unsupported、blocked、audit-only、discovered-only 不产生 mutation。
- runtime/core/systems 不引用 UI，不读取 raw TBGD/TextMap/旧 v7/旧 model pack。

## 下一阶段建议

当前目标表达式底座已补到可支撑更多状态和怪物技能。下一阶段建议优先补状态系统主体：

1. `stack/refresh/chance`。
2. `duration/tick/expire`。
3. DoT tick、控制、抵抗、免疫、驱散。

每个新增机制仍必须满足：真实来源、通用接口、正例可审计、负例 state unchanged。
