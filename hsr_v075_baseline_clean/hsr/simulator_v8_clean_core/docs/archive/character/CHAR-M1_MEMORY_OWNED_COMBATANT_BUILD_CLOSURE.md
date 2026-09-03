# CHAR-M1 记忆角色与忆灵构筑闭环执行卡

## 执行配置

- 任务归属：角色卡 / 角色构筑轨，不属于 P8-S8。
- 推荐模型：5.6 Sol。
- 推荐推理等级：`max`。
- 推荐模式：Goal 模式，Goal 只覆盖本卡，不自动推进光锥、遗器或其他角色扩面。
- 并行约束：从已验收检查点建立独立 worktree；同一工作区内不得与装备轨并行修改共享文件。

## 前因后果

P8-S2 建立正式角色构筑时，遇到了一类不能归到角色本体技能的默认行迹节点：节点提升的是角色拥有的忆灵技能。当前装配器只会在角色本体动作集合中解析技能等级，因此把这类真实来源统一保留为：

```text
auxiliary_unit_skill_level_requires_owned_combatant_build
```

这一阻断当时是诚实的，因为系统尚没有“角色构筑同时装配其所属派生战斗单位”的类型化结果。但它不能成为永久边界。当前已经存在 `ServantDefinitionIR`、召唤生命周期、owner 关系和部分 servant 行动底座；缺少的是把这些事实接入角色构筑，并让忆灵自己的属性、技能等级、动作和特殊资源由自己的定义承接。

本任务只关闭这一角色构筑职责缺口。光锥机制不会在这里实现；P8-S8 只会把受影响目录项记录为外部角色构筑依赖，直到本任务完成。

## 阶段目标

完成后，正式角色构筑不再把忆灵技能当作角色本体技能，也不再仅用一条诊断跳过它。角色构筑会生成一个可审计的 owner 构筑结果，以及零个或多个由该角色真实拥有的派生战斗单位构筑结果。每个忆灵拥有独立身份、属性来源、有效技能等级、动作集合、机制引用、owner 关系和生命周期准入状态。

对于当前数据中带有忆灵技能升级节点的已发布角色：

- 每个辅助技能必须唯一解析到该角色真实拥有的 `ServantDefinitionIR` 或其类型化后继模型。
- 默认解锁、行迹升级和星魂加级必须作用到正确的忆灵技能，不能进入角色本体技能集合，也不能重复计入。
- 角色和忆灵的构筑结果必须分别可重算、可追溯、递归不可变，并由父构筑结果显式关联。
- 角色正式入战前必须检查派生战斗单位构筑；任何来源、技能、动作、属性或特殊资源未闭合时保持 blocked。
- 构筑成功不等于无条件开局生成忆灵。是否出生、何时出生、移除与替换必须继续由真实召唤 / 生命周期来源决定。

本阶段完成的是记忆角色的 owned-combatant 构筑与入战边界，不宣称所有记忆角色的每个战斗机制、文本效果和数值分支已经全量复刻。

## 本阶段只做

1. 全量审计当前已发布角色中的辅助技能节点、角色到 servant 的所有权来源、`AvatarServantConfig`、servant 技能表、动作定义、能力绑定、属性来源和特殊资源来源。
2. 回正角色本体、忆灵定义和玩家构筑实例之间的类型化关系；复用并完善现有 `ServantDefinitionIR`，不另造一套重复召唤物规则。
3. 为角色构筑结果增加独立的 owned-combatant 装配通道，使每个派生单位拥有自己的构筑结果和 fingerprint。
4. 将辅助技能等级解析迁移到所属派生单位；原有诊断仅在真实来源仍无法唯一闭合时保留。
5. 补齐当前记忆角色构筑实际需要的特殊资源定义与初始状态投影；不得默认成普通能量或补零。
6. 让 scenario / `UnitState` 只消费已准入的装配结果和机制引用；出生、行动、移除、owner 清理继续走通用 summon、timeline、action 和 lifecycle 系统。
7. 用当前源码证明至少一个真实记忆角色可完成正式空装备构筑并进入场景，同时对当前全部受影响角色输出逐项结果和剩余阻断归属。

## 本阶段不做

- 不修改光锥或遗器规则，不把本任务重新编号为 P8-S8 子阶段。
- 不把忆灵技能、属性或生命周期复制进角色本体卡。
- 不假定所有忆灵都在战斗开局生成，也不为验证强制生成。
- 不实现敌方 AI、外部推演器策略或 UI 编辑器。
- 不为了让全部角色显示 admitted 而忽略尚未闭合的角色专属能力；不相关缺口必须单列，不能吞掉。
- 不全量制作所有角色卡；只处理当前 owned-combatant 构筑边界及其真实直接依赖。

