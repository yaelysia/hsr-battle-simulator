# P2 状态系统完整覆盖分步计划

本文档是 P2 状态系统阶段的执行计划。它不是 P1-4 的延续清单，而是一个更严格的“完整状态系统覆盖”计划：先把状态底层语义补完整，再把当前 TBGD / Canonical IR 中能发现的全部状态相关来源逐一分类、接入、验证或明确阻断。

## 0. 背景和目标

P1 已经完成，v8 clean core 现在具备外部推演器驱动下的最小完整战斗纵切。P1-4 已经把状态系统底座推进到可用状态，包含状态添加、叠层、刷新、持续时间、过期、DoT tick、概率、效果抵抗、免疫、确定性驱散、控制阻塞行动等第一阶段能力。

但 P1-4 的目标是“第一阶段底座”，不是“所有状态完整覆盖”。现在进入 P2，目标要收紧：

```text
所有状态相关来源都必须被看见、分类、验证。
有真实来源且当前语义可支持的状态必须 executable。
有真实来源但 runtime / lowering / admission 不完整的状态必须进入实现任务。
当前数据库无来源或规则缺失的状态路径必须明确 blocked / source_absent，不允许伪造正例。
```

这里的“所有状态”不是按角色名或怪物名手工补特例，而是按状态系统的结构来源覆盖：

- 所有 modifier / status definition。
- 所有状态施加来源。
- 所有状态移除、驱散、清理来源。
- 所有状态叠层、刷新、持续时间、tick、过期来源。
- 所有状态命中、抵抗、免疫、控制抵抗来源。
- 所有状态监听和回调。
- 所有通过状态影响属性、伤害、行动、目标、队列、资源的路径。

P2 状态系统完成后，后续角色、怪物、光锥、遗器、关卡机制扩面时，不应再发现“状态底座根本没做好”的隐藏缺口。

## 1. 完成定义

P2 状态系统完成必须同时满足以下条件：

- 当前 TBGD / Canonical IR 中的状态相关来源有全量覆盖矩阵。
- 覆盖矩阵中没有 `implementation_missing`、`lowering_gap`、`admission_gap`、`validation_gap` 残留。
- 每一种有真实来源的状态语义都有至少一个结构化正例，能执行、产生 transition、通过 replay 和 source audit。
- 每一种不能执行的状态语义都有明确原因，并证明 blocked / process-only / state unchanged。
- validation 不靠固定角色名、怪物名、技能名、文件名、hash 或观测答案作为主路径。
- runtime 不读取 raw TBGD、TextMap、旧 v7、旧 model pack。
- 状态 mutation 都能反查 settlement，再反查 Canonical IR，再反查 TBGD source path / evidence。
- 默认验证不输出完整 Canonical IR、大体积 coverage 或完整 transition dump；大产物必须显式开关。

任何一个状态来源没有被矩阵看见，或者被看见但分类不清楚，都不能宣称“状态系统做完”。

## 2. 状态分类口径

后续每个状态机制都必须先分层定位：

```text
raw TBGD 是否有结构化来源
lowering 是否投影到 Canonical IR / 数据卡 IR
RuleBook 是否保留 admission 所需字段和 source trace
runtime 是否有通用执行语义
validation 是否能用结构化谓词选到正例或负例
```

分类只能使用以下状态：

- `executable`：有真实来源，runtime 可执行，mutation / settlement / replay / source audit 均通过。
- `source_absent_not_required`：当前数据库没有这种结构化来源，且不属于当前数据库必须执行的状态路径。
- `boundary_only`：当前只需要明确边界，runtime 必须 blocked / process-only / state unchanged。
- `lowering_gap`：raw 有来源，但 lowering 没投影或投影丢字段。
- `admission_gap`：IR 有来源，但 RuleBook 或 admission 谓词不足。
- `validation_gap`：runtime 已支持，但验证脚本选样或断言不足。
- `implementation_missing`：有真实来源，但 runtime 还没有正确执行语义。

不能把检查脚本没扫到直接叫 source gap。必须先证明不是 lowering、admission 或 validation 谓词问题。

## 3. 阶段拆分

P2 状态系统分成 12 个步骤。每一步都要能独立验收，并在完成后更新总矩阵。

