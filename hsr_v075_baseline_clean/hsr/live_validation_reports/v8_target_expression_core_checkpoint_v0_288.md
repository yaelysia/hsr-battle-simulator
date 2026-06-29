# v0_288 目标表达式核心底座

## 本阶段完成

- 新增 `TargetExpressionIR`，进入 `CanonicalIR.target_expressions`。
- `RuleBook` 增加只读索引：
  - `target_expression(target_expression_id)`
  - `target_expressions()`
- TBGD lowering 会从 ability task 的目标字段生成目标表达式 IR，并把 `target_expression_id` 写入 effect 的标准 payload。
- `TargetSystem` 新增只读目标表达式解析接口，支持有限安全子集：
  - 单体：`Caster`、`ModifierOwnerEntity`、`ParamEntity`、`CurrentActionTarget`、`AbilityTargetEntity`
  - 群体：`AllEnemy`、`AllTeamMember`、`AllLightTeam`、`AllTeammate`
- `StatusSystem.apply_add_modifier` 优先使用 `target_expression_id` 解析目标；没有 `target_expression_id` 时保留旧 alias fallback。
- 新增 `validate_v0_288`，验证目标表达式 IR、AddModifier 正例、blocked 负例和旧 alias fallback。

## 数据库事实进入 IR 的结果

`validate_v0_288` 本轮构建结果：

- `target_expression_count=243671`
- `executable=190885`
- `blocked=52786`
- effect 标准 payload 中带 `target_expression_id` 的记录数：99850

目标表达式类型高频项：

- `TargetAlias=222862`
- `Retarget=10029`
- `TargetFetchCaster=7491`
- `TargetTimeSlow=1157`
- `TargetFetchPartner=1026`
- `TargetSequence=692`
- `TargetConcat=229`
- `TargetFetchUniqueNameEntity=157`

目标别名高频项：

- `Caster=113463`
- `ModifierOwnerEntity=34003`
- `AbilityTargetEntity=21264`
- `AllEnemy=8480`
- `ParamEntity=7517`
- `AllDarkTeam=3466`
- `AllLightTeam=3359`
- `CasterSummonedMinions=2461`
- `CasterServant=1930`
- `AbilityTargetAdjoinEntity=1834`

## 正例与负例

正例选择策略：

- 只选 `Config/ConfigAbility/Avatar`、`Config/ConfigAbility/Monster`、`Config/ConfigAbility/Equip` 主线来源。
- 按结构化谓词选择 `EffectIR(opcode=AddModifier)`。
- 要求 `standard.target_expression_id` 存在。
- 要求对应 `TargetExpressionIR.coverage_status=executable`。
- 要求直接执行 `StatusSystem.apply_add_modifier` 成功，不被动态值、监听器、duration 或 modifier 定义缺失阻塞。
- 不按固定角色名、怪物名、技能 ID、文件名或观测值选择。

本轮实际正例：

- 单体正例来自 Avatar 主线 ability，目标别名为 `ModifierOwnerEntity`。
- 群体正例来自 Monster 主线 ability，目标别名为 `AllEnemy`。
- 两个正例都会产生状态 mutation，并在 `status_details.source_trace.target_expression` 中记录目标表达式解析来源。

负例覆盖：

- 缺失 `target_expression_id`：blocked，不产生 mutation。
- `TargetSequence` / `Retarget` 等未 admission 表达式：只进入 IR 和报告，runtime blocked，不产生 mutation。
- `TargetSystem.resolve_target_expression` 对 blocked 表达式返回明确 blocked reason。
- 没有 `target_expression_id` 的旧 alias fallback 仍可执行，避免未迁移 payload 断掉。

## 当前支持边界

本阶段不是完整目标表达式系统，只是核心底座：

- 已支持：直接目标别名和明确阵营群体目标。
- 未支持：`TargetSequence`、`TargetFilter`、`Retarget`、`TargetFetch*`、`TargetSort*`、相邻目标、召唤物目标、servant 目标、唯一实体查询、特殊玩法目标。
- 未支持项都保留为 `TargetExpressionIR`，并带 `coverage_status=blocked`、`blocked_reason`、`admission_batch`。
- Runtime 仍只读取 Canonical IR / RuleBook，不读取 raw TBGD。

## 验证结果

在 `hsr_v075_baseline_clean/hsr` 下已通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_288 --output-dir /tmp/hsr_v8_target_expression_v0_288
```

`validate_v0_288` 输出 `ok=True`，核心断言包括：

- `target_expressions` 已生成。
- effect payload 中存在 `target_expression_id` 引用。
- executable alias 和 blocked composite/fetch 表达式都存在。
- AddModifier 正例通过目标表达式解析后产生状态 mutation。
- 状态详情能反查到目标表达式来源。
- missing/blocked target expression 不产生 mutation。
- payload 中 `target_alias` 与 `target_expression.alias` 不一致时 blocked，防止手工改 alias 绕过表达式来源。
- 旧 alias fallback 仍可执行。
- static checks 通过。

回归验证已通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_284 --output-dir /tmp/hsr_v8_regression_v0_284_after_v0_288
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_286 --output-dir /tmp/hsr_v8_regression_v0_286_after_v0_288
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_287 --output-dir /tmp/hsr_v8_regression_v0_287_after_v0_288
```

## 距离最小可用战斗纵切还缺什么

- 目标表达式核心别名已经可支撑更多怪物技能附带状态和部分 callback task。
- 下一步应补 `TargetSequence`、`TargetFilter`、`Retarget` 的安全子集，尤其是 `SkillTargetEntityList`、`ParamEntityList`、`TeamFormation` 这类审计中高频但还没 admission 的目标来源。
- 状态 stack/refresh/chance、duration/tick/expire、DoT tick 仍未完整。
- 控制、抵抗、免疫、驱散、锁血阈值仍 blocked。

## 距离完整复刻还缺什么

- 完整目标表达式系统，包括序列、过滤、排序、fetch、唯一实体、相邻目标、召唤物和特殊玩法目标。
- 完整状态系统：叠层、刷新、概率、失败分支、持续时间、tick、DoT、控制、抵抗、免疫、驱散。
- 全角色数据卡、光锥、内外圈遗器与套装机制。
- 全怪物技能、被动、阶段切换、召唤、波次和关卡倍率。
- 完整敌方行动推演、波次和关卡环境。
