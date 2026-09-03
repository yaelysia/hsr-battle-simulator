# P8-S21 当前源码全量聚合、回归与文档收口执行卡

## 执行配置

- 对应问题：P8-I17，最终复核 P8-I01 至 I18。
- 硬前置：P8-S0 至 P8-S20 均已独立验收、勾选并有代码检查点；工作区无未提交实现改动。
- 推荐模型：5.6 Sol。
- 推荐推理等级：`max`。
- 推荐模式：Goal 模式，目标只允许“生成当前源码证据并收口 P8”；发现机制 gap 时停止，不得在聚合阶段补 runtime。
- 选择理由：需要长时间串行全装备 focused 构建、跨阶段证据审计和文档整理；Goal 可持续运行重验证，但必须禁止自动修实现或提交。

## 当前事实与阶段结果

分阶段报告只是证据索引，历史 `ok=true` 和 `/tmp` 产物不能证明当前源码仍正确。S21 必须从当前 source fingerprint、当前代码和当前 Canonical IR 重新生成装备总矩阵，并验证 S0-S20 的报告 schema、代码锚点和关键谓词非空。

完成后，P8-DONE 严格表示：当前 source fingerprint 下全部已发布光锥、普通玩家遗器模板、词条、套装档位和 gameplay ability 都已完成定义、合法实例、装配、runtime、settlement、source audit 和 replay；四类实现 gap 与 unknown gameplay 为零；特殊模式和 non-gameplay 均有逐项分类；希儿示例只是端到端样例，不覆盖其他目录行。聚合发现任何真实 gap 时，产出 blocked 报告并退回责任阶段，不能勾 P8-DONE。

## 本阶段只做

- 读取已验收 S0-S20 报告，验证 schema/version/source fingerprint/code hash/必需 checks 和证据文件真实存在。
- 从当前源码共享一次 focused equipment compilation/RuleBook，重新生成全光锥、遗器模板、主副词条、套装档位和 gameplay family 矩阵。
- 核对分阶段 gap 继承：任何行不得在聚合中被更宽谓词、手写总数或 sample 覆盖。
- 在同一次 final 中通过生产入口复核装备总矩阵、关键负例和 S20 manifest；不逐阶段重跑历史主验证。
- 抽样完成六类全来源反查：光锥静态、光锥动态、主词条、副词条、套装静态、套装动态。
- 由同一 final 通过生产 runner 消费希儿 manifest，并明确标记为 sample；不另起 S20 验证进程。
- 更新 README、架构边界、DOCUMENTATION_INDEX、CODEX_HANDOFF、AGENTS 和最终 checkpoint；归档可丢弃中间报告时保留长期证据索引。
- 记录 P8 明确不做的刷取、背包、UI 布局、自动配装和未来版本增量。

## 本阶段不做

- 不修改 runtime、lowering、assembler 或验证核心逻辑来让 aggregate 变绿。
- 不重新解释/放宽某阶段目标，不把实现 gap 改称 deferred/source gap。
- 不依赖执行线程外历史 `/tmp` 作为唯一证据；聚合产物重新写入新的 `/tmp`。
- 不运行与装备无调用链/数据契约关系的全项目验证。
- 不由执行线程勾总 checklist、提交 Git 或自称 `done`。

## 聚合可信不变量

1. 当前矩阵从 source discovery 得到总集，不能以固定数量、文件名、角色/装备 ID 或历史 summary 构造。
2. S0-S20 每份证据必须当前、结构完整、checks 非空；缺 key、错类型、假 `ok`、陈旧指纹均失败。
3. 已发布 gameplay 要求 executable；`lowering_gap`、`admission_gap`、`implementation_missing`、`validation_gap` 和 unknown 必须为零。
4. `source_gap_blocked` 只有 raw 真缺源才成立；若使已发布装备不完整，仍阻断 P8-DONE。
5. non-gameplay 与 CUSTOM/特殊模式逐项分类，不允许从分母过滤后声称完整。
6. 聚合只验证当前实现，不能含修复分支；发现 gap 返回所属 S 阶段重新计划/实施/验收。
7. 默认产物受资源预算约束，不写完整 Canonical IR、RuleBook 或全 transition。

## 目标与证据映射

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 阶段证据当前 | S0-S20 schema/fingerprint/code anchor/checks 全部有效 | stage evidence manifest |
| 目录完整 | published light cones/templates/affixes/thresholds 与 raw 一一对应 | definition aggregate |
| gameplay 零 gap | 光锥与套装 family 的四类 gap/unknown/blocker 均为零 | gameplay aggregate |
| 特殊分类诚实 | CUSTOM/non-gameplay/source gap 有逐项结构证据 | classification ledger |
| 关键负例不退化 | path mismatch、4+2、2+2、非法词条、partial graph、stale replay 均失败正确 | regression matrix |
| 来源审计闭合 | 六类样本完整 walkback | source audit matrix |
| 端到端可用 | S20 正式纵切 replay 通过且仅标 sample | sample summary |
| 资源合规 | build 次数、RSS/IO、输出大小在预算内，无默认大对象 | resource report |
| 文档一致 | 状态、缺口、边界和下一阶段在长期文档一致 | documentation audit |

## 拟改文件与关键符号