## 设计不变量

1. **身份分离**：角色卡身份、servant 定义身份、运行时单位身份和构筑实例身份不得复用同一个字段表达。
2. **所有权来自数据**：角色到忆灵的关联必须由当前 TBGD 结构化来源建立；禁止按命途名称、角色名、固定角色 ID 或技能 ID 推断。
3. **技能归属唯一**：一个技能等级只能归到一个 combatant；同一逻辑技能的默认等级、行迹和星魂来源按既有规则合并，不能同时出现在 owner 与 servant。
4. **定义与实例分离**：`ServantDefinitionIR` 描述来源事实，owned-combatant 构筑结果描述本次角色构筑选择；runtime 不读取 raw 表或重新计算构筑。
5. **出生与构筑分离**：构筑结果可以存在而运行时单位尚未出生；只有真实 spawn intent / setup / ability 才能创建单位。
6. **原子准入**：父角色要进入正式战斗时，所有必需的派生单位构筑都必须完整；子构筑 blocked 时父构筑不得静默忽略。
7. **无第二套内核**：忆灵的动作、目标、伤害、状态、资源、时间线和 RNG 必须复用通用系统。
8. **来源审计完整**：派生单位的每项属性、技能等级、动作引用和资源定义都能反查到 Canonical IR，再回到真实 TBGD 行或能力记录。

## 详细完成要求与验收证据

| 目标 | 允许通过的条件 | 不允许通过的情况 | 证据 |
|---|---|---|---|
| 来源目录闭合 | 当前所有辅助技能节点和 owner-servant 关系均被结构化发现、唯一关联并保留来源 | 只抽一个角色；按 Memory 名称或固定 ID 建表 | source inventory |
| 类型化子构筑 | 父构筑结果明确包含独立、不可变的派生单位装配结果及稳定 fingerprint | 把 servant 内容塞进任意字典、flags 或角色面板 | model round-trip / immutability matrix |
| 技能等级正确归属 | 默认节点、行迹和星魂加级在正确 servant 动作定义上恰好生效一次 | owner 与 servant 双计；找不到动作时取第一个或补默认等级 | skill ownership oracle |
| 特殊资源诚实 | 当前直接阻断记忆构筑的特殊资源有类型化来源、初值和 runtime slot；未知来源保持 blocked | 当作普通能量、补 0、从文本猜值 | resource source matrix |
| servant 定义可用 | 所需属性、动作集合、能力绑定、timeline 和 lifecycle 引用均唯一且可查询 | `action_set` 只有字符串声明；缺图仍标 executable | servant assembly matrix |
| 父子准入原子 | 必需子构筑失败时父构筑 blocked 且无可入战结果；全部闭合后父构筑 admitted | 忽略子诊断后让角色入战 | admission negative matrix |
| scenario 边界正确 | scenario 只接收构筑结果；未有出生来源时不生成忆灵，有真实来源时通过通用 spawn 创建并绑定 owner | scenario 手填 servant 最终面板；正式模式隐式 fallback | scenario / lifecycle matrix |
| 行动闭环 | 出生后的真实 servant 能通过通用动作查询得到 source-backed 动作与目标，并至少完成一条当前已准入动作 transition | 专用忆灵按钮或直接 mutation；动作图缺失仍算完成 | action query / transition sample |
| 回归闭合 | 普通非记忆角色构筑结果不变；既有召唤、时间线、source audit 和 replay 不回退 | 为记忆角色特判公共装配器导致其他命途变化 | focused regressions |

## 必须覆盖的负例

- 角色没有 servant 所有权来源，却引用辅助技能。
- 同一辅助技能可匹配多个 servant，或一个 servant 可匹配多个冲突动作定义。
- 辅助技能被同时写入角色本体和 servant 的有效技能等级。
- 默认节点被显式重复选择，或默认等级与行迹加级重复计算。
- servant 定义属于另一个角色。
- servant 属性、动作、能力图、特殊资源或生命周期来源缺失 / 重复 / 冲突。
- 子构筑 blocked，但父构筑被篡改为 admitted。
- 构筑输入或来源容器在创建后修改，导致 fingerprint 或结果变化。
- 没有 spawn 来源却在场景初始化时自动生成忆灵。
- runtime 尝试读取 `AvatarServantConfig`、技能表或角色文本。
- 验证使用固定角色 ID、servant ID、技能 ID 或观测答案作为主选择条件。

