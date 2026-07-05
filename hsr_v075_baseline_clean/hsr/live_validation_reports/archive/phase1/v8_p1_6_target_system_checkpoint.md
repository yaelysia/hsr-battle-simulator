# P1-6 目标系统关键缺口 checkpoint

## 本阶段完成

- `TargetExpressionIR` admission 扩展到 P1-6 安全 pipeline 子集：
  - `TargetFetchCaster`
  - `TargetFetchParamEntityList`
  - `TargetFetchPartner`
  - `TargetFetchUniqueNameEntity`
  - `TargetMapAdjoinEntity`
  - `TargetSortByProperty`
  - `TargetSortByPropertyRatio`
  - `TargetSortByFormation`
  - `TargetTake` / `TargetIndex`
  - `TargetReverse`
  - `TargetShuffle`
- `TargetAlias` 纳入安全全局 target config 子集：
  - 直接 alias：`AbilityTargetAdjoinEntity` 等相邻目标族。
  - dot-chain alias：`AllEnemy.SortByHP`、`AllEnemy.SortByHPRatio`、`AllLightTeam.GetAliveOnly.SortByHPRatio` 等。
- `ConfigAI` target strategy 只进入矩阵统计，不进入 P1-6 executable runtime 主路径。
- `TargetSystem` 从单点 alias resolver 扩展为 producer/transform pipeline：
  - Fetch/Alias 产出候选。
  - Filter/Sort/Take/Index/Reverse/Adjacent/Random 转换候选。
  - resolution steps 记录候选池、排序 key、方向、tie-breaker、跳过原因、blocked reason。
- Random target 不使用进程随机或隐式 hash；只接受 `event_payload["target_random_choices"]` 显式 choice ledger，并生成 `RNGEvent(rng_type="target_random")`。
- `TargetExpressionResult` 新增 `rng_events`，并在 `StatusSystem.apply_add_modifier` / `apply_dispel_status` 透传。
- target expression blocked 的状态路径会写 process-only settlement record，带 target resolution trace；不产生 mutation。
- `target_unique_entity_registry` 和 `target_partner_registry` 均为显式 runtime registry；缺 registry、缺 key、多目标、dead/removed 均 blocked。`TargetFetchPartner` 带 `Name` 时只允许命名 key 或 `caster:name` key，不能回退到 caster 默认 partner，并在 resolution step 记录 `matched_registry_key`。
- summon target 继续复用 P1-3 `summon_runtime`：`LastSummonMonsters`、`CasterSummonedMinions` 有正例；servant target 没有 executable runtime registry，保持 source gap blocked。

## 数据库事实进入 IR 的结果

`validate_p1_6_target_system` 本轮构建结果：

- `target_expression_count=243671`
- `executable=216510`
- `blocked=27161`
- `p1_6_target_pipeline=12662`
- P1-6 可执行样例计数：`12347`

Fetch 正例矩阵：

- `TargetFetchCaster=7491`
- `TargetFetchParamEntityList=2`
- `TargetFetchPartner=1026`
- `TargetFetchUniqueNameEntity=157`

Sort 正例矩阵：

- `CurrentHP=48`
- `HPRatio=3`

仍 blocked 的 sort/fetch 继续保留 source trace 和 blocked reason，例如：

- `TargetSortByModifierValue`
- `TargetSortMonsterRank`
- `ParamEntityAttackTargetList.SortByHP`
- 特殊玩法或未 admission 的 dot-chain alias

## 正例与负例

正例选择策略：

- 按 `TargetExpressionIR.kind`、`alias`、`coverage_status`、`admission_batch`、normalized payload 选择。
- 不按固定角色名、怪物名、技能 ID、文件名、hash 或观测答案选择。
- mutation 正例只从真实 `EffectIR(opcode=AddModifier)` 和 executable target expression 选取。

本轮通过的正例：

- HP sort、HP ratio sort。
- `TargetFetchCaster`、`TargetFetchParamEntityList`、`TargetFetchPartner`、`TargetFetchUniqueNameEntity`。
- `TargetFetchPartner` 命名来源精确命中 `caster:name`，并验证命名缺失时不会被 caster 默认项冒充。
- `AbilityTargetAdjoinEntity` 中间位置、边缘位置、removed neighbor。
- random target 显式 choice、replay 稳定、RNG event 记录。
- `LastSummonMonsters`、`CasterSummonedMinions`。
- AddModifier runtime mutation 能从 mutation/settlement 反查 target expression IR 和 TBGD source。

本轮负例：

- 缺 sort payload blocked。
- 缺 retarget payload blocked。
- random 缺 choice 返回 `requires_rng_choice`。
- random invalid choice blocked。
- unique missing、ambiguous、defeated 均 blocked。
- missing partner registry、missing summon runtime 均 blocked。
- status target blocked 路径 process-only、无 mutation。

## Source Gap

- toughness sort 当前没有安全真实正例，记录为 source gap；runtime admission 保留安全实现，缺正例不伪造 mutation。
- formation sort 当前没有安全真实正例，记录为 source gap；缺 position 时 blocked。
- `TargetFetchOwner` / `TargetFetchModifierOwner` 当前没有数据库正例，记录为 source gap。
- servant target 当前没有 executable runtime registry，记录为 source gap blocked。
- `ConfigAI` 中的 TargetSort 不作为 P1-6 executable 主路径。

## 验证结果

在 `hsr_v075_baseline_clean/hsr` 下已通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_6_target_system --output-dir /tmp/hsr_v8_p1_6_target_system
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_288 --output-dir /tmp/hsr_v8_target_expression_v0_288_after_p1_6
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_289 --output-dir /tmp/hsr_v8_target_expression_v0_289_after_p1_6
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_4_status_system --output-dir /tmp/hsr_v8_p1_4_after_p1_6
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_3_summon_assistant_servant --output-dir /tmp/hsr_v8_p1_3_after_p1_6
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_5_queue_window_system --output-dir /tmp/hsr_v8_p1_5_after_p1_6
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_264 --output-dir /tmp/hsr_v8_bounce_rng_v0_264_after_p1_6
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_286 --output-dir /tmp/hsr_v8_mutation_events_v0_286_after_p1_6
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_287 --output-dir /tmp/hsr_v8_status_target_audit_v0_287_after_p1_6
git diff --check
```

全部输出 `ok=True` 或无 diff whitespace error。核心断言包括：

- P1-6 target scope matrix 通过。
- sort/fetch/adjacent/random/dynamic max/blocked/status blocked trace/mutation audit 全部通过。
- replay 和 source audit 通过。
- static checks 通过。

## 距离最小可用战斗纵切还缺什么

- 目标系统已经能支撑第一阶段最关键的 sort/fetch/adjacent/random/unique/summon 子集。
- 仍需要 P1-7 把 RNG 分支枚举、概率分支和 replay ledger 扩成统一接口。
- 状态系统还需要继续补 tick、DoT tick、控制、抵抗、免疫、驱散等主体。

## 距离完整复刻还缺什么

- 完整目标表达式系统：特殊玩法目标、完整 random 分支枚举、更多 sort/fetch/servant runtime registry。
- 完整角色面板、光锥、遗器、环境和关卡机制。
- 全角色/全怪物机制解释、阶段切换、召唤、波次和敌方行动推演。