- 新增 `tools/validate_p8_s21_current_source_aggregate.py`：只聚合/验证，不包含生产修复逻辑；同一入口必须提供不构建 RuleBook 的 `--preflight-only`。
- 可新增阶段 evidence manifest builder，复用 P7 已有严格 evidence 读取模式但不复制手写结论。
- `../P8_EQUIPMENT_BUILD_LIGHT_CONE_RELIC_TASK_PLAN.md`：验收线程最终勾选 S21/P8-DONE。
- `README.md`、`ARCHITECTURE_BOUNDARY_CONTRACT.md`、`DOCUMENTATION_INDEX.md`、`CODEX_HANDOFF.md`、根 `AGENTS.md`：更新当前事实和明确剩余边界。
- `live_validation_reports/v8_p8_equipment_build_light_cone_relic_final_checkpoint.md`。

实现线程只能新增 aggregate/report 草稿；checklist 和最终状态更新由验收线程完成。若聚合脚本需要业务逻辑才能计算某行，说明生产/证据边界设计错误，停止。

## 结构化验收谓词

```text
stage_evidence_count_matches_s0_through_s20=true
all_stage_evidence_current=true
empty_or_fake_checks_rejected=true
current_source_inventory_non_empty=true
published_light_cone_definition_gap_count=0
published_relic_template_gap_count=0
main_affix_gap_count=0
sub_affix_gap_count=0
set_threshold_gap_count=0
light_cone_gameplay_gap_count=0
relic_set_gameplay_gap_count=0
unknown_gameplay_count=0
special_modes_fully_classified=true
non_gameplay_rows_have_structured_evidence=true
six_source_walkbacks_complete=true
critical_negative_regressions_pass=true
seele_slice_passes_as_sample=true
aggregate_contains_runtime_fix_logic=false
large_artifacts_written_by_default=false
documentation_state_consistent=true
```

## Gap 与停止条件

- 任一阶段 evidence 失效：先判断代码回归还是报告陈旧；不能在 aggregate 忽略。
- 任一真实定义/gameplay gap 非零：S21 blocked，映射回最早责任阶段并停止；不要在 S21 修代码。
- `source_gap_blocked` 影响已发布装备完整执行：阻断 P8-DONE，除非验收线程确认其为 non-gameplay。
- 重验证资源超过预算：先停止、优化验证复用/输出，不通过跳过检查来降负载。
- 文档与代码状态冲突：修文档事实，但不得用文档改写实现结论。

## 验证命令与资源

S21 是 P8 唯一允许执行 `full` 级验证的阶段，但它不能修改任何生产代码。先运行不构建 RuleBook 的轻量 preflight，检查报告结构、源码/来源指纹、阶段清单和责任映射；preflight 通过后，最终聚合只运行一次：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/hsr_v8_p8_s21_pycache python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 /usr/bin/time -v -o /tmp/hsr_v8_p8_s21_preflight_time_v.txt timeout --signal=TERM 5m python3 -B -m simulator_v8_clean_core.tools.validate_p8_s21_current_source_aggregate --preflight-only --tbgd-root ../../turnbasedgamedata-main --reports-root live_validation_reports --output-dir /tmp/hsr_v8_p8_s21_current_source_aggregate_preflight
PYTHONDONTWRITEBYTECODE=1 /usr/bin/time -v -o /tmp/hsr_v8_p8_s21_final_time_v.txt timeout --signal=TERM 30m ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p8_s21_current_source_aggregate --tbgd-root ../../turnbasedgamedata-main --reports-root live_validation_reports --output-dir /tmp/hsr_v8_p8_s21_current_source_aggregate
git diff --check
```

- preflight 墙钟预算 5 分钟，不得构建 RuleBook；失败时只返回陈旧报告或责任阶段清单，不运行 final。
- final 在一个进程中共享一次 focused equipment compiler/RuleBook，并通过生产 runner 消费 S20 manifest；不得单独重跑 S20 或 P7 聚合，也不得逐阶段重跑 S0-S20。
- final 只允许一次。失败后根据结构化责任映射退回对应阶段；修复完成后重新进入新的 S21 验收轮次，不能在 S21 内边修边反复聚合。
- final 预算：墙钟 30 分钟、峰值 RSS 1.5 GiB；S21 累计验证预算 45 分钟；默认产物不超过 20 MiB。任何一项超限都阻断，不提高限制或省略谓词。
- 只有 UI 文件实际被修改时才追加 UI typecheck/build。`validate_v0_209`、P1-P7 聚合、旧九族组合和完整 IR/RuleBook/transition dump均禁止。
- summary 必须记录读取文件/字节、compiler/RuleBook build 次数、case 数、墙钟、最大 RSS/IO（不可获得时为 `not_measured`）及每个输出大小。

## Ready-for-review 产物

- 当前 source/code fingerprint 的 S0-S20 evidence manifest。
- 全定义、全 gameplay、特殊模式/non-gameplay 和关键负例 aggregate。
- 六类来源 walkback、同进程 S20 sample、关键负例和资源报告。
- 文档更新 diff 与最终 checkpoint 草稿。
- 若有 blocker：准确责任阶段和证据；不得提交“基本完成”。

## 唯一执行清单（仅验收线程可勾）

- [x] S0-S20 证据全部当前、非空、结构有效并绑定当前源码。
- [x] 全光锥、遗器模板、主副词条、套装档位目录与当前 raw 一一闭合。
- [x] 光锥和套装 gameplay 严格零 gap、零 unknown、零 partial graph。
- [x] 特殊模式/non-gameplay/source gap 分类逐项诚实且不从分母静默过滤。
- [x] 六类来源反查、关键负例和希儿 sample 在同一次当前源码 final 中复核通过。
- [x] 聚合无生产修复逻辑，资源预算和默认输出规模合规。
- [x] 长期文档、最终 checkpoint 与代码事实一致。
- [x] 验收线程确认后才允许勾 P8-S21 和 P8-DONE 并提交最终检查点。