## 拟改范围

实际文件以只读审计为准，预期触达：

- `rules/ir.py`、`rules/rulebook.py`：owner-servant 类型化关系和窄查询。
- `tbgd/character_cards.py`、`tbgd/lowering.py`：辅助技能、servant 动作 / 能力 / 资源来源投影。
- `builds/models.py`、`builds/character_assembler.py`：owned-combatant 输入、结果、技能等级归属和父子准入。
- `scenarios/build_state.py`：只消费已准入结果，保持构筑与出生分离。
- `systems/summon.py`、`systems/action_availability.py`：仅修真实调用链暴露的通用缺口。
- 新增聚焦验证器和 `ready_for_review` 报告。

若审计发现需要新增全新核心概念，或现有 `ServantDefinitionIR` 无法在不保留双轨的情况下演进，执行线程必须先暂停并提交修订执行卡，不得自行并存两套模型。

## 结构化验收谓词

```text
affected_auxiliary_skill_nodes_all_classified=true
owner_servant_relations_unique_and_source_backed=true
owner_and_servant_build_identities_distinct=true
owned_combatant_results_recursively_immutable=true
auxiliary_skill_levels_resolve_to_owned_combatant=true
auxiliary_skill_level_double_application_count=0
required_special_resources_typed_and_source_backed=true
required_servant_definitions_assembled=true
parent_child_battle_admission_atomic=true
missing_spawn_source_does_not_spawn=true
source_backed_spawn_preserves_owner_relation=true
spawned_servant_has_queryable_source_backed_action=true
representative_servant_transition_committed=true
representative_mutations_source_audited=true
representative_transition_replay_equal=true
fixed_character_or_servant_id_count=0
runtime_raw_tbgd_read_count=0
non_memory_character_build_regression=true
memory_path_has_formal_admitted_character_build=true
```

`memory_path_has_formal_admitted_character_build=true` 只能由结构化选出的真实角色构筑证明，不能用 kernel fixture、手填 panel、跳过默认节点或跨命途替代角色完成。

## 验证与资源限制

先新增一个聚焦验证器，一次构建当前角色 / servant 所需的最小 RuleBook，并复用内存结果。默认只写 summary、source matrix、skill ownership matrix、admission negatives 和少量 transition / replay 样本。

必跑最小集：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_memory_owned_combatant_build_closure --tbgd-root ../turnbasedgamedata-main --output-dir /tmp/hsr_v8_memory_owned_combatant_build_closure
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/hsr_v8_memory_pycache python3 -m compileall -q hsr/simulator_v8_clean_core
git diff --check
```

聚焦验证绿后，按实际调用链串行选择直接回归：

```text
P8-S2 角色构筑与基础面板
P3 servant 生命周期 / 动作 / 状态资源伤害中被本次实际触达的专项
P6 unit birth / spawn 边界
P7 action query、timeline、source audit / replay 中被本次实际触达的专项
P8-S8 catalog startup matrix 的定向调用，仅证明外部角色依赖已关闭
```

禁止默认运行 P1-P8 聚合、`validate_v0_209`、完整 Canonical IR 序列化或全量 transition dump。所有重验证低优先级、严格串行；如聚焦验证已等价覆盖某旧脚本，应在报告中写明替代谓词，不重复消耗资源。

## 交付边界

执行线程最终只能提交 `ready_for_review`，不得修改 P8-S8 checklist、P8 总 checklist 或自称完成。报告必须分别列出：

- owned-combatant 构筑已经关闭的缺口；
- 当前仍属于角色完整机制扩面的缺口；
- 对 P8 光锥目录启动的影响；
- 实际运行和明确未运行的验证。

## 唯一执行清单（仅验收线程可勾）

- [x] 当前辅助技能、owner-servant、servant 动作 / 属性 / 资源来源目录完整且无固定身份选择。
- [x] 父角色与派生战斗单位形成独立、不可变、可追溯的构筑结果。
- [x] 默认行迹、行迹升级和星魂加级在正确 combatant 上恰好生效一次。
- [x] 当前记忆构筑所需特殊资源和 servant 定义闭合，缺失时 fail-closed。
- [x] 父子 battle admission 原子，至少一个真实记忆角色正式空装备构筑 admitted。
- [x] 构筑与出生分离；真实出生后 owner、生命周期、动作查询和代表 transition 闭合。
- [x] 负例、source audit、replay 和直接回归通过，资源使用符合限制。
- [x] `ready_for_review` 证据包完整，未修改 P8 checklist，未提交 Git。
