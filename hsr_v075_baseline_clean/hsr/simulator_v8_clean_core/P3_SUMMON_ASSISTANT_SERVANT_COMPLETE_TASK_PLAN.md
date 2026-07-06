# P3 召唤物 / 忆灵 / Assistant 体系完整覆盖分步计划

本文档是 P3 召唤物相关体系的执行计划。它延续 P2 状态系统的严格口径：先盘点当前数据库和 IR 中所有相关来源，再分层归因，最后只把有真实来源、可审计、可回放的路径做成 executable。缺来源、缺条件、缺目标、缺事件 payload、缺公式、缺 action admission 的路径必须 blocked / process-only / state unchanged，不能用 synthetic 正例凑完成。

## 0. 背景和当前事实

P1 已经完成召唤物体系的最小纵切：

- `SummonMonster` ability task 已 lower 到 `SummonMonsterIntentIR`，可生成敌方召唤怪物。
- 召唤怪物 spawn 会产生 `UnitSpawn` mutation 和 `summon_runtime` mutation，并通过 replay / source audit。
- `SummonUnitData` / `ConfigSummonUnit` 已进入 `SummonUnitDefinitionIR` discovery，但当前仍按 catalog / visual / adventure 边界处理，不等同于战斗 runtime 自动生成。
- `AvatarServantConfig` / `AvatarServantSkillConfig` 已 lower 到 `ServantDefinitionIR`，runtime 支持 servant / 忆灵 spawn、remove、target registry、action availability 和 BattleSetup initial setup。
- servant 目标相关别名已经有第一阶段正例，flag-only servant 不会被当成真实目标。
- `TurnInsertAssistantAbility` 已进入 `AssistantAbilityResolutionIR`，但 assistant actor / stats / execution source 当前未 admission，仍是 boundary-only。

当前明确不足：

- 召唤物总账本还没有像 P2 状态系统那样完整覆盖所有 raw / IR / runtime 来源域。
- `SummonUnitData` 仍没有拆清 combat battle summon 与 client / scene / adventure summon 的完整 admission。
- summoned monster 的移除、过期、owner death cleanup、波次清理还只覆盖最小边界。
- servant / 忆灵虽然可以生成和作为行动单位出现，但 damage stat binding、资源归属、完整技能执行、生命周期联动仍未宣称完整。
- assistant 仍没有可执行 actor / stats / action graph / queue drain 正例。
- summon runtime schema 还是 P1-3 版本，后续需要升级成能表达多类召唤实体、生命周期、目标关系、行动、来源审计的稳定契约。

P3 的目标不是做敌方 AI。敌人、召唤怪物、servant、assistant 的动作选择仍由外部推演器控制；core 只提供合法动作、目标、队列、生命周期和结算规则。

## 1. 范围定义

本阶段覆盖“召唤物相关体系”，包括：

- 敌方或机制生成的 summoned monster。
- `SummonUnitData` / `ConfigSummonUnit` 中能证明属于战斗 runtime 的 battle unit summon。
- servant / 忆灵，包括 owner 绑定、属性继承、行动、目标关系、生命周期。
- assistant ability，包括 `TurnInsertAssistantAbility`、assistant queue / window、assistant action execution。
- 召唤物与状态、目标、队列、时间线、波次、BattleSetup、source audit、replay 的联动。

本阶段不覆盖：

- 敌方 AI 或自动选招策略。
- 全角色、全怪物机制解释本身；只在召唤体系需要时接入必要数据卡槽位。
- 光锥、遗器、关卡环境的完整复刻；只处理它们提供召唤来源时的分类和边界。
- 没有真实战斗 runtime 来源的 client / scene / adventure summon。

## 2. 完成定义

P3 召唤物体系完成必须同时满足：