```text
P2-S0  状态全量盘点和覆盖矩阵
P2-S1  状态 IR / RuleBook 来源完整性
P2-S2  状态实例、来源、默认生命周期统一
P2-S3  施加、叠层、刷新、替换、共存完整语义
P2-S4  持续时间、tick、过期、跨波清理完整语义
P2-S5  概率、效果抵抗、控制抵抗、免疫完整语义
P2-S6  控制状态对行动、队列、时间线的完整语义
P2-S7  状态数值影响和动态值绑定完整语义
P2-S8  DoT / 状态伤害 / 状态触发伤害完整语义
P2-S9  移除、驱散、净化、不可驱散完整语义
P2-S10 状态回调事件族和任务 opcode 覆盖
P2-S11 全状态来源接入和未覆盖清零
P2-S12 聚合验收、文档收口和 P3 交接
```

## 4. P2-S0 状态全量盘点和覆盖矩阵

### 目标

建立状态系统的总账本。执行层在写任何新 runtime 逻辑前，必须先知道当前数据库里到底有哪些状态、哪些来源、哪些事件、哪些任务、哪些已经可执行、哪些还缺。

### 必须覆盖

- 状态定义：所有 modifier / status definition。
- 状态施加：所有 `AddModifier` 来源。
- 状态移除：所有 `RemoveModifier` / `RemoveSelfModifier` 来源。
- 驱散：所有 `DispelStatus` 来源。
- 生命周期：所有持续时间、tick、过期、清理时点。
- 叠层刷新：所有叠层、减少层数、刷新、替换、共存规则。
- 概率与抵抗：所有命中概率、效果抵抗、控制抵抗、免疫来源。
- 回调：所有状态监听事件和 callback task。
- 数值：所有状态动态值、状态层数读取、状态持续时间读取、属性修改、伤害修改。
- 状态伤害：所有 DoT、状态触发伤害、附加伤害。

### 验收结果

- 新增状态覆盖矩阵输出，至少包含：
  - 状态定义总数。
  - 状态施加来源总数。
  - 状态移除 / 驱散来源总数。
  - 状态回调事件族总数。
  - 各语义 family 的 executable / blocked / gap 计数。
  - 每个 gap 的分层归因。
- 矩阵默认只输出 summary、计数、分类和少量样例，不写完整 IR。
- 如果某个状态机制还没被分类，验证必须失败。

### 不算完成

- 只统计 `AddModifier`，不统计状态定义和回调。
- 只按字段名搜索，不确认 raw -> IR -> RuleBook 链路。
- 只输出总数，没有 gap 归因。

## 5. P2-S1 状态 IR / RuleBook 来源完整性

### 目标

保证状态 runtime 需要的所有规则事实都已经从 TBGD 投影到 Canonical IR / RuleBook。后续 runtime 只能读 IR，不能因为缺字段直接回头读 raw。

### 必须覆盖

- 状态定义中的类型、正负面、控制分类、是否可驱散、行为标记。
- 状态默认持续时间和默认刷新规则。
- 叠层上限、叠层增加/减少、叠层属性。
- 施加概率、效果命中/抵抗相关字段。
- 控制抵抗相关来源。
- 免疫和不可被施加规则。
- 驱散筛选条件、数量、顺序、正负面范围、只驱散可驱散状态。
- 生命周期时点：回合开始、回合结束、行动前后、波次、永久状态。
- callback 事件和任务树来源。
- 状态动态值和公式绑定。

### 验收结果

- 对每一类状态机制，能说明 raw 是否存在、IR 是否有字段、RuleBook 是否可查。
- raw 有而 IR 缺的全部列为 `lowering_gap`，不得进入 runtime 特判。
- IR 有但 RuleBook 查不到的全部列为 `admission_gap`。
- 所有新增 IR 字段必须带 source trace。

### 不算完成

- runtime 为了补字段读取 raw TBGD。
- 用 `engine_convention` 冒充 TBGD 来源。
- 用技能文本或 TextMap 作为 runtime 规则来源。

## 6. P2-S2 状态实例、来源、默认生命周期统一

### 目标

定义所有状态实例的通用身份和默认生命周期规则。用户明确提出：如果文本没有特殊说明，状态默认按刷新回合数处理；能不能叠层看机制和文本解释结果，一般默认不能叠层。runtime 不能读文本，但数据卡/IR admission 必须把这个默认规则表达清楚。

### 必须覆盖

