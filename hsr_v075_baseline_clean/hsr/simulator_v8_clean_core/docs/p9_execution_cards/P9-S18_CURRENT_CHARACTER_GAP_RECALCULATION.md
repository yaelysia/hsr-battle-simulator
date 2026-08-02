# P9-S18 当前角色机制差距重算与代表清单执行卡

## 执行配置

- 对应问题：P9-I18；机制包 M18 审计。
- 硬前置：P9-S17 已验收并形成检查点；S0 的范围目录和窄投影接口仍是当前生产入口。
- 推荐：5.6 Terra / `xhigh` / Goal 模式。
- 理由：本阶段以结构化目录核对、差距归因和确定性选样为主，不应修改复杂战斗语义。

## 当前事实与阶段结果

P9 的施工范围是当前已发布、非记忆、非欢愉的 79 条角色记录，以及一份共享角色能力。
S0-S17 分别关闭共享来源、构筑、执行语言和领域消费者，但阶段通过不能自动证明当前完整
角色目录已经归零，也不能靠预先指定若干角色代表全部来源组合。

完成后，当前来源会得到一份由生产窄投影重新计算的逐角色、逐来源、逐机制差距矩阵。
所有来源项只能落入总计划允许的状态；四类内部 gap 必须为零，否则本阶段阻断并退回责任
阶段。与此同时，根据仍需正式战斗证明的“机制组合义务”生成一份稳定的代表 manifest，供
S19 唯一消费。代表数量由当前事实决定，不预设人数，也不按角色知名度挑选。

## 详细目标

1. 从 S0 的当前范围查询重新发现 79 条目标角色和共享能力；禁止复用历史固定数量、旧报告
   或人工角色白名单作为目录事实。
2. 为每条动作、被动、独立能力、行迹和星魂重算完整链路状态：真实来源、来源图绑定、最终
   构筑绑定、typed family、条件/事件契约、runtime 消费者、正式生产者和战斗准入。
3. 每个 gap 必须归到唯一责任阶段和唯一根因；一个来源被多个角色引用时以共享根因归并，
   同时保留所有受影响角色，不能用 blocked 次数膨胀工程量。
4. 四类内部 gap `lowering_gap`、`admission_gap`、`implementation_missing`、`validation_gap`
   必须分别统计且为零。发现非零项时只生成阻断报告，不在 S18 修改生产机制。
5. `source_gap_blocked` 必须具备来源搜索范围、候选结果、为何无法唯一证明及受影响入口；不能
   因扫描器没找到、命名混淆或 lowering 漏接而误判成 source gap。
6. `non_gameplay` 必须回到 S0 的完整分支分类证据；`external_content_dependency` 必须证明
   当前 79 条角色没有真实生产者，且消费者属于未来命途、怪物或关卡内容。
7. 建立“正式战斗证明义务”：至少区分来源形状、机制族、条件上下文、事件生产窗口、领域
   消费者、RNG 形状、生命周期和 replay 要求。义务是机制组合，不是抽象职业或角色定位。
8. 用确定性集合覆盖算法选择最少但足够的真实角色入口。每项义务至少有一个真实来源覆盖；
   同分时按稳定来源身份排序，输入顺序变化不得改变结果。
9. 生成小型、版本化的代表 manifest。固定角色 ID 只允许存在于该明确标记的最终示例文件，
   每个选择必须说明覆盖哪些义务、使用哪个动作/行迹/星魂入口及所需战斗前置。
10. 真实 source gap 不能被伪造成 executable 代表；应在 manifest 中形成 blocked 审计样例，
    用于 S19 证明拒绝和 state unchanged。

## 代表 manifest 契约

建议产物：

```text
simulator_v8_clean_core/examples/p9_character_representative_manifest.json
```

manifest 至少保存：

- 当前来源完整指纹、S18 目录指纹和选择算法版本。
- 每个 proof obligation 的稳定身份、来源类别和预期结论。
- 每个代表入口的角色卡、构筑选择、动作或机制入口，以及覆盖义务列表。
- 需要的合法场景前置类别，例如目标关系、资源、状态、队列或生命阶段；不保存手工结果。
- source gap 审计项及其受影响角色；不保存伪造动作、mutation 或事件 payload。