- 当前 TBGD / Canonical IR 中所有 summon / servant / assistant 相关来源都有覆盖矩阵。
- 每个来源都完成分层归因：raw 是否存在、lowering 是否投影、RuleBook 是否保留 admission 字段、runtime 是否有通用语义、validation 是否能结构化选样。
- 有真实来源且当前语义可支持的路径都能 executable，并产生 transition、mutation、settlement、replay 和 source audit。
- 不能执行的路径都有明确原因，并验证 blocked / process-only / state unchanged。
- summon runtime schema 能表达实体身份、owner/summoner、队伍归属、唯一组、目标关系、生命周期、行动 admission、来源审计和移除状态。
- 所有 `UnitSpawn`、`UnitRemove`、runtime registry、queue、timeline、status、damage 相关 mutation 都能反查到 settlement，再反查到 IR，再反查到 TBGD source path / evidence。
- validation 不靠固定角色名、怪物名、技能名、文件名、hash 或观测答案作为主路径。
- runtime 不读取 raw TBGD、TextMap、旧 v7、旧 model pack。
- 不引入角色、怪物、关卡、路线硬编码特判。
- 默认验证不写完整 Canonical IR、大体积 coverage 或完整 transition dump；大产物必须显式开关。

不能宣称完成的情况：

- 只验证 `SummonMonster`，不盘点 servant / assistant / `SummonUnitData`。
- 只验证 spawn，不验证 remove / cleanup / wave / target / queue / action boundary。
- 只把 blocked negative 当成机制完成，但没有真实来源正例。
- 只看聚合 `ok=true`，不审查 source trace 是否指向真实 IR 节点。
- 把 client / visual / adventure summon 当成 battle runtime 来源。

## 3. 分类口径

每个召唤相关机制只能使用以下分类：

- `executable`：有真实来源，runtime 可执行，mutation / settlement / replay / source audit 均通过。
- `source_absent_not_required`：当前数据库没有这种战斗 runtime 结构化来源，且不属于当前数据库必须执行的路径。
- `boundary_only`：当前只需要明确边界，runtime 必须 blocked / process-only / state unchanged。
- `lowering_gap`：raw 有来源，但 lowering 没投影或投影丢字段。
- `admission_gap`：IR 有来源，但 RuleBook 或 admission 谓词不足。
- `validation_gap`：runtime 已支持，但验证脚本选样或断言不足。
- `implementation_missing`：有真实来源，但 runtime 没有正确执行语义。

标记 `source_absent_not_required` 前必须先排除 lowering gap、admission gap 和 validation gap。不能把“当前脚本没扫到”直接当成数据库没有来源。

## 4. 阶段拆分

```text
P3-S0  召唤物来源全量盘点和术语归一
P3-S1  Summon / Servant / Assistant IR 与 RuleBook 契约补齐
P3-S2  summon runtime schema v2 与实体身份统一
P3-S3  summoned monster 生成、位置、数量、唯一组和延迟 admission 完整化
P3-S4  battle unit summon / SummonUnitData 来源拆分和 runtime admission
P3-S5  servant / 忆灵定义、属性、生命周期、owner 关系完整化
P3-S6  召唤单位行动可用性和动作执行链路
P3-S7  assistant ability、assistant queue/window 和执行边界
P3-S8  目标系统中的召唤物 / servant / assistant 关系扩展
P3-S9  移除、过期、owner cleanup、死亡、波次切换和清场
P3-S10 状态、资源、伤害、击杀归因与召唤物联动
P3-S11 BattleSetup、scenario、外部推演器接口和端到端样例
P3-S12 全来源闭环、聚合验收、报告和交接
```

## 5. P3-S0 召唤物来源全量盘点和术语归一

### 目标

建立召唤体系总账本。执行层在改 runtime 前，必须先知道当前数据库里有哪些召唤相关来源，分别属于哪类战斗语义。

### 必须覆盖

- `SummonMonster` ability task。
- `SummonUnitData` / `ConfigSummonUnit` / summon unit config。
- `MonsterConfig.SummonIDList` 等 catalog 引用。
- `AvatarServantConfig` / `AvatarServantSkillConfig` / servant ability files。
- `TurnInsertAssistantAbility` 及其 queue intent。
- summon / servant / assistant 相关 target alias / target operation。
- owner death、remove、expire、wave clear、lifetime、targetability、actionability 相关来源。
- 角色、怪物、stage、battle event、global config 中可能触发召唤或影响召唤物的来源。