- 同一来源重复施加同一状态时，默认刷新剩余回合数。
- 未声明可叠层时，默认不可叠层。
- 可叠层状态必须有明确叠层规则来源或数据卡解释结果。
- 状态实例必须保留：
  - 持有者。
  - 施加者。
  - 来源 action / effect / callback。
  - 状态定义。
  - 当前层数。
  - 当前持续时间。
  - 刷新策略。
  - 叠层策略。
  - 可驱散和分类信息。
- 同名不同来源状态是否共存、替换或共享实例必须有规则。

### 验收结果

- 重复施加普通状态默认刷新持续时间，不重复制造状态实例。
- 普通不可叠层状态重复施加不会叠层。
- 可叠层状态按真实规则增加、减少、封顶。
- 同名不同来源状态不会互相误删、误刷新或误叠层。
- 负例覆盖缺来源、缺状态定义、缺持有者、缺施加者、目标不存在。

### 不算完成

- 只靠当前 P1 的几个样例通过。
- 默认所有状态都可叠层。
- 默认所有重复施加都替换，不刷新。
- 用状态名字特判刷新或叠层。

## 7. P2-S3 施加、叠层、刷新、替换、共存完整语义

### 目标

把状态施加从“能添加几个状态”提升为完整通用流程。所有状态施加都要经过同一条 admission、mutation、settlement、事件分发和 replay 路径。

### 必须覆盖

- 首次施加。
- 重复施加普通状态。
- 重复施加可叠层状态。
- 叠层达到上限。
- 叠层减少。
- 叠层到 0 移除。
- 刷新持续时间。
- 只叠层不刷新。
- 叠层并刷新持续时间。
- 替换旧状态。
- 多来源共存。
- 施加失败但保留 process record。

### 验收结果

- 每种施加结果都有独立 settlement record，不混成一个笼统 applied。
- 状态成功施加、叠层、刷新、替换、共存都能 replay。
- 所有 mutation 都能 source audit。
- 当前数据库若存在叠层并刷新持续时间的真实来源，必须接成 executable；若矩阵证明 raw 也没有组合来源，则记录 `source_absent_not_required`，不能再靠窄谓词误报。

### 不算完成

- 只有 `AddModifier` 首次添加通过。
- 叠层通过删除再添加模拟。
- 刷新只改了字段但没有 settlement 和 source audit。
- 找不到样例就直接写 source gap，未做 raw / lowering / RuleBook 分层审计。

## 8. P2-S4 持续时间、tick、过期、跨波清理完整语义

### 目标

让所有状态都进入统一生命周期。状态什么时候减少持续时间、什么时候 tick、什么时候过期、什么时候跨波保留或清理，都必须有明确规则。

### 必须覆盖

- 回合开始 tick。
- 回合结束 tick。
- 行动前 tick。
- 行动后 tick。
- 波次开始 / 结束清理。
- 永久状态。
- 按持有者回合减少。
- 按施加者回合减少。
- 按行动次数减少。
- 动态持续时间。
- 到期移除。
- 到期触发回调。
- 目标死亡 / 退场时清理。

### 验收结果

- 每个生命周期时点都有矩阵分类。
- 当前数据库存在真实来源的 tick 时点必须 executable。
- 不同 tick owner 不会互相误触发。
- 状态过期同时清理状态列表和详情。
- 状态过期、清理、跨波移除都有 settlement、replay、source audit。
- 负例覆盖非持有者 tick、已死亡单位、已移除单位、缺持续时间、缺 tick source。

### 不算完成

- 只支持 P1 已覆盖的两个时点。
- tick 只在 scheduler 某条路径里生效，queue 或 wave 路径漏掉。
- 过期只删状态名，不删详情。
- 跨波清理用硬编码清空全部状态。

## 9. P2-S5 概率、效果抵抗、控制抵抗、免疫完整语义

### 目标

把状态命中判定做成完整可回放分支。状态命中、效果抵抗、控制抵抗、免疫是不同机制，不能混成一个“没命中”。

### 必须覆盖

- 基础概率。
- 效果命中。
- 效果抵抗。
- 控制抵抗。
- 状态免疫。
- 控制免疫。
- 负面状态免疫。
- 特定状态免疫。
- 必中状态。
- 不走抵抗的特殊状态。
- 成功、失败、抵抗、免疫四类结算。

### 验收结果

- 命中公式和抵抗公式来源明确。
- 控制抵抗与效果抵抗分开计算和记录。
- 每次随机判定都有 RNG event 或显式 deterministic choice。
- 同输入 + 同 choice replay 结果一致。
- 失败、抵抗、免疫不产生状态 mutation。
- 结算中能看出失败原因，不只写 skipped。

