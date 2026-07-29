# P8-S9 遗器定义卡 ready_for_review

- 状态：`ready_for_review`
- 基线：`61c946fbaf1a00691be8694e42f13f81c122e100`
- 范围：仅 P8-S9；未创建遗器实例，未计算词条，未激活套装，未创建 graph/mechanism ref，未进入 runtime。

## 验收差量修复

- 构建器、正式目录和 RuleBook 共用同一遗器引用闭包校验；缺目标、目标歧义、跨域及正反向关系不一致均 fail-closed。RuleBook 对受影响定义返回 `equipment_definition_reference_closure_invalid`。
- 真实定义按来源表、`raw_type`、记录身份、JSON 位置及来源指纹成员核对；域和主/副词条组统一标记为 `derived`，验证输入统一标记为 `validation_fixture`。
- 光锥与遗器 AbilityList 来源共用同一严格边界：正式记录只允许 `tbgd`，测试只允许显式 `validation_fixture`，`derived` 在构造器及 codec 边界均被拒绝。
- 未知槽位不再回退为 `outer`，对应模板不进入诊断目录；负例直接证明没有生成臆造域。
- Canonical IR 元数据原子拆分为光锥来源、遗器来源、光锥目录、遗器目录四类指纹；已移除误导性的通用装备来源指纹字段。
- reference、source provenance 和未执行边界均由当前对象图实际遍历生成，不再写死缺引用计数或 graph 边界结果。

## 验证治理与代码量

- S9 验证器由 1313 行总计、1260 行非空，精简为 1184 行总计、1125 行非空，分别减少 129 行和 135 行，已低于 1200 行硬上限。
- 精简通过复用正式目录的 `definitions()` / `reference_issues()`、数据化夹具变更、共用 RuleBook 构造和来源反序列化探针完成；21 项契约检查、12 个案例及四类 evidence 均保留在原验证器内，没有迁移到其他文件。
- 当前仍高于 800 行目标；已按执行索引完成结构审查，未用压缩生成代码、删除谓词或搬移 helper 伪造达标。
- 相对基线 `61c946fbaf1a00691be8694e42f13f81c122e100`，生产代码非空差量为 `+4409/-205`，验证代码非空差量为 `+1315/-37`；验证新增量低于生产新增量。统计范围不含执行卡和本报告。

## 当前来源与目录

- 实时来源：6 张遗器表、15 个装备能力文件，共 21 个文件、1,893,153 bytes。
- 来源指纹：`3226efe771227410e8844600a9223bdf9e131126b85aad287ca75fb3f081e314`。
- 能力目录：226 个唯一 AbilityList 身份；六表各一次 Decimal 解析、能力身份索引一次。
- 定义目录：2 域、6 槽、1 个无类型筛选行、29 主词条组、117 主词条、4 副词条组、48 副词条、726 模板、58 套装、90 档位，共 1080 个定义。
- 定义指纹：`e387abc8c732be319bb8997df178708e4de7f87bdba93554c9bcb9f696c61953`。
- 模板：720 `BASIC`、6 `CUSTOM`；726 个 published 模板全部 `lowered`，`blocked=0`。
- 引用闭包：3630 个模板引用、90 个套装档位引用，缺引用和关系问题均为 0。
- 来源类别：1045 个原始 TBGD 定义、35 个派生定义、0 个验证夹具定义进入正式目录。

## 当前最终 evidence

- `/tmp/hsr_v8_p8_s9_relic_definition_cards/p8_s9_source_inventory.json`
- `/tmp/hsr_v8_p8_s9_relic_definition_cards/p8_s9_definition_matrices.json`
- `/tmp/hsr_v8_p8_s9_relic_definition_cards/p8_s9_negative_matrix.json`
- `/tmp/hsr_v8_p8_s9_relic_definition_cards/p8_s9_query_codec_matrix.json`
- `/tmp/hsr_v8_p8_s9_relic_definition_cards/validation_summary_p8_s9_relic_definition_cards.json`

最终 summary 为 `ok=true`、`ready_for_review=true`。12/12 负例与变形用例通过，其中 10 个 fail-closed、2 个变形正例；21/21 RuleBook、codec、来源、闭包及指纹检查通过。派生能力来源的遗器构造器、遗器 codec、套装档位 codec 和光锥共用边界负例均通过，`forged_derived_ability_source_accepted=false`。`equipment_graph_reference_created`、`relic_mechanism_reference_created`、`runtime_mutation_created`、`relic_instance_created` 均由遍历得到 `false`。

## 验证与资源

- 本轮验证治理后仅重建最终主入口 1 次：退出码 0，summary 墙钟 1.632274s，`/usr/bin/time` 墙钟 1.89s，峰值 RSS 63,312 KiB。
- 当前 evidence 共 290,917 bytes；未写完整 Canonical IR、RuleBook、ability payload 或 runtime 产物。
- `compileall` 通过；`git diff --check` 通过。
- S1 共用类型正向查询切片和负向查询切片均通过，且不读取 TBGD。
- 此替代运行覆盖此前 evidence；全阶段五次主入口累计墙钟约 8.02s，低于 15 分钟预算。

## 明确未执行

- 未运行 S0/S1 完整验证器、完整 `TBGDLowering.build`、完整战斗 RuleBook、ability 执行、完整 Canonical IR dump、P1-P8 聚合或 `validate_v0_209`。
- 未更新 checklist，未提交 Git，未进入 P8-S10。