### 验收结果

- 输出轻量覆盖矩阵，至少包含来源域、raw 数量、IR 数量、executable / blocked / gap 计数、样例 source trace。
- 明确区分 summoned monster、battle unit summon、servant / 忆灵、assistant、client / scene / adventure summon、catalog ref。
- 每个 gap 都有分层归因。
- 未分类来源数量必须为 0。
- 默认只输出 summary、matrix、少量样例，不写完整 IR。

### 不算完成

- 只统计 `SummonMonster`。
- 把 `SummonUnitData` 全部当作 battle spawn。
- 把 monster catalog ref 当作 runtime trigger。
- 只输出总数，没有 raw -> IR -> RuleBook 链路。

## 6. P3-S1 Summon / Servant / Assistant IR 与 RuleBook 契约补齐

### 目标

保证 runtime 所需的规则事实都已经从 TBGD 投影到 Canonical IR / 数据卡 IR / RuleBook。runtime 不能为了补字段回头读 raw。

### 必须覆盖

- 召唤实体类型、owner/summoner、队伍归属、目标可选性、唯一组、数量上限。
- spawn 触发来源、位置、延迟、初始行动值、初始等级、基础属性来源。
- remove / expire / owner cleanup / wave cleanup 来源。
- servant 属性继承、速度、生命、行动集、技能图、生命周期、owner 绑定。
- assistant actor、stats、ability graph、target、queue priority、attribution policy。
- 召唤物与状态、资源、伤害公式、target expression 的 source trace。
- RuleBook 查询 API 必须能按结构化 key 查到定义、intent、resolution、lifecycle policy 和 action admission。

### 验收结果

- 每类机制能说明 raw 是否存在、IR 是否有字段、RuleBook 是否可查。
- raw 有而 IR 缺的列为 `lowering_gap`。
- IR 有但 RuleBook 查不到的列为 `admission_gap`。
- 所有新增 IR 字段带 source trace。
- blocked / discovered / audit-only 不会被 runtime admission 成 executable。

### 不算完成

- runtime 读取 raw TBGD。
- 用文本、名称或旧 v7 推断规则。
- 用 `engine_convention` 冒充 TBGD 来源。

## 7. P3-S2 summon runtime schema v2 与实体身份统一

### 目标

把 P1 的 `summon_runtime` 提升为稳定契约，能够承载所有召唤实体，而不是只服务最小样例。

### 必须覆盖

- 每个召唤实体的唯一 runtime id、unit id、template/ref、summon kind。
- owner、summoner、team side、source intent、source trace、created / removed event index。
- by owner、by unique group、last summoned monsters、last servants、assistant history。
- targetability、actionability、timeline admission、lifetime、wave clear policy。
- removed 状态必须保留审计记录，不能直接从 registry 中消失。
- runtime view 是纯查询，不能改变 state。

### 验收结果

- 新 schema 有版本号和向前边界说明。
- spawn / remove / owner cleanup 都同步更新 runtime registry。
- replay 能从 mutations 复原 runtime。
- 缺 schema、错 schema、flag-only entity、registry 缺 source trace 全部 blocked。

### 不算完成

- 只靠 `UnitState.flags` 临时拼 target。
- runtime registry 只记录 id，不记录来源和生命周期。
- 移除时删除记录导致审计丢失。

## 8. P3-S3 summoned monster 生成、位置、数量、唯一组和延迟 admission 完整化

### 目标

把当前 `SummonMonster` 最小纵切扩展成完整可依赖的 summoned monster 底座。

### 必须覆盖