manifest 不得保存最终面板、预期伤害常数、手工行动值、硬编码 RNG 结果或第二套执行规则。

## 本阶段不做

- 不修 lowering、admission、runtime、事件生产者或领域消费者。
- 不建立角色逐个 handler，不实现记忆或欢愉专属机制。
- 不运行正式战斗纵切，不用样例结果替代目录审计。
- 不为了减少代表数量合并语义不同的义务，不为了预算只保留容易执行的角色。

## 目标与证据

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 当前目录完整 | 目标角色和共享能力与当前范围查询一一对应 | catalog identity matrix |
| 链路重算完整 | 每个来源入口均经过来源、绑定、准入、生产者和消费者核对 | per-entry closure ledger |
| 内部 gap 归零 | 四类内部 gap 均为 0 | gap summary + responsibility matrix |
| source gap 诚实 | 每项均有穷尽搜索和受影响入口 | source-gap dossiers |
| 代表选择充分 | 所有 proof obligation 至少被一个正式或 blocked 样例覆盖 | set-cover matrix |
| 选择确定性 | 输入重排不改变 manifest 和 fingerprint | metamorphic sample |
| 职责隔离 | 本阶段没有生产机制修复 | diff scope audit |

## 结构化通过谓词

```text
current_target_character_catalog_complete=true
shared_character_ability_catalog_complete=true
every_gameplay_entry_has_unique_closure_status=true
lowering_gap_count=0
admission_gap_count=0
implementation_missing_count=0
validation_gap_count=0
source_gap_has_exhaustive_evidence=true
non_gameplay_reuses_scope_classification=true
external_dependency_has_no_current_producer=true
representative_obligation_coverage_complete=true
representative_selection_deterministic=true
fixed_character_ids_outside_manifest=0
production_mechanism_changed=false
```

## 关键负例与停止条件

- 缺失、损坏或来源指纹陈旧的 S17 evidence 必须阻断，不得把旧成功当当前事实。
- 任一当前目录项未出现在矩阵、重复身份、错误命途范围或共享能力重复展开，必须阻断。
- 将扫描失败误报 source gap、将实现缺口改名 deferred、将 `not_proven` 当通过，必须阻断。
- 人工固定角色白名单、按名称选样、先选角色再声明义务，必须阻断。
- manifest 中存在未被覆盖义务、伪造 gameplay 前置或手工预期结果，必须阻断。
- 四类内部 gap 任一非零时，状态为 `blocked`；报告责任阶段后停止，不得提交完成态
  `ready_for_review`。

## 拟改范围

- 当前角色窄目录审计与差距归因工具；优先复用 S0-S17 生产查询，不复制 lowering。
- 新增 `tools/validate_p9_s18_current_character_gap_recalculation.py`。
- 新增代表 manifest 及 S18 `ready_for_review` 报告。
- 除修复纯审计代码错误外，不修改 compiler、IR、RuleBook、assembler、runtime 或 scenario。

## 验证与资源

- 当前窄目录只构建一次；family、角色和来源过滤在投影前生效。
- 允许一个小型输入重排探针验证确定性，不重复构建完整目录。
- 不执行角色战斗场景，不重跑 S0-S17 阶段验证。
- 不输出完整 Canonical IR、RuleBook、raw ability 或角色能力图。
- 预算：主入口 12 分钟、累计 15 分钟、1 GiB、10 MiB、900 非空验证行。
- `compileall`、唯一 S18 主验证、`git diff --check`；没有生产改动时不跑 direct。

## 唯一执行清单

- [ ] 当前 79 条角色和共享能力目录身份完整且范围正确。
- [ ] 每个 gameplay 入口的完整链路状态已重算并唯一归因。
- [ ] 四类内部 gap 为零，source gap 与外部内容依赖证据诚实。
- [ ] 所有正式战斗证明义务已经穷尽生成。
- [ ] 代表 manifest 由确定性集合覆盖生成且无遗漏义务。
- [ ] 主验证、资源和范围审计通过并提交 `ready_for_review`。
