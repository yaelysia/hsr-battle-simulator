# CHAR-M1 记忆角色与忆灵构筑闭环 ready_for_review

## 状态

- 执行线程状态：`ready_for_review`
- 验收线程状态：`accepted`
- 验收日期：`2026-07-23`
- 执行卡：`simulator_v8_clean_core/docs/character_execution_cards/CHAR-M1_MEMORY_OWNED_COMBATANT_BUILD_CLOSURE.md`
- Checklist：验收线程已复核并勾选 CHAR-M1 唯一执行清单
- Git：执行线程交付时未提交 commit；验收通过后由验收线程提交检查点
- 阶段边界：未修改光锥或遗器规则，未强制忆灵开局出生，未推进其他角色扩面

本报告只是当前代码与验证 evidence 的索引，不代替验收。执行线程不声明 `accepted`，也不声明全记忆角色、全忆灵或全光锥机制已经复刻。

验收线程在独立输出目录重新运行 CHAR-M1 聚焦验证，结果为
`schema_version=char_m1_memory_owned_combatant_build_closure_v3`、`ok=true`。
修正后的多动作负例从正式准入目录中按结构选择具有两个必需动作的真实子构筑，
仅移除其中一个动作的能力绑定；另一个动作在修改后的 RuleBook 和子构筑结果中仍保持完整可执行，
而子构筑、父构筑及正式战斗准入均保持 blocked。该证据关闭上一轮验收阻断。

## 拒绝项修正

### 1. 削韧来源检查先于目标适用性

- `ToughnessSystem.apply_packet` 先检查 packet 的 coverage、amount stage 和类型化数值来源，再读取目标、弱点、韧性及免疫条件。
- 精确反例使用 `coverage_status=blocked`、空弱点目标，结果为 `ok=false`、`toughness_emission_not_executable:blocked`、0 mutation；不再返回 `toughness_skipped`。
- 代表动作仍使用无对应弱点目标，但只在确认该动作 6 条 toughness emission 均为 `executable` 后执行。这样目标不适用只会跳过已准入来源，不会掩盖来源缺口。

### 2. process-only 任务不再按 opcode 无条件放行

- `AbilityTaskIR.execution_mode` 由 lowering 显式投影；runtime 不再维护 opcode 豁免集合。
- 每个 process-only effect 都携带闭合的 `ability_process_only_source_shape_v1` 契约，包括 opcode、实际字段、字段类型、来源形状状态和 blocked reason。
- lowering 对未知字段、字段类型错误、缺必需字段、`DamagePerformFinish` 的结算控制字段、`SkillPerformFinish` 的结算控制字段及 `TriggerAnimStateWithMove` 嵌套事件 fail-closed。
- runtime 在任何分派前检查 task coverage、effect 身份、effect coverage、task/effect source 一致性和 source-shape 契约；明确 blocked 的任务返回非空 reason、0 mutation。
- 全量矩阵覆盖当前 RuleBook 的 148,728 个 process-only task、13 个 opcode：148,025 个 source-admitted、703 个 source-blocked，runtime admitted/blocked 数量逐项一致，`mismatch_count=0`。

### 3. 特殊资源由真实初始化器写入 runtime

- `SpecialResourceDefinitionIR` 与 `SpecialResourceInitializerIR` 保存最大值分支、最低值、初值表达式、动态 hash、世界等级阈值、等级来源、触发窗口和真实能力来源。
- 构筑输入只携带资源定义身份与初始化来源类型，不接受 `current_value`；旧式补零或任意当前值在闭合 JSON 边界被拒绝。
- `ScenarioStateBuilder` 在正式构筑单位创建时消费该绑定，要求第一波、有效 `battle_setup.world_level` 和同阵营存活非 servant 等级来源，计算最大值和初值并检查 `0 <= current <= maximum`。
- 当前真实正例在世界等级 6 得到 `maximum=34000`、`current=10200`，写入 `UnitState.resources`，并生成 `special_resource_initialization` settlement 与 source trace。缺世界等级时构筑场景 blocked；不会借初始化器绕过父构筑的其他阻断。