- 多 entry、多 count、固定和可证明的位置策略。
- delay / initial action value 规则；动态或未支持 delay 必须 blocked，不能静默忽略。
- monster data card、combatant profile、level、toughness、resistance、status resistance 来源。
- wave clear policy、owner/summoner、summon side、target relation。
- unique group 和数量上限；超过上限时替换、拒绝、移除旧实体必须有来源。
- 重复 unit id、缺 owner、缺 monster card、缺 profile、缺位置来源等负例。

### 验收结果

- 至少一个真实 `SummonMonster` 正例完成 spawn、timeline、runtime、target relation、replay、source audit。
- 每类 unsupported source 都有 blocked / state unchanged 负例。
- 所有 spawn mutation 可追到 intent、entry、monster card、profile、position、delay 来源。

### 不算完成

- 只支持单 entry，却把多 entry 标成 executable。
- 不解析 delay 字段却执行。
- 没有 source trace 的手工 unit spawn。

## 9. P3-S4 battle unit summon / SummonUnitData 来源拆分和 runtime admission

### 目标

解决 `SummonUnitData` 当前只能 boundary-only 的问题：先拆清它到底哪些是 battle runtime，哪些只是 client / scene / adventure / catalog。

### 必须覆盖

- `IsClient`、`DestroyOnEnterBattle`、scene / maze / adventure 标记。
- `SummonUnitData` 与 battle ability / stage / event / monster / avatar 的真实触发链路。
- battle runtime 所需的 unit profile、stats、position、lifetime、targetability、actionability。
- catalog ref 只保留 catalog，不触发 spawn。
- 没有真实 trigger 的 definition 不执行。

### 验收结果

- `SummonUnitDefinitionIR` 分类矩阵中无 unclassified。
- 如果存在 battle runtime 来源，至少一个真实正例能 spawn 并通过 replay / source audit。
- 如果当前数据库没有 battle runtime 来源，必须证明 raw 层来源是 client / scene / adventure / catalog，并以 `source_absent_not_required` 或 `boundary_only` 收口。
- 不能把 P1 smoke 的 hand-written setup 当作来源正例。

### 不算完成

- 看到 `SummonUnitData` 就创建战斗单位。
- 用配置文件名或显示名判断 battle summon。
- 用 BattleSetup synthetic case 冒充 TBGD trigger。

## 10. P3-S5 servant / 忆灵定义、属性、生命周期、owner 关系完整化

### 目标

把 servant / 忆灵从“可生成单位”推进到可稳定参与战斗结算的 owner-bound 召唤实体。

### 必须覆盖

- owner entity ref、servant ref、技能槽位、可执行和 skipped skill 审计。
- HP、速度、攻击、防御、其他战斗属性的来源和继承规则。
- timeline / action value、lifetime、owner death policy、targetability。
- owner mismatch、缺 owner、属性非正数、缺 action set、缺 timeline source 等负例。
- servant 多实例、重复生成、替换或拒绝策略。
- servant 与 owner 的资源、状态、伤害 attribution 边界。

### 验收结果

- 至少一个真实 servant 正例完成 spawn、target registry、action availability、owner cleanup、replay、source audit。
- servant attack / defense 不再只是 schema carry；如果当前缺真实伤害 stat binding 来源，必须明确 blocked，而不能参与 damage formula admission。
- owner death remove 有真实 lifecycle source 时执行；缺 source 时 blocked。
- 所有 servant mutation 可追到 servant definition、stat source、timeline source、lifecycle source。

### 不算完成

- 只生成 servant unit，不验证属性、行动、目标、移除。
- 用 owner 当前面板值直接参与伤害公式但没有来源说明。
- flag-only servant 被 target system 接受。

## 11. P3-S6 召唤单位行动可用性和动作执行链路

### 目标

让 summoned monster 和 servant 在外部推演器控制下可以像普通单位一样查询合法动作并执行，同时保持来源边界。

### 必须覆盖

- action availability 对 summoned monster、servant、普通 ally/enemy 的一致入口。
- action set 来源、ability binding、ability phase/task、target requirement。
- 外部推演器选择 action 后，runtime 执行 action，不做 AI 选招。
- 缺 action source、缺 ability graph、缺 target、资源不足、单位死亡、timeline 不 admitted 等负例。
- summon action 与 queue / timeline / turn lifecycle 的交互。