### 不算完成

- 把控制抵抗当成效果抵抗。
- 没有公式来源时用手写默认公式。
- 直接调用随机数，不记录 RNG event。
- 失败分支不记录 settlement。

## 10. P2-S6 控制状态对行动、队列、时间线的完整语义

### 目标

控制状态只做规则化 gating，不做敌方 AI。它要准确告诉外部推演器：这个单位现在能不能行动、队列能不能执行、时间线如何处理、被阻塞的来源是什么。

### 必须覆盖

- 冻结、禁锢、纠缠、眩晕、怒噪、支配、无法行动等控制类状态。
- 普通行动不可用。
- 终结技窗口不可用或可用的规则。
- 已入队行动的阻塞、跳过或保留。
- 额外行动和反击在控制下的处理。
- 控制解除后的行动资格恢复。
- 控制导致行动跳过、延后、行动值变化的来源。
- 控制状态与死亡 / 退场 / 波次切换的交互。

### 验收结果

- action availability 能列出控制来源。
- scheduler 和 queue preflight 复用同一控制判断。
- 控制状态不能被普通 route command 绕过。
- 控制相关 process event、blocked reason、source trace 完整。
- 控制解除后状态恢复可验证。
- 当前数据库中每类控制状态都被矩阵分类。

### 不算完成

- 只验证一个 synthetic freeze。
- 根据状态名字符串推断控制。
- action availability 阻塞了，但 executor 仍可直接执行。
- queue 路径和普通 action 路径判断不一致。

## 11. P2-S7 状态数值影响和动态值绑定完整语义

### 目标

状态不仅是挂在单位身上的标签，还会影响属性、伤害、速度、能量、韧性、资源、公式变量。P2 必须把状态数值影响纳入统一绑定和审计。

### 必须覆盖

- 状态层数读取。
- 状态剩余时间读取。
- 状态动态值定义、设置、累加。
- 按状态修改攻击、防御、速度、暴击、增伤、减伤、击破、效果命中、效果抵抗等面板。
- 按状态修改伤害公式。
- 按状态修改治疗、护盾、能量、战技点、韧性。
- 状态数值随叠层、刷新、过期、移除实时更新。

### 验收结果

- 所有数值绑定来源能追到状态实例和 IR。
- 状态变化后，公式读取的是最新状态。
- 状态移除后，数值影响消失。
- 多状态叠加顺序和聚合规则有明确来源或 engine convention 标注。
- 缺公式、缺绑定、unsupported modifier value 时 blocked，不使用默认值。

### 不算完成

- 只支持 `Layer` 读取。
- 状态移除后数值仍残留。
- 用角色特判实现某个状态增伤。
- 公式失败时默认当 0 或 1 执行。

## 12. P2-S8 DoT / 状态伤害 / 状态触发伤害完整语义

### 目标

把 DoT 和状态触发伤害纳入状态生命周期，而不是独立的伤害特例。状态伤害要有来源、tick 时点、快照规则、归因、目标规则和失败分支。

### 必须覆盖

- 持续伤害 tick。
- 击破 DoT。
- 普通状态 DoT。
- 状态触发的附加伤害。
- 状态引发的生命损失。
- 状态伤害多段。
- 状态伤害目标死亡跳过。
- 状态伤害击杀归因。
- 状态伤害触发后续事件。
- 状态伤害与叠层、动态值、持续时间的关系。

### 验收结果

- 每类状态伤害都有真实来源正例或明确 gap。
- DoT tick 先后顺序与生命周期一致。
- 状态伤害 mutation 的 source frame 能区分施加者、持有者、状态来源。
- replay/source audit/settlement 通过。
- 负例覆盖目标死亡、来源状态已过期、公式缺失、目标不可选。

### 不算完成

- 只跑一个 DoT 样例。
- 状态伤害直接调用普通伤害但丢失状态来源。
- tick 顺序和 duration 减少顺序不固定。

## 13. P2-S9 移除、驱散、净化、不可驱散完整语义

### 目标

把状态离场做完整。主动移除、到期移除、驱散、净化、死亡清理、波次清理、不可驱散都必须走统一语义。

### 必须覆盖