### 4. servant 定义所有权只有复数关系一套权威来源

- `ServantDefinitionIR` 已移除旧单一 `owner_entity_ref` 定义字段，只保存 `owner_relations`；`owner_entity_refs` 仅为关系集合的派生只读投影。
- lowering 不再生成旧 owner 字段或旧 owner source。构筑、scenario identity、summon 和 spawn 均通过 `owner_relation_for(actual_owner_entity_ref)` 解析唯一关系。
- RuleBook 对 servant definition ID、servant ref、owner relation ID 及 `(servant_definition_id, owner_entity_ref)` 语义身份执行重复拒绝，不再静默覆盖。
- 运行时单位上的实际 `owner_id` 是某次出生实例关系，不是第二套 servant 定义权威来源。

### 5. 必需动作集合必须整体闭合

- lowering 根据 servant character config 的 `SkillType`、`UseType`、`EntryAbility` 和对应技能记录来源，将槽位分类为 `required_action`、`passive` 或 `lifecycle`；无法分类的槽位阻断整个 action set。
- 每个 `required_action` 槽必须同时具有唯一技能、action definition、`turn_action` admission 和 executable ability binding；任一缺失都会使 action set 和子构筑 blocked。
- 装配器独立重建 `required_action_skill_ids`，要求它与槽位分类完全一致，并比较全部必需技能与实际 action bindings，不能再以“至少一个动作可用”代替完整性。
- 精确负例只从“父子均 admitted、至少两个必需动作、必需动作集合与已装配 binding 完全相等”的真实构筑中结构化选样；删除其中一个 action ability binding 后，另一个动作在篡改后的 RuleBook 和子构筑结果中仍完整 executable，但子构筑、父构筑和正式 battle admission 全部 blocked/rejected。重复 owner relation、动作缺失、动作冲突和 ability binding 缺失也分别 fail-closed。

## 构筑闭环

- 当前所有辅助技能节点通过类型化 owner relation 唯一归属到 `ServantDefinitionIR`，不按 Memory 名称、角色名或固定 ID 建表。
- `CharacterBuildAssemblyResult` 显式包含独立 `OwnedCombatantBuildAssemblyResult`；父构筑、子构筑、servant 定义和运行时单位使用不同身份。
- 子构筑保存属性公式、有效技能等级、必需动作绑定、机制图、owner relation、出生来源和 lifecycle admission，并有独立稳定 fingerprint。
- 默认行迹、显式行迹升级和星魂加级只进入所属 servant；父角色与 servant 双计、默认节点重复选择及同逻辑节点冲突均 fail-closed。
- 正式 scenario 只消费 canonical rebuild 后仍 admitted 的父子构筑。构筑成功只建立可出生定义；没有真实 spawn source 时 0 spawn mutation，有来源时复用通用 summon、spawn、timeline、action、damage/toughness 和 lifecycle 系统。

## 聚焦证据

最终命令：

```text
nice -n 10 env PYTHONPATH=hsr_v075_baseline_clean python3 \
  -m hsr.simulator_v8_clean_core.tools.validate_memory_owned_combatant_build_closure \
  --output-dir /tmp/hsr_v8_memory_owned_combatant_build_closure
```

结果：`schema_version=char_m1_memory_owned_combatant_build_closure_v3`、`ok=true`、`ready_for_review=true`。一次完整 lowering、一次完整 RuleBook、一次最小负例 RuleBook；未写完整 Canonical IR、RuleBook 或 transition dump。