### 验收结果

- 至少一个 summoned monster 或 servant 的真实 action 正例能进入 action execution，产生 damage/status/resource 等真实 mutation。
- action availability 不靠 side 名称或 flag 单点放行，必须有 runtime entity、action admission、source trace。
- 负例全部 state unchanged。

### 不算完成

- action availability 能显示按钮但 action execution blocked，却标 executable。
- 给 `side="summon"` 默认动作。
- core 内部自动选择召唤物动作。

## 12. P3-S7 assistant ability、assistant queue/window 和执行边界

### 目标

把 assistant 从 boundary-only 推进到真实来源可执行，或严格证明当前数据库缺可执行来源。

### 必须覆盖

- `TurnInsertAssistantAbility` 来源、assistant ability id、owner alias、target alias。
- assistant actor / stats source、ability graph、target resolution、queue priority。
- assistant queue window 与 queue intent / resolution / lifecycle 一致性。
- assistant action attribution：伤害、状态、资源、击杀归因归谁。
- missing actor、missing stats、dynamic ability id、target alias unsupported、priority missing 等负例。

### 验收结果

- 如果存在真实可执行来源，至少一个 assistant queue -> drain -> action/effect 正例通过 replay / source audit。
- 如果不存在，assistant 保持 `source_absent_not_required` 或 `boundary_only`，并证明 raw / IR / RuleBook 分层结果。
- blocked assistant intent 不得生成 executable queue downstream IR。

### 不算完成

- 把 assistant 当成普通 servant 或普通 summon 直接执行。
- 只检查 queue intent，不检查 assistant actor/stats/target/action graph。
- 用固定 ability id 合成正例。

## 13. P3-S8 目标系统中的召唤物 / servant / assistant 关系扩展

### 目标

让目标系统能完整表达召唤物相关目标关系，同时保持“缺 registry / 缺 source 不 fallback”。

### 必须覆盖

- owner、summoner、servant、servant owner、last summon、caster summoned minions。
- summon / servant 与 ally/enemy/team side 的关系。
- targetability 和 dead / removed / untargetable 过滤。
- unique group、adjacent、formation order、random target、fetch / sort 与 summon entity 的交互。
- assistant target alias 和 payload。

### 验收结果

- 召唤物目标相关 alias / operation 矩阵无 unclassified。
- 真实 source-backed 正例覆盖 owner fetch、servant fetch、last summon、summoned minions。
- 缺 registry、flag-only、removed entity、wrong owner、unsupported target operation 全部 blocked。

### 不算完成

- fallback 到 caster 或默认目标。
- 只按 unit side 判断队伍，不读 runtime/team helper。
- removed servant 仍可被 target。

## 14. P3-S9 移除、过期、owner cleanup、死亡、波次切换和清场

### 目标

把召唤实体的生命周期闭环做完整，避免只会生成不会消失。

### 必须覆盖

- 真实 remove / expire / owner death / wave cleanup 来源。
- summoned monster 死亡、servant 死亡、owner 死亡、owner 离场。
- wave clear policy：counts / ignore / blocked。
- battle end / wave transition / setup reset 对 summon runtime 的影响。
- 移除后 target registry、timeline queue、pending queue、status、runtime registry 同步。

### 验收结果

- 至少一个真实 remove 或 owner cleanup 正例产生 `UnitRemove` 和 runtime mutation。
- 缺 remove source 时 blocked，不能复用 spawn source。
- active enemy summon 是否阻塞 wave clear 由真实 policy 决定。
- 移除后 replay、source audit、target negative、queue negative 全部通过。

### 不算完成

- 直接删除 unit，不写 mutation。
- 只更新 `state.units`，不更新 summon runtime。
- owner death 默认清理所有 summon，没有来源。

## 15. P3-S10 状态、资源、伤害、击杀归因与召唤物联动