- 按状态名移除。
- 按实例移除。
- 自身移除。
- 到期移除。
- 死亡 / 退场清理。
- 波次清理。
- 驱散正面状态。
- 驱散负面状态。
- 驱散控制状态。
- 驱散多个状态。
- 按最后添加顺序驱散。
- 按规则筛选候选。
- 不可驱散状态跳过。
- 没有候选时 process-only。

### 验收结果

- 每种移除原因都有明确 settlement。
- 移除状态同时清理列表、详情、动态值、事件监听、数值影响。
- 驱散候选选择可审计。
- 当前数据库若没有随机驱散，则矩阵记录无来源；不能实现 synthetic random dispel 正例。
- 多数量驱散和动态数量驱散有真实来源正例或明确 blocked。

### 不算完成

- 只支持 fixed count=1。
- 按状态名误删同名不同来源实例。
- 不可驱散状态被驱散。
- 无候选时静默成功。

## 14. P2-S10 状态回调事件族和任务 opcode 覆盖

### 目标

让状态回调成为通用机制入口。所有状态事件和 callback task 要么 executable，要么有明确 blocked 原因，不能在执行中静默跳过。

### 必须覆盖

- 创建、销毁、叠层、刷新、tick、受击、攻击、造成伤害、击杀、回合开始、回合结束、行动前后、波次、状态添加/移除等事件。
- callback 条件判断。
- callback 目标解析。
- callback 中的 AddModifier / RemoveModifier / DispelStatus。
- callback 中的动态值读写。
- callback 中的队列插入。
- callback 中的行动延迟 / 行动值变化。
- callback 中的状态伤害。
- unsupported opcode 的完整 blocked 记录。

### 验收结果

- 状态事件族矩阵覆盖所有当前事件。
- 每个 executable callback 有真实事件源和 payload。
- 缺事件源、缺 payload、缺条件、缺目标、unsupported task 时 blocked/state unchanged。
- 不允许 unknown opcode 被跳过后仍标 supported。
- callback 产生的 mutation 都能 source audit。

### 不算完成

- 只支持 P1 已用到的 OnPhase1 / OnAfterBeingAttacked。
- callback task 不支持时只写日志。
- 缺 payload 时 fallback 到 caster 或默认目标。

## 15. P2-S11 全状态来源接入和未覆盖清零

### 目标

这是“所有状态”的核心验收步骤。前面步骤补底层，P2-S11 要拿全量状态来源矩阵回扫当前数据库，清掉所有未分类和实现缺口。

### 必须覆盖

- Avatar 来源状态。
- Monster 来源状态。
- Equipment / light cone / relic 来源状态。
- Battle event / stage 来源状态。
- Global modifier 来源状态。
- Servant / summon 相关状态。
- UI 或文本只作为展示，不作为规则来源。

### 验收结果

- 全量状态矩阵中没有未分类来源。
- `implementation_missing` 为 0。
- `lowering_gap` 为 0，或每一项都有独立后续 issue / plan 且不能宣称状态系统完成。
- `admission_gap` 为 0，或每一项都有独立后续 issue / plan 且不能宣称状态系统完成。
- `validation_gap` 为 0。
- 所有 `source_absent_not_required` 都有 raw 层证明，不是脚本没扫到。
- 所有 blocked 项都有 state unchanged 验证。

### 不算完成

- 只看 P1 选出来的样例。
- 只覆盖角色，不覆盖怪物 / stage / global modifier。
- 只覆盖 AddModifier，不覆盖 callback 和移除。
- 矩阵里还有 unknown / not_touched / discovered_only 但宣称完成。

## 16. P2-S12 聚合验收、文档收口和 P3 交接

### 目标

用一个状态系统聚合验收入口证明 P2 状态系统完成，并把文档整理成后续角色、怪物、装备扩面能直接依赖的状态系统契约。

### 必须产出

- `validate_p2_status_system_complete.py` 或等价聚合验证入口。
- 状态总覆盖矩阵。
- 状态机制分类矩阵。
- 状态正例样本集。
- 状态负例样本集。
- source audit 抽样报告。
- replay 抽样报告。
- resource budget 报告。
- P2 状态系统最终报告。
- 更新 `CODEX_HANDOFF.md` 和必要入口文档。

### 验收结果

最终 summary 必须至少包含：

```text
ok=True
p2_status_substrate_complete=True
p2_all_status_sources_classified=True
p2_status_implementation_missing_count=0
p2_status_lowering_gap_count=0
p2_status_admission_gap_count=0
p2_status_validation_gap_count=0
p2_status_unclassified_count=0
```