| Evidence | 结果 | 实际证明 |
|---|---:|---|
| 受影响角色 / 辅助节点 / 辅助技能 | 7 / 84 / 49 | 当前目录全量，不是单角色抽样 |
| servant 定义 / owner relation | 6 / 7 | 共享 servant 保留两个独立来源关系，索引无覆盖 |
| 技能构筑变体 / oracle 行 | 28 / 196 | 默认、行迹升级和星魂等级逐行比较 |
| 含星魂加级 oracle 行 / 双计 | 94 / 0 | expected/actual 数值与来源恰好一致 |
| 正式 admitted 记忆构筑 | 2 | 结构化选出的真实空装备构筑，不是 fixture |
| 必需构筑负例 | 18 | 全部 blocked/rejected 且 state unchanged |
| 多必需动作精确负例 | 2 -> 1 | 仅移除 1 个 ability binding；保留动作在 RuleBook 与重装配子结果中仍 executable，父子及正式 admission 均拒绝 |
| process-only task | 148,728 | 148,025 admitted、703 blocked、0 runtime 错配 |
| 代表动作 mutation / settlement | 9 / 128 | 通用 action/ability/event/lifecycle 执行链 |
| source audit | 9 mutation / 9 record / 9 trace | 0 violation，每个受检 mutation 均有配对来源 |
| replay | equal | replay after、transition after 与执行 after 一致 |

新增及保留的关键谓词全部为真：

```text
blocked_toughness_source_precedes_target_applicability=true
process_only_task_requires_explicit_source_contract=true
required_special_resources_typed_and_source_backed=true
required_servant_definitions_assembled=true
owner_servant_relations_unique_and_source_backed=true
parent_child_battle_admission_atomic=true
missing_spawn_source_does_not_spawn=true
source_backed_spawn_preserves_owner_relation=true
spawned_servant_has_queryable_source_backed_action=true
representative_toughness_sources_admitted=true
representative_servant_transition_committed=true
representative_mutations_source_audited=true
representative_transition_replay_equal=true
fixed_character_or_servant_id_count=0
runtime_raw_tbgd_read_count=0
memory_path_has_formal_admitted_character_build=true
```

18 个构筑负例覆盖：父子准入篡改、缺 owner、owner 歧义、重复 owner relation、默认节点重选、默认与升级冲突、动作缺失、保留其他动作时删除必需动作、动作冲突、ability binding 缺失、属性缺失、lifecycle 缺失、spawn 缺失、错误 owner、父子双计、创建后容器修改、特殊资源定义缺失及外部注入特殊资源当前值。其中“保留其他动作时删除必需动作”在 `admission_negatives.json` 显式记录结构候选数、原始必需动作数、唯一删除数、保留动作数、保留动作 RuleBook/子结果可执行性、父子阻断和正式 admission 拒绝。另有两个精确 runtime 反例覆盖 blocked toughness 与 blocked process-only task。

Evidence 文件：

- `/tmp/hsr_v8_memory_owned_combatant_build_closure/summary.json`
- `/tmp/hsr_v8_memory_owned_combatant_build_closure/source_matrix.json`
- `/tmp/hsr_v8_memory_owned_combatant_build_closure/skill_ownership_matrix.json`
- `/tmp/hsr_v8_memory_owned_combatant_build_closure/admission_negatives.json`
- `/tmp/hsr_v8_memory_owned_combatant_build_closure/fail_closed_regressions.json`
- `/tmp/hsr_v8_memory_owned_combatant_build_closure/process_only_task_contract_matrix.json`
- `/tmp/hsr_v8_memory_owned_combatant_build_closure/special_resource_runtime_matrix.json`
- `/tmp/hsr_v8_memory_owned_combatant_build_closure/transition_replay_samples.json`

## 当前诚实阻断

以下 5 个父构筑均因子构筑 blocked 而原子 blocked，不被本卡吞掉：

- `avatar:1407 -> servant:11407`：`servant_stat_formula_nonpositive:max_hp`、`servant_timeline_stat_source_blocked`。
- `avatar:1409 -> servant:11409`、`avatar:1415 -> servant:11415`：`servant_stat_formula_nonpositive:speed`、`servant_timeline_stat_source_blocked`。
- `avatar:8007 -> servant:18007`、`avatar:8008 -> servant:18007`：`servant_spawn_source_missing`。当前 discovery 未取得来源，但尚不能据此断言 raw TBGD 永久无来源；后续仍需区分 raw source、lowering 与 admission gap。

`avatar:1402 -> servant:11402` 与 `avatar:1413 -> servant:11413` 是当前正式 admitted 正例。上述 ID 只用于报告定位，不参与生产分支或验证主选择。