### 目标

召唤实体必须和 P2 状态底座、伤害底座、资源底座一致工作。

### 必须覆盖

- 召唤物作为状态持有者、施加者、目标。
- servant / summon 的 DoT、控制、免疫、驱散、持续时间 tick。
- 召唤物伤害公式中的攻击、防御、速度、倍率、owner stat binding。
- resource ownership：能量、战技点、特殊资源是否归 owner、summon 或 process-only。
- kill attribution：召唤物伤害击杀、owner attribution、extra turn / trigger 关系。
- 召唤物死亡、owner 死亡、状态清理、queue 清理。

### 验收结果

- 至少一个召唤实体造成伤害或施加状态的正例通过 settlement traceability。
- 击杀归因能区分 actor、owner、source frame。
- 缺 stat binding 或资源归属来源时 blocked，不用默认 owner 兜底。
- P2 状态聚合相关回归不退化。

### 不算完成

- 用普通单位公式硬套 servant，但没有 stat source。
- 召唤物状态不进统一 status lifecycle。
- kill credit 只记 owner，不记具体伤害来源。

## 16. P3-S11 BattleSetup、scenario、外部推演器接口和端到端样例

### 目标

让外部推演器能通过统一入口建立含召唤物的战斗，并查询/执行合法动作。

### 必须覆盖

- BattleSetup initial summoned monster、initial servant、可能的 battle unit summon。
- 初始 timeline、wave、target registry、summon runtime 一致。
- scenario route 中显式选择召唤物或 servant 行动。
- route input 不得绕过 action availability、target admission、queue/window。
- UI / scenario 只能编排和展示，不能提供规则事实。

### 验收结果

- 至少一个端到端 scenario 覆盖：开局 servant 或 summon、目标解析、行动查询、动作执行、mutation、replay、source audit。
- 缺真实来源的 initial summon blocked / state unchanged。
- route 选择不合法召唤物动作时 blocked，不自动改选。

### 不算完成

- 只手写 BattleState，不走 BattleSetup。
- scenario 直接注入规则结果。
- UI 展示路径绕过 runtime admission。

## 17. P3-S12 全来源闭环、聚合验收、报告和交接

### 目标

用一个聚合验证入口证明 P3 召唤物体系达到当前数据库来源闭环，并整理后续阶段可依赖的契约。

### 必须产出

- `validate_p3_summon_assistant_servant_complete.py` 或等价聚合入口。
- 召唤物来源总矩阵。
- summon / servant / assistant 机制分类矩阵。
- 正例样本集。
- blocked / state unchanged 负例样本集。
- source audit 抽样报告。
- replay 抽样报告。
- resource budget 报告。
- P3 最终报告。
- 更新 `CODEX_HANDOFF.md`、`README.md` 和必要入口文档。

### 验收结果

最终 summary 至少包含：

```text
ok=True
p3_summon_substrate_complete=True
p3_summon_sources_classified=True
p3_summon_implementation_missing_count=0
p3_summon_lowering_gap_count=0
p3_summon_admission_gap_count=0
p3_summon_validation_gap_count=0
p3_summon_unclassified_count=0
```

如果当前数据库确实不存在某些战斗 runtime 来源，可以有：

```text
source_absent_not_required_count > 0
boundary_only_count > 0
```

但每一项都必须有 raw / IR / RuleBook 分层证据，不能是脚本漏扫。

### 不算完成

- 聚合 `ok=True`，但还有 hidden blocker。
- 报告只列已支持样例，不列全量缺口。
- 只跑验证脚本，不审代码结构和通用性。
- 没有更新交接文档，导致后续线程继续按旧状态理解。

## 18. 分阶段验证范围

每个步骤都必须有最小验证，不允许无脑全量。

### 必跑最小集

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

每个步骤还必须跑本步骤新增或修改的主验证脚本。

### 直接回归集

