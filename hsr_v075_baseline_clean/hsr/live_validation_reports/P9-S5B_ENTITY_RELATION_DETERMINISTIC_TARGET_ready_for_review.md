# P9-S5B 实体关系与确定性效果目标 ready_for_review

## 状态

`ready_for_review`

基于检查点 `12de2ca` 严格实施 P9-S5B。未修改总 Checklist，未提交 Git，未进入 P9-S5C。

## 生产变更

- 新增唯一 `EntityRelationResolver.resolve`，关系结果直接复用 S5A 的
  `TargetExpressionResult(resolved|blocked)`，没有建立平行结果体系或关系索引。
- 新增不可变 `TargetEvaluationContext`。施放者、效果拥有者、参数实体、已选/当前目标及已存在的
  正式事件身份在 11 个生产调用边界显式构造；resolver 不再从自由 event 字典读取关系身份。
- 11 个正式调用边界同时从 committed `BattleState.global_flags.turn_owner_id` 注入当前行动者；缺失、
  非法或未知身份分别在类型化构造/统一 resolver 边界 fail-closed，不再要求调用者手工补值。
- 状态施加者与状态持有者允许跨阵营；上下文身份查询不附加存活/可选性规则。真实
  `ModifierOwnerEntity` 对跨阵营及已死亡 owner 均保持身份解析，生命周期过滤只由来源节点显式请求。
- team、lifecycle、formation 分别读取 committed `UnitState`、`UnitLifecycleSystem` 与正式位置；
  owner/summoner/owned summon 每次先通过 `validate_summon_runtime`，损坏或矛盾索引原子 blocked。
- `TargetSystem.resolve_target_expression` 成为唯一表达式入口。全局 alias 与 operation 从
  S5A `target_source.py` 的严格来源闭包直接进入正式 lowering；未知、循环、歧义或依赖已阻断定义均
  fail-closed。伙伴/唯一单位的无权威全局字典读取已删除，保留 typed producer dependency。
- 角色 ability 文件中的 `GlobalTargetAlias` 以来源文件为作用域，优先解析同文件 alias，再回退全局
  alias；25 条本地定义已并入同一个闭包，没有角色名白名单或第二套运行时注册表。
- `TargetFilterAliveState`、不可选/实体类型过滤、creator/全队映射，以及怪物等级、状态层数/类型、
  护盾、击破增伤和行动序排序已进入 typed lowering 与统一运行时。怪物 rank 权重从 Canonical IR
  写入 committed state，场景输入不能覆盖；波次敌人与战斗中召出的怪物均从同一 Canonical 权重
  映射写入 rank 事实。creator 复用已验证 summon runtime。
- 类型化目标节点构造边界拒绝未知 compute 语义、错误 selector 分支数、非法生命周期掩码、实体
  类型及状态排序字段；运行时不再把非法交集节点当作并集执行。不可选与相邻关系均排除 removed
  单位，但不对普通身份查询附加存活过滤。集合型 team/formation 查询明确区分 selectable、
  defeated 与后台单位；相邻查询同时服从 `UnitLifecycleView.can_be_targeted_alive` 和显式不可选事实。
  `IgnoreServant` 只读取已验证 runtime 的 `servants` 索引，不排除召唤怪物。
- `RuleBook` 一次性建立 292 条目标语言切片；Ability、Status、Effect 与 callback 系统复用各自
  持有的 `TargetSystem`，热路径不再扫描约 25 万条完整目标表达式。
- `ByRandom`、shuffle 与随机 retarget 统一返回 `random_target_pending_s5d`，没有首项 fallback；
  action policy 中仍存在的 owner/summoner 选择规则属于明确禁止修改的 S5C 边界，本卡未触碰。

## 验收证据

唯一主入口：

```text
python3 -m simulator_v8_clean_core.tools.validate_p9_s5b_entity_relation_deterministic_target \
  --output-dir /tmp/hsr_v8_p9_s5b.fix6b.RtdhUj/evidence
```

结果：`ok=true`。

| 执行卡验收项 | 证据 |
|---|---|
| 单一关系入口 | `call_path_audit.json`：1 个 relation 入口、1 个 expression 入口；旧入口、缺 context 调用、平行 helper 均为 0 |
| 权威一致 | `relation_matrix.json`、`negative_cases.json`：召唤镜像冲突、未知身份和缺失队形 fail-closed；跨队及死亡 owner 身份正确 resolved |
| 确定性闭合 | `source_contract.json`：453 条 blocked gameplay 根记录中，S5B 归属 0、未归属 0；随机节点仍明确转交 S5D |
| 集合稳定 | `relation_matrix.json`：重排 `BattleState.units` 结果一致；来源顺序排序、tie breaker、limbo mask 与非有限值负例通过 |
| 空与失败分离 | 普通单位无 owned summon 为 resolved empty；损坏 runtime/未知 operation/越界 index 均 blocked 且目标集合为空 |
| 来源闭包 | 正式 lowering 与 S5A 292 条严格定义 fingerprint 集合完全一致；Cerydra 文件内真实 alias 经正式入口解析，未知 alias 仍 blocked |
| 后续依赖诚实 | `dependency_ledger.json`：671/671 blocked 全量结构化列账；归属来自 typed node、family 和作用域，不再从错误文字推断 |

