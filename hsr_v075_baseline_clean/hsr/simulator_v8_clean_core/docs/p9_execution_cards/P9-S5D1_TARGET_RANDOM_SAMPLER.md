# P9-S5D1 目标随机抽样基础契约执行卡

## 执行配置

- 对应问题：P9-I06 的随机目标基础部分。
- 硬前置：S5C2 已验收；若检查点因环境权限暂不可写，必须存在 accepted 报告且生产差量未漂移。
- 推荐：5.6 Sol / `xhigh` / 普通聚焦。
- 本卡只建立一个可供目标表达式和动作弹射复用的随机抽样权威，不接 executor。

## 阶段目标

完成后，目标随机不再由 `TargetShuffle`、`Retarget` 或弹射各自拼接 `RNGRequest`。生产代码
提供一个严格、不可变、来源绑定的目标随机计划与抽样器，明确支持：

1. 单次调用从候选池选择一个目标；不同调用有不同 invocation 身份，允许再次选中同一目标。
2. 同一次调用内无放回抽取若干目标，供随机 Retarget 按上限截取。
3. 同一次调用内生成完整随机排列，供 `TargetShuffle` 使用。

候选池先由 S5B 的确定性目标系统解析。随机器不查单位关系、不解释目标语言、不决定动作
影响范围，只消费已经解析的稳定候选身份。

## 闭合地图

- 权威分母：S5A 窄投影中 `Retarget.ByRandom=true`、`TargetShuffle` 和
  `RandomSelectInTargetList` 的当前来源记录。
- 输入权威：严格目标随机计划，包含来源节点、求值上下文、调用身份、规范候选池、抽取模式和数量。
- 输出权威：`resolved` 或 `blocked` 的抽样结果；resolved 才能携带选择和正式 RNG event。
- 正式调用者：本卡只迁移目标表达式中的随机 Retarget 与 TargetShuffle；弹射和
  RandomSelect 任务入口在 S5D2 迁移。
- 后续 owner：能力图是否真正执行 Retarget 任务属于 S8；本卡不得用验证器代替该生产者。

## 已确定语义

### 候选与身份

- 候选必须是稳定、无重复、非空字符串身份；随机器内部按规范排序计算原始池 fingerprint。
- 无放回每一 draw 都重新计算 remaining-pool fingerprint。
- choice identity 必须绑定来源节点、求值上下文、invocation、原始池、remaining pool、draw index
  和总 draw 数。上述任一项改变，旧 choice 失效，即使旧目标仍在池中。
- 公开构造器拒绝重复候选、可变嵌套、未知模式、越界数量和伪造 fingerprint。

### 抽样模式

- `single`：空池 blocked；单元素直接 resolved 且不耗 RNG；多元素只抽一次。
- `sample_without_replacement`：空池 resolved empty；请求数大于池大小时截到池大小；负数、bool、
  非整数 blocked；每次 draw 从 remaining pool 选择。
- `shuffle`：返回完整排列；空池和单元素池不耗 RNG。
- 显式 ledger 缺当前 choice 时，只公布第一个未解决 request；不得发布已完成的部分 RNG event。
- 全部 choice 解决后才返回正式 event 序列。deterministic 模式复用同一计划和 draw identity。

### 目标表达式接线

- `Retarget.ByRandom`：先执行真实 target/predicate/lifecycle 解析，再无放回排序，最后按 `MaxNumber`
  截取；上限大于池大小不阻断。
- `TargetShuffle`：对输入候选返回完整排列，不退化成单选。
- 两者只调用共享抽样器，不维护私有 RNG 日志或备用确定性排序。

## 生产不变量

1. blocked 结果没有选择和 RNG event；不正确状态在随机计划构造或 resolve 边界立即失败。
2. event 中的候选、remaining、draw 和来源与 request identity 可互相重算。
3. event 顺序与 draw 顺序一致，event ID 和 choice key 从同一 identity 生成。
4. RNG event 只表示真实分支；零/单候选不创建伪事件。
5. 目标表达式只能使用正式节点来源，不接受验证器伪造的 executable 来源。

## 验收标准

| 目标 | 通过条件 | 权威证据 |
|---|---|---|
| 三模式语义 | single、无放回、shuffle 的空/单/多候选行为均符合上述定义 | sampler matrix |
| 身份闭合 | 池、remaining、draw、上下文、invocation、来源任一变化都会改变 key | identity mutation slice |
| 显式选择 | 仅公布首个未解 request，部分选择不产生正式 event | explicit-ledger slice |
| 表达式迁移 | Retarget 与 Shuffle 使用同一 sampler，完整排列和 cap 正确 | target expression slice |
| 来源覆盖 | 三类来源全部分类，D1 负责的表达式来源没有内部 gap | source ledger |
| 调用者闭合 | 不存在旧随机 helper 或第二套 expression RNG 入口 | CodeGraph consumer audit |

## 必须覆盖的最小负例

- 重复或空候选身份、伪造池 fingerprint、非法模式、负数/bool 数量。
- 候选增加/删除、remaining 变化、draw 交换、invocation 或来源改变后复用旧 choice。
- 第二个 draw 缺 choice 时返回第一个正式 event。
- shuffle 漏项、重复项或只返回一个元素。
- Retarget 上限大于池大小被阻断，或缺失动态绑定被静默当默认值。
- blocked 目标表达式仍创建 RNG request。

## 明确不做与停止条件

- 不迁移 executor 弹射，不执行 `RandomSelectInTargetList` 任务，不改 action transaction。
- 不实现概率条件、随机控制流、随机数值或 AI。
- 不重跑 S5A-S5C 主验证，不构建完整 Canonical IR。
- 若真实来源显示带权抽样或第四种战斗语义，提交 `plan_mismatch`。
- 若必须改变全部非目标 RNG 的 replay 语义才能完成，提交影响分析并暂停。

## 拟改范围

- 新增 `systems/target_random.py`。
- 最小修改 `systems/target.py` 与 `systems/__init__.py`。
- 仅在现有通用 RNG 类型无法承载严格身份时最小修改 `systems/rng.py`。
- 新增唯一验证器和仓库级报告。

## 验证预算

- 顺序：`compileall -> 秒级构造负例 -> 唯一主入口 -> 最多一个 RNG direct -> git diff --check`。
- 主入口 4 分钟，累计 7 分钟，RSS 640 MiB，evidence 1 MiB，验证器 520 非空行。
- 来源窄投影只构建一次；完整 lowering 和完整 RuleBook 构建次数必须为 0。

## 唯一执行清单

- [x] 严格目标随机计划、结果和共享 sampler 已建立。
- [x] 三种抽样模式及确定性边界符合来源语义。
- [x] choice identity 完整绑定池、remaining、draw、上下文、invocation 和来源。
- [x] Retarget 与 TargetShuffle 已迁移且无旧随机入口。
- [x] D1 负责来源无内部 gap，后续生产者依赖归属明确。
- [x] 主验证、必要 direct、资源和调用者审计通过。