- 改召唤 spawn / runtime registry：跑 P1-3 summon、P1-8 battle setup、P1-9 aggregate。
- 改 unit spawn/remove：跑 P1-1 lifecycle。
- 改 wave clear / wave transition：跑 P1-2 wave。
- 改 action availability / summon actor：跑 P1-0 action boundary。
- 改 queue / assistant：跑 P1-5 queue/window、P2-S10 status callback coverage。
- 改 target alias / target operation：跑 P1-6 target、v0_289 target expression。
- 改 status / damage / resource 联动：跑 P2 聚合和相关 P2 子验证。
- 改 BattleSetup / scenario：跑 P1-8 和 P1-9。

### 条件触发集

只有改到共享底座时扩大验证：

- `MutationReducer` / snapshot / replay。
- `RuntimeSourceAuditor` / settlement traceability。
- `TBGDLowering` / Canonical IR schema。
- `ActionExecutor` / ability task execution。
- `TargetSystem` / target expression resolver。
- `QueueSystem` / queue window drain。
- `TimelineSystem` / scheduler。
- `StatusSystem` / DamageSystem。

### 高负载验证

以下脚本默认不作为小改直接回归：

- 全量 TBGD discovery / lowering 大产物脚本。
- 写完整 `CanonicalIR.to_json()` 的脚本。
- 写完整 coverage / fidelity JSON 的脚本。
- `validate_v0_209`。

确实需要跑时必须串行，输出到 `/tmp`，并说明触发原因。

## 19. 执行记录格式

每完成一步，执行线程应更新本文件 checklist，并补一份阶段报告。报告必须包含：

- 本步完成了什么。
- 本步没有完成什么。
- 新增或修正的来源分类。
- 正例来源如何选择，是否结构化选样。
- 负例覆盖哪些 blocked / state unchanged。
- replay / source audit / settlement traceability 结果。
- 运行了哪些验证，为什么没有跑无关验证。
- 是否还有 implementation_missing / lowering_gap / admission_gap / validation_gap。
- 是否影响 P3 总完成口径。

## 20. Checklist

- [ ] P3-S0 召唤物来源全量盘点和术语归一完成。
- [ ] P3-S1 Summon / Servant / Assistant IR 与 RuleBook 契约补齐完成。
- [ ] P3-S2 summon runtime schema v2 与实体身份统一完成。
- [ ] P3-S3 summoned monster 生成、位置、数量、唯一组和延迟 admission 完整化完成。
- [ ] P3-S4 battle unit summon / SummonUnitData 来源拆分和 runtime admission 完成。
- [ ] P3-S5 servant / 忆灵定义、属性、生命周期、owner 关系完整化完成。
- [ ] P3-S6 召唤单位行动可用性和动作执行链路完成。
- [ ] P3-S7 assistant ability、assistant queue/window 和执行边界完成。
- [ ] P3-S8 目标系统中的召唤物 / servant / assistant 关系扩展完成。
- [ ] P3-S9 移除、过期、owner cleanup、死亡、波次切换和清场完成。
- [ ] P3-S10 状态、资源、伤害、击杀归因与召唤物联动完成。
- [ ] P3-S11 BattleSetup、scenario、外部推演器接口和端到端样例完成。
- [ ] P3-S12 全来源闭环、聚合验收、报告和交接完成。

## 21. 第一项执行建议

下一步应先执行 P3-S0，不要直接改 runtime。

P3-S0 的执行层目标是产出一个轻量召唤体系总矩阵，用它回答：

```text
当前数据库里到底有哪些 summoned monster 来源？
有哪些 SummonUnitData / ConfigSummonUnit 来源？
哪些是 combat battle summon，哪些只是 client / scene / adventure / catalog？
有哪些 servant / 忆灵定义和技能？
有哪些 assistant queue / ability 来源？
哪些已经 executable？
哪些是 boundary_only？
哪些是 lowering gap？
哪些是 admission gap？
哪些是 implementation missing？
哪些只是 validation gap？
```

只有这个矩阵可靠，后续才不会再出现“召唤物体系某个大类其实从没接入”的问题。
