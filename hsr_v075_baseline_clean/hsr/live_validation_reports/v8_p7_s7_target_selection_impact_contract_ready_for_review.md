# P7-S7 目标选择与影响组契约待验收报告

状态：`ready_for_review=true`。本报告仅作为统一验收的证据索引，不宣告阶段完成，不修改 P7 checklist。

## 本阶段结果

- `TargetResolution` 明确分离 `selectable`、`primary`、`impact_group`；`TargetPlan` 同步保留目标关系、已选主目标和派生影响组，查询结果与执行计划可逐字段对照。
- `ActionDefinitionIR` / `ActionEventIR` 新增结构化 `target_relation`。lowering 从 action/phase 的目标别名结构投影 enemy、ally、self、owner、summoner、summon 等关系；未知关系保持 blocked，不按伤害类型、角色名或技能 ID 猜测。
- `TargetPolicy` 一等声明关系、选择最小/最大基数、影响模式及 off-field 准入。single/blast/bounce 只接受一个显式主目标；aoe 不接受外部注入目标并由策略自动派生影响组。
- 查询和提交共用同一 target enumeration/cardinality/targetability 实现。重复目标、少选、多选、错误关系、败退/移除、不可选、后排以及合法非法混合请求均整体拒绝，不过滤非法项后继续执行。
- blast 相邻目标按阵位和明确关系从主目标派生；aoe 从合法可选集合派生；bounce 只在本阶段固定首个主目标，后续随机跳点仍归 RNG 阶段。
- 全局 dot-chain 目标别名与普通目标表达式收敛到统一 typed-node lowering，移除旧 `normalized/raw` 执行 payload 分支。

## 结构化验证证据

主验证：

```text
python3 -m simulator_v8_clean_core.tools.validate_p7_s7_target_selection_impact_contract --output-dir /tmp/p7_s7_main
```

结果：`ok=true`、`ready_for_review=true`、`rows=6`、`negative_cases=10`。

验证实际覆盖：

- 模式矩阵：single、blast、aoe、bounce；分别检查主目标、自动影响组和选择基数。
- 关系矩阵：enemy、ally、self、ally_or_self、owner、summoner、summon；unknown relation 必须 blocked。
- targetability 负例：defeated、removed、`targetable=false`、off-field、错误阵营；合法与非法目标混合时必须整体失败。
- executor 正例：blast、aoe 均 committed，mutation replay 和 source audit 通过，执行计划中 primary/impact 与目标解析一致。
- executor 负例：single 多选、重复目标、缺主目标、aoe 显式注入、未知关系；全部 blocked、state unchanged、zero mutation、不可作为后继。
- query/submit round trip：查询返回的每个 selectable target 可原样组成命令，提交后的 selectable 集、primary 和 impact group 与同一决策状态契约一致。
- 静态边界：目标关系不从 `damage_kind` 推断；`TargetResolution` 具备三层目标身份；基数和 targetability 共用同一实现。

输出：

- `/tmp/p7_s7_main/validation_summary_p7_s7_target_selection_impact_contract.json`
- `/tmp/p7_s7_main/p7_s7_target_selection_impact_matrix.json`
- `/tmp/p7_s7_main/p7_s7_target_selection_impact_evidence.json`

## 直接回归与资源情况

- `validate_v0_288`：真实 TBGD 目标表达式 core 回归 `ok=true`。
- `validate_v0_289`：首次运行抓到旧 synthetic boundary 仍提交 raw payload；验证迁移为 typed IR 后重跑 `ok=true`。unsupported filter 现在确实穿透到 condition admission 并被拒绝，缺 target 的 retarget 穿透到 retarget payload 检查。
- P7-S1：`ok=true`。
- P7-S3：`ok=true`，9 cases。
- P7-S4：`ok=true`，11 ownership rows。
- P7-S5：`ok=true`，6 rows。
- P7-S6 runtime query/submit 直接调用链：round trip、insert contract、10 个负例和 state-unchanged 谓词均为 true；未重复全量 lowering 来源矩阵。
- `compileall`：通过。
- `git diff --check`：通过。
- 两项真实 TBGD 回归均低优先级串行运行，只写 `/tmp`；未运行已知会默认写约 1.6GB 的 P1-5。

## 明确未做

- 未实现 bounce 后续随机跳点与独立 RNG ledger，归 P7-S12。
- 未实现 scheduler/queue 的决策循环与 drain 前进保证，归 P7-S8。
- 未为 unknown target relation 添加默认敌方 fallback；真实来源未投影的 action 继续 blocked。
- 未修改 P7 checklist，未提交 Git 检查点。
