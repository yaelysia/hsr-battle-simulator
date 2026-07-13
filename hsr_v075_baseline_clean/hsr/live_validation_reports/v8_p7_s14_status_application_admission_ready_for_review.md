# P7-S14 状态施加、抵抗与完整准入待验收报告

状态：`ready_for_review=true`。本报告仅作为统一验收证据索引，不宣告阶段完成，不修改 P7 checklist。

## 本阶段结果

- AddModifier lowering 显式记录 Chance 字段是否存在；省略 Chance 只有在携带 `guaranteed_no_resistance` 及独立 engine-rule source 时才表示必定施加，runtime 不再把“缺字段”无条件猜成普通概率 100%。
- 概率准入按结构化 status config/definition 分类为 positive、guaranteed、debuff、control、special-debuff；unknown 分类和 special resistance 缺 binding 时 blocked。
- 普通减益组合 base chance、效果命中和效果抵抗；控制额外组合通用控制抵抗及具体 control-kind resistance；special-debuff 必须声明 resistance key/source。所有乘项先完整相乘，只在最终概率处 clamp；有限且非负的 base chance 允许超过 100%，并记录 applied/skipped terms。
- 每次需要概率的施加只形成一个 `final_status_application` RNG 决策；不再先判 base chance、再独立判 resist。最终概率为 0/1 时不制造无意义 RNG。
- 结构化免疫在 RNG 前处理；命中免疫时无 Mutation、无 RNG，并保留 immunity source。
- definition 继续只接受 effect 的明确 link 或唯一候选；多候选不会取第一个。duration、stack、refresh、dynamic binding、property、chance classification 任一不完整时，在创建 StatusInstance 前整次 blocked。
- `active_partial` 不再作为 AddModifier 的可提交兜底。unsupported property/动态值/生命周期不会产生状态 Mutation，满足 S3 原子提交前提。
- Chance、叠层、持续时间与驱散数量统一接受类型化 `program` 数值 IR；status runtime 不再维护旧 expression-kind 白名单。Add/Remove/Dispel 与 OnCreate dynamic value 均要求类型化 target expression，旧 target alias 只可作为审计信息。

## 结构化验证证据

主验证：

```text
python3 -m simulator_v8_clean_core.tools.validate_p7_s14_status_application_admission --output-dir /tmp/p7_review2_s14
```

结果：`ok=true`、`ready_for_review=true`、`rows=13`。

实际覆盖：positive、guaranteed、ordinary debuff、control、special-debuff、immunity、unknown classification、omitted semantics 缺来源、definition 多候选、partial no-mutation。新增 `program` IR 同时覆盖 chance/stack/duration/dispel；partial gate 以真实 StatusSystem 结果检查 0 Mutation 和快照不变，不再写死布尔值；旧 target alias 单独验证为 blocked。

输出：

- `/tmp/p7_review2_s14/validation_summary_p7_s14_status_application_admission.json`
- `/tmp/p7_review2_s14/p7_s14_status_application_matrix.json`
- `/tmp/p7_review2_s14/p7_s14_status_application_evidence.json`

## 直接回归与诚实保留的验证迁移

- P7-S3 atomic commit：`ok=true`、9 cases。
- P7-S5 typed expression：`ok=true`、6 rows。
- P2-S5 真实来源状态概率验证已迁移掉“双 RNG”断言，并迁移到 P6 UnitSpawn 出生契约；实际重跑仍未选出可提交 dynamic Chance 正例。结构化诊断显示候选依赖的状态 dynamic values 未由该旧验证提供真实绑定，现被 `status_dynamic_value_unresolved:*` 门阻断。过去的绿灯依赖 `active_partial`；执行线程没有恢复该错误行为，也没有用自造数值填充真实公式参数。
- 该 P2-S5 结果应归为旧验证输入/参数绑定迁移缺口，不表示状态概率 runtime 失败，也不能被 S14 fixture 写成“全 TBGD 状态正例完成”。S19 聚合必须继承并处理这一事实。
- `compileall`、`git diff --check`：通过。

## 明确未做

- 未批量覆盖角色/怪物状态，未用路径 `Advanced`、文本关键词或文件顺序选择 definition。
- 未把控制抵抗等同普通效果抵抗，未为缺 special resistance 来源的状态造可执行正例。
- 未修改 P7 checklist，未提交 Git 检查点。