完成谓词还直接要求：正式当前行动者查询解析为 committed actor、11/11 调用点具备生产者、召唤
怪物出生模板生成 `monster_rank`/`monster_rank_score`、默认与允许不可选的 team 集合不同、defeated
单位不进入不可选/相邻集合、`IgnoreServant` 保留召唤怪物、后台主体在显式准入时可查询队伍。它们
不再由 gap 分类结果自证。

召唤怪物等级证据不再使用 `SimpleNamespace` 或虚构来源。验证按 opcode 形状在 JSON/IR lowering 前
筛选 121 个真实 ability 来源，经正式 standalone ability、summon intent 与 unit birth lowering 得到
516 个模板；其中 15 个真实 executable 模板全部携带来源化 rank 与 score。代表 evidence 保留实际
source path、raw identity 和原始表达式链。集合负例通过 `CommittedStateIntegrityGate.check_full`，
包括正式非空 defeat record；完整性结果为 `passed`、issues 为空。

结构化通过谓词 22 项全部满足。新增生产边界谓词直接覆盖跨阵营 owner、死亡身份、partner/unique
伪造输入、正式事件身份迁移、S5A 闭包复用和热路径窄索引；body-part 计数由正式 projection 的
executable 节点计算，不再写死。

生产调用审计覆盖：

- `systems/ability.py`：1 处。
- `systems/effect.py`：2 处。
- `systems/status.py`：4 处。
- `systems/status_callbacks.py`：4 处。

共 11 处；`missing_context=[]`、`old_entry_calls=[]`。严格上下文构造负例覆盖空 caster、重复身份及
current/selected 矛盾；resolver 负例覆盖未知身份、召唤镜像冲突和重复反向索引。`_condition_context`
持有的正式事件 source/target 已写入 typed context；自由 payload 不能覆盖正式身份。

## Gap 账本

主验证扫描 80 个 ability 来源、16,113 条来源记录和 292 条语言定义。11,826 条 gameplay
效果目标中 11,373 条 executable、453 条 blocked；每条 blocked gameplay 根记录均携带非空、可枚举的
`dependency_stages`，S5B 归属与未归属均为 0：

| 结构化后续依赖组合 | 根记录数 |
|---|---:|
| P9-S9/S17 typed event/entity producer | 317 |
| P9-S6/S7 condition evaluator | 40 |
| P9-S5D RNG + P9-S6/S7 condition | 47 |
| P9-S6/S7 condition + P9-S9/S17 producer | 15 |
| P9-S5D RNG + P9-S9/S17 producer | 14 |
| P9-S5D RNG + condition + event/entity producer | 18 |
| P9-S17 source-language decode | 1 |
| P9-S5C action target selection | 1 |

全部记录及精确 JSON path 位于
`/tmp/hsr_v8_p9_s5b.fix6b.RtdhUj/evidence/dependency_ledger.json`。另外 115 条 blocked 语言定义与
非 gameplay/source-scope 项同样列账，但不冒充 gameplay 完成证据。本卡未伪造 predicate、event 或
body-part gameplay producer。

另做过一次非门禁完整 `TBGDLowering.build()` 诊断，命中检查点既有
`IRIdentityConflictError: entity:entity_id:avatar:1212`。因此依执行卡停止条件改用来源前置过滤的窄投影；
唯一主入口的 `full_canonical_ir_build_count=0`，该既有聚合冲突未被伪装为 S5B 失败或在本卡扩修。

## 资源与固定顺序

- `compileall`：通过。
- 秒级关系负例：通过。
- 唯一主入口：10.428 秒（外层墙钟 10.68 秒）；峰值 601,812 KiB；evidence 170,348 字节。
- necessary direct：0 项；本卡未修改 summon runtime 的公开查询/校验接口，符合执行卡上限。
- `git diff --check`：通过。
- 阶段累计墙钟低于 9 分钟；观测峰值低于 768 MiB；无完整 IR dump。
- 新验证器 700 个非空行，符合 700 行预算。

工作区原有 `ARCHITECTURE_BOUNDARY_CONTRACT.md` 修改、UI HTML 与 UI 任务草稿均保持原样，未混入
本阶段实施范围。
