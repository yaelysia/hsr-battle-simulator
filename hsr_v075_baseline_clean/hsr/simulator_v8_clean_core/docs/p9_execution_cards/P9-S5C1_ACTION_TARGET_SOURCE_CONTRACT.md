# P9-S5C1 动作目标来源与类型化契约目录执行卡

## 执行边界

- 前置检查点：P9-S5B `f3a6a91`。
- 本卡是规划/验收重构后的首个实证阶段。
- 只建立动作目标来源和严格契约目录；不改查询、提交、executor 或战斗结果。
- 执行配置：Terra / max 或同等能力；规划裁决已在本卡固定。

## 闭合地图

| 项目 | 权威契约 |
|---|---|
| 完成分母 | 每次生产 lowering 产生的全部 `ActionDefinitionIR` 按 `(action_id, level)` 一对一形成契约结果；P9 当前角色范围另与 S1 source graph 的全部 gameplay action source 对账；每个真实 `TargetInfo` 的全部同级字段逐项分类 |
| 输入权威 | 角色/monster/servant 动作配置中的结构化选择目标字段；已绑定 ability phase 的 target source 只在明确标为动作选择来源时参与，否则仅作为 effect context 留证；不读文本、UI 或伤害结果猜目标 |
| 输出权威 | 独立 `ActionTargetContractIR` 目录及 RuleBook 窄查询；每项只能 `lowered` 或 `blocked` |
| 生产不变量 | 缺模式、缺关系、来源多义、跨 action/level、字段未分类或来源值与规范化结果矛盾时在模型/lowering 边界 fail-closed；blocked 不携带可运行选择契约 |
| 正式调用者 | 本卡只新增 CanonicalIR/RuleBook 目录消费者；现有 `target_policy_for_action` 和 runtime 不读新目录 |
| 后续归属 | 查询、提交、已选目标与 effect impact 边界统一归 S5C2；随机归 S5D；目标筛选依赖的未准入通用条件归 S6；不在当前 S1 角色来源图内的旧版/旁支 action row 归 source scope；真实来源缺失单独列账 |
| 最小证据 | 一个完整动作表分母账本、一个 S1 当前 action-source 对账、每条生产不变量一个最小反例 |

## 已核对事实

- 当前窄构建观测到 10,799 条 action definition，其中 7,219 条弱 `target_relation`
  为 unknown；数量只记录事实，不写成 gate。
- `ActionDefinitionIR` 仍携带弱 `target_mode/target_relation`，`_target_relation_from_action_semantics`
  会用“伤害动作默认敌方”补来源；这种推断不得进入新契约的 lowered 来源。
- S1 source graph 已给出当前非记忆/非欢愉角色的完整 gameplay action-source 分母。
- `DecisionToken` 已绑定 state revision 和 choice revision；本卡不新建重复 query identity。
- 4 条 `SetTeamLockTarget` 是特定角色的 input/client projection，本卡保持
  `projection_only`，不把它们扩展成全局战斗规则。

## 阶段目标

1. 建立递归不可变的动作目标契约，至少保存 action/level 身份、选择方式、候选关系、
   最小/最大数量、重复政策、来源分量、coverage 和 blocked reason。
2. 目标模式只从 raw 枚举或 monster/servant 结构化目标来源解码；未知枚举 blocked。
3. 候选关系只从真实 row/AI/ability target source 唯一解析；禁止按动作名、伤害类型或玩法经验补默认值。
   ability phase 中的 `Caster`、`SkillTargetEntityList` 等效果上下文不能覆盖动作配置的选择目标。
4. 选择基数只由已准入的类型化目标模式语义导出；关系和模式矛盾时整项 blocked。
5. 建立完整、稳定排序、可 JSON round-trip 的目录，并接入 CanonicalIR/RuleBook 窄查询。
6. 生产目录构建不读验收产物、不构建完整 RuleBook 后过滤，不改任何 runtime 行为。
7. 对每个真实 `TargetInfo` 枚举全部同级字段：战斗字段进入严格契约，展示字段只留审计，
   未识别字段阻断整条记录；不得只投影 `TargetType`/`SubTargetType` 后宣称来源完整。

## 明确不做

- 不迁移 `ActionChoice`、`DecisionToken`、`ActionCommand`、scheduler 或 executor。
- 不新增 `target_query_id`，不实现候选查询和提交。
- 不计算 blast/aoe/bounce impact，不修改 RNG。
- 不把 `SetTeamLockTarget` 执行为 BattleState mutation。
- 不删除旧 runtime 字段；新目录在 S5C2 原子迁移前没有 runtime 消费者，不形成双轨行为。

## 验收门

| 审查面 | 只有以下结果才通过 |
|---|---|
| 来源范围 | 输入 action definition 与契约结果按 typed key 一对一；所有真实 `TargetInfo` 同级字段均已分类；S1 当前 action source 无未归属项，且其全部 action/level 契约均为 lowered |
| 生产不变量 | 跨 action/level、多义来源、非法基数、伪 lowered 和 codec 篡改在构造/lowering 边界拒绝 |
| 调用者 | CanonicalIR 和 RuleBook 仅增加目录/窄查询；runtime 对新类型的读取为零 |
| gap 归属 | 每个 blocked 项保留精确来源和原因，严格区分 source scope、source gap、source ambiguity、source decode、S5C2 或 S6，不得使用“后续处理”混合桶 |
| 验证真实性 | 独立 raw/action-source 分母、一个真实 lowered 代表、一个真实 blocked 代表；总门有假值控制探针 |

## 必须负例

- 同 action/level 重复或冲突契约。
- 目标模式、候选关系、基数或 source component 类型错误。
- 用 damage kind、action/character 名或没有 raw 位置的 derived 来源伪装 lowered。
- 用 ability effect target context 伪装 action selection source。
- blocked 携带可运行关系/基数，lowered 缺少必要来源。
- 原始 JSON 可变容器、未知字段、错误 fingerprint 或伪冻结子类绕过边界。
- generic limit 截断动作定义却将目录标记完整。
- 任一真实同级字段未进入分类账本；多目标上限、召唤物限制或筛选结果与来源字段不一致。

## 验证与成本

- 唯一主入口：`validate_p9_s5c1_action_target_source_contract`。
- 一次读取 action 表和一次复用 S1 raw/source graph；完整 CanonicalIR/RuleBook 构建为 0。
- 独立 oracle 直接读 raw identity 和 source graph membership，不调生产契约帮助函数计算期望值。
- 预算：主入口 3 分钟、RSS 700 MiB、evidence 1 MiB、验证代码不超过 700 非空行。
- 必跑：聚焦 `compileall`、主入口、`git diff --check`。只有 CanonicalIR/RuleBook codec 实际改变时才跑一个现行小型 direct。
- 不跑 S5A/S5B 主入口、完整 lowering、runtime、scheduler、replay 或 P1-P8 聚合。

## 唯一执行清单

- [x] 动作目标契约模型和目录严格、不可变且可查询。
- [x] 每个 action definition 恰好形成一个 lowered 或 blocked 契约结果。
- [x] S1 当前 gameplay action source 全部进入结构化责任账本。
- [x] 语义推断、多义、缺来源和矛盾记录均 fail-closed。
- [x] 新目录的 runtime 消费者为零，战斗行为不变。
- [x] 五面验收和资源门通过，报告记录实施/验收/修复轮数。