## 对 P8 的影响

P8-S8 只运行 catalog startup 定向入口，不作为 S8 重验收：

```text
nice -n 10 env PYTHONDONTWRITEBYTECODE=1 python3 -B \
  -m hsr.simulator_v8_clean_core.tools.validate_p8_s8_light_cone_remaining_gameplay_closure \
  --tbgd-root ../turnbasedgamedata-main \
  --output-dir /tmp/hsr_v8_char_m1_p8_s8_startup \
  --catalog-startup-only
```

- `external_character_build_dependency_count=0`，CHAR-M1 负责的外部角色构筑依赖已关闭。
- 162 项中 159 项 started、3 项 startup blocked，所以顶层 `ok=false`、`formal_catalog_startup_complete=false`，不能声称光锥目录全绿。
- 三项是定义 `23036`、`23042`、`23049` 的两个 `summon_runtime_missing` 和一个 `first_target_alias_unresolved`；均标记为 equipment gap。本卡没有用强制开局出生 servant 绕过。

## 直接回归

所有重验证均低优先级、严格串行，后一项只在前一项退出后启动。

| 验证 | 结果 | 实际覆盖 |
|---|---|---|
| CHAR-M1 聚焦验证 | `ok=true` | 五个拒绝点、全目录、18 个构筑负例、source audit/replay |
| P7-S12 damage/toughness | `ok=true`，12 行 | 通用 damage/toughness stage 与 mutation ownership |
| P3-S5 servant lifecycle | `ok=true` | 6 定义，2 executable、4 blocked，7 负例，spawn/cleanup replay |
| P3-S6 summon action | `ok=true` | servant action executable，9 mutation，source audit/replay，6 负例 |
| P8-S2 character build | `ok=true` | 92 profile、644 promotion tier、1 个类型化特殊资源；既有两项 `implementation_missing` 分类未伪装消失 |
| P8-S8 catalog startup 定向 | 预期 `ok=false` | 159 started、3 equipment gap、外部角色构筑依赖 0 |
| P6-S2/S3 unit spawn/birth | `ok=true`，15 行 | 4 executable、11 boundary guard，构筑与出生分离 |

P4-S11 曾被实际尝试，但旧验证器要求先找到一个完全 executable 的普通角色动作，当前严格准入下没有该前置样本；它未生成通过矩阵，也未被列为绿色证据。本卡动作查询由聚焦验证和 P3-S6 覆盖。

## 最小检查

```text
env PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/hsr_v8_memory_pycache \
  python3 -m compileall -q hsr/simulator_v8_clean_core

git diff --check
```

两项均通过且无错误输出。

## 资源与未运行项

- 聚焦输出目录最终为 `1.7M`；P8-S8 启动定向为 `140K`；P6 出生单回归为 `116K`。
- 未运行 P1-P8 阶段聚合、P8-S8 全量验收、`validate_v0_209`、完整 Canonical IR/RuleBook 序列化或全量 transition dump；它们不属于本卡直接调用链，且执行卡禁止默认运行。
- 验证主选择使用结构化谓词；`fixed_character_or_servant_id_count=0`、`runtime_raw_tbgd_read_count=0`。
- 工作区原有无关未跟踪文件未修改；CHAR-M1 checklist、P8-S8 checklist 和 P8 总 checklist 均未修改。

## 阶段边界

距离最小可用记忆角色战斗纵切：已有两个真实空装备记忆角色构筑 admitted，其中至少一个可经真实 spawn source 出生、查询 source-backed servant 动作并提交 committed transition。本卡要求的 owned-combatant 构筑、父子原子准入、构筑与出生分离及代表执行纵切已形成可复核证据。

距离完整复刻仍缺：上述 5 个角色/servant 组的属性、timeline 或 spawn 来源闭合，全部记忆角色专属能力、状态、资源分支和生命周期细节，以及 P8 暴露的 3 个装备启动目标/servant runtime 缺口。后续不能把本报告解释为全角色、全忆灵或全光锥机制完成。