如果当前数据库确实不存在某些机制来源，可以有：

```text
source_absent_not_required_count > 0
```

但每一项都必须有 raw / IR / RuleBook 分层证据，不能是脚本漏扫。

### 不算完成

- 聚合 `ok=True`，但还有 hidden blocker。
- 报告只列已支持样例，不列全量缺口。
- 只跑验证脚本，不审代码结构和通用性。
- 没有更新交接文档，导致后续线程继续按旧状态理解。

## 17. 分阶段验证范围

每个步骤都必须有最小验证，不允许执行线程每次无脑跑全量。

### 必跑最小集

所有步骤都跑：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

每个步骤还必须跑本步骤新增或修改的主验证脚本。

### 直接回归集

- 改状态施加、移除、生命周期：跑 P1-4 状态验证。
- 改 action availability 或控制：跑 P1-0 action boundary。
- 改 unit death/remove 清理：跑 P1-1 lifecycle。
- 改 wave cleanup：跑 P1-2 wave。
- 改 summon/servant 状态交互：跑 P1-3 summon/servant。
- 改 queue / callback 插入：跑 P1-5 queue/window。
- 改 target resolution：跑 P1-6 target。
- 改 RNG choice：跑 P1-7 RNG。
- 改 BattleSetup initial status：跑 P1-8 setup。
- 改聚合矩阵：跑 P1-9 aggregate。

### 条件触发集

只有改到共享底座时扩大验证：

- `MutationReducer` / snapshot / replay。
- `RuntimeSourceAuditor` / settlement traceability。
- `DamageSystem` / damage source frame。
- `EventDispatchSystem` / callback event family。
- `RuleEvaluator` / formula binding。
- `TBGDLowering` / Canonical IR schema。

### 高负载验证

以下脚本默认不作为小改直接回归：

- 全量 TBGD discovery / lowering 大产物脚本。
- 写完整 `CanonicalIR.to_json()` 的脚本。
- 写完整 coverage / fidelity JSON 的脚本。
- `validate_v0_209`。

确实需要跑时必须串行，输出到 `/tmp`，并说明触发原因。

## 18. 执行记录格式

每完成一步，执行线程应更新本文件对应 checklist，并补一份阶段报告。报告必须包含：

- 本步完成了什么。
- 本步没有完成什么。
- 新增或修正的来源分类。
- 正例来源如何选择，是否结构化选样。
- 负例覆盖哪些 blocked / state unchanged。
- replay / source audit 结果。
- 运行了哪些验证，为什么没有跑无关验证。
- 是否还有 implementation_missing。
- 是否影响 P2 总完成口径。

## 19. Checklist

- [x] P2-S0 状态全量盘点和覆盖矩阵完成。
- [x] P2-S1 状态 IR / RuleBook 来源完整性完成。
- [x] P2-S2 状态实例、来源、默认生命周期统一完成。
- [ ] P2-S3 施加、叠层、刷新、替换、共存完整语义完成。
- [ ] P2-S4 持续时间、tick、过期、跨波清理完整语义完成。
- [ ] P2-S5 概率、效果抵抗、控制抵抗、免疫完整语义完成。
- [ ] P2-S6 控制状态对行动、队列、时间线的完整语义完成。
- [ ] P2-S7 状态数值影响和动态值绑定完整语义完成。
- [ ] P2-S8 DoT / 状态伤害 / 状态触发伤害完整语义完成。
- [ ] P2-S9 移除、驱散、净化、不可驱散完整语义完成。
- [ ] P2-S10 状态回调事件族和任务 opcode 覆盖完成。
- [ ] P2-S11 全状态来源接入和未覆盖清零完成。
- [ ] P2-S12 聚合验收、文档收口和 P3 交接完成。

## 20. 第一项执行建议

下一步应先执行 P2-S0，不要直接改 runtime。

P2-S0 的执行层目标是产出一个轻量状态总矩阵，用它回答：

```text
当前数据库里到底有多少状态定义？
有多少状态施加来源？
有多少移除和驱散来源？
有多少状态回调和事件？
哪些已经 executable？
哪些是 source absent？
哪些是 lowering gap？
哪些是 admission gap？
哪些是 implementation missing？
哪些只是 validation gap？
```

只有这个矩阵可靠，后续才不会再出现“某个状态系统缺口到最后才突然冒出来”的情况。
