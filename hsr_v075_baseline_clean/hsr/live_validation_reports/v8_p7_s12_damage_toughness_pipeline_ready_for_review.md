# P7-S12 统一伤害与削韧结算管线待验收报告

状态：`ready_for_review=true`。本报告仅作为统一验收证据索引，不宣告阶段完成，不修改 P7 checklist。

## 本阶段结果

- 新增 `DamageStagePipeline` 与按伤害家族声明的阶段矩阵。direct、DoT、break、super-break、true、hp-loss、toughness 不再共享一个含义模糊的 `amount` 路径；producer base、各阶段输入/输出与 final amount 分别记录。
- DoT、break、super-break 生产器只提交 `family_base`，true/hp-loss 只提交 `fixed_final`；阶段声明缺失或不匹配时 blocked、无 Mutation。没有为单一卡、技能或观测答案加入常数。
- direct 保留既有 `DirectDamageFormula` 计算入口，但其 ledger 被投影为同一阶段 schema；非 direct 家族通过共享 `status_modifier_terms` 合同读取状态实例中的增伤、易伤、防御、抗性、减伤、击破与削韧乘区，不强行套用 direct 的暴击阶段，也不只读取单位 resource。
- damage/toughness settlement 同时记录 `producer_base_amount`、pipeline、`applied_terms` 与 `skipped_terms`。每个不适用/无来源项都保留结构化跳过原因。
- before-hit 后才采集本次伤害 modifier；before-toughness-calculation 在形成削韧 Mutation 前派发，事件提交后的快照会被重新读取。因此前置事件可以影响当前 hit，但不会事后修改已经计算的 Mutation。
- `DamageSourceFrame`、sequence/target/owner、击杀归因、多段记录和 replay 路径保持；hp loss 明确不进入普通护盾吸收，本阶段没有提前实现 S13。
- 防御与抗性公式已收敛到 `engine_rule_registry` 的类型化 `DamageFormulaRuleIR`，包含规则编号、注册表版本、适用范围、运算和参数；direct 与非 direct 共用同一求值器。生产 `DamageSystem/ToughnessSystem` 从 RuleBook 的 Canonical IR 取得规则，缺规则时 blocked、0 Mutation。

## 结构化验证证据

主验证：

```text
python3 -m simulator_v8_clean_core.tools.validate_p7_s12_damage_toughness_pipeline --output-dir /tmp/p7_review2_s12
```

结果：`ok=true`、`ready_for_review=true`、`rows=12`。

验证实际覆盖：

- direct、DoT、break、super-break、hp-loss、toughness 六类 producer/stage/final 正例；另覆盖 true 固定最终值路径。
- 防御、抗性、易伤、减伤的 applied 与 skipped ledger；不适用家族有明确 `not_applicable_to_family`。
- 100 点 DoT 在状态实例提供 100% 增伤时得到 200 点最终值，且 ledger 明确记录该状态 term；这同时防止“状态有行为但账本未记录”的回归。
- before-hit 修改攻击侧状态后，本 hit 读取新值；before-toughness 修改目标/攻击侧相关状态后，本次削韧读取新快照。
- amount stage 缺失/错误时 blocked、0 Mutation、state unchanged。
- source frame、kill attribution、multi-hit identity、Mutation replay 与 settlement 字段一致。
- 版本化规则正例确认 defense/resistance bucket 记录真实规则身份；删除 Canonical IR 规则的负例结构化阻断且状态不变；两套 runtime 中原先重复的公式常数已移除。

输出：

- `/tmp/p7_review2_s12/validation_summary_p7_s12_damage_toughness_pipeline.json`
- `/tmp/p7_review2_s12/p7_s12_damage_toughness_matrix.json`
- `/tmp/p7_review2_s12/p7_s12_damage_toughness_evidence.json`

## 真实来源直接回归与已诚实保留的边界

- P2-S8 状态伤害真实来源重验证：普通 DoT 与 true damage 子矩阵通过，DoT 基础量进入共享防御阶段后得到 final amount；source audit、replay、transition 均通过。
- 同一 P2-S8 汇总仍为 `ok=false`：继承的 multi-DoT validation gap 与当前数据库扫描下 break executable 正例计数为 0。该结果没有被主验证 fixture 覆盖或改写成“全真实来源正例完成”。
- P6-S1 旧验证当前不能选出完整可信 action 正例：结构扫描发现 4198 个含 damage+toughness emission 的来源候选，但其 selected ability graph 均含未投影/unsupported task，S3 可信图门全部正确 blocked，0 damage/toughness Mutation。执行线程没有放宽 S3，也没有把“来源节点存在”等同于“完整动作可提交”；该验证需要在 P7-S19 按新的可信图口径迁移为来源入口证据与完整图准入证据两层。
- P7-S3、S9、S10、S11 直接回归通过。
- `compileall`、`git diff --check`：通过。
- 未运行 `validate_v0_209`：轻量家族矩阵、P2 真实来源子矩阵与直接回归已经覆盖本次 schema 风险；该脚本会进行不必要的全量高负荷序列化。

## 明确未做

- 未批量解释角色专属附加伤害，未伪造当前无完整可信执行图的 TBGD 正例。
- 未把 hp loss 当普通伤害，也未提前实现护盾实例路由。
- 未修改 P7 checklist，未提交 Git 检查点。
