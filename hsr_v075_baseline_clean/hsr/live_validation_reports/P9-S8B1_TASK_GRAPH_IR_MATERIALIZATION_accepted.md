# P9-S8B1 任务图 IR 与物化账本验收报告

## 结论

P9-S8B1 已通过验收。当前阶段只建立来源真实、递归不可变的任务图数据权威、物化账本和唯一查询；
没有改变 runtime，也没有提前迁移 ability、status callback 或跨入口执行链。

最终权威证据：

```text
/tmp/hsr_v8_p9_s8b1_task_graph_ir_materialization_accepted_846b8b6/
validation_summary_p9_s8b1_task_graph_ir_materialization.json
```

## 完成范围

- 继承 S8A-R1 的 10,113 条完整来源责任记录，不按固定角色、文件或任务 ID 选取生产分母。
- 来源 occurrence、正式图位置和图内容使用分离稳定身份；重复出现不会覆盖，内容冲突会阻断。
- 分支拓扑、数值引用、模板引用、循环终止、来源 family 和外部领域责任均进入类型化模型。
- 只有纯任务图责任且控制角色已知的节点可物化；未知角色和仍含外部责任的节点 fail-closed。
- Canonical IR 和 RuleBook 支持完整来源目录、正式多 entry 目录、结构化 blocked 查询和唯一 resolved 查询。
- 完整来源 snapshot 必须来自类型化生产对象；来源文件摘要、行位置及来源 occurrence 可反查。

## 五面验收

1. 来源范围：独立分母与生产目录均为 10,113 条，截断目录不能伪装完整目录。
2. 生产不变量：模型递归不可变，嵌套内容参与 fingerprint；孤立图、悬空引用、错误来源、错误
   owner、未知角色、伪造 lowered 状态和冲突多 entry 均在构造或安装边界拒绝。
3. 正式调用者：Canonical IR、lowering 和 RuleBook 已迁移；runtime 消费者明确留给 S8B2-S8B5。
4. gap 归属：执行器归 S8B2，ability 目录与消费者归 S8B3，status callback 归 S8B4，跨入口运输
   归 S8B5，旧拓扑退役归 S8B6，barrier/parallel/random 归 S8C。
5. 验证质量：验证器使用独立来源分母和动态真实 action slice；未构建完整 Canonical IR，未用
   固定 ID、伪来源或 `all([])` 证明完成。

## 验证结果

```text
P9-S8B1 focused: 10/10 predicates, ok=true
source responsibility records: 10,113
wall clock: 24.227 s
peak RSS: 512,348 KiB
evidence: 1,183 bytes
validator nonblank lines: 350
full Canonical IR build: 0
compileall: pass
git diff --check: pass
```

S8A 修订后的独立 direct 同步通过：约 7.10 秒、峰值 335,836 KiB、完整 Canonical IR build 为 0。

## 候选证据作废说明

实施期间曾出现多份候选绿结果，随后五面审查发现循环终止、来源文件摘要、普通叶节点来源 family、
外部多领域责任、blocked 查询语义和目录身份覆盖不足。这些候选结果全部作废，只有上列 accepted
目录是本阶段权威证据。另一次失败来自 S8A 修正后旧验证归属预期未同步，不是业务回退。

## 流程反哺

- 上游目录身份必须散列完整规范化嵌套内容，不能只散列记录 ID。
- 最小单图纵切只能证明模型语义，不能证明正式多图目录。S8B3 必须一次构建来源索引、流式物化
  多个 entry，并只合并一次完整来源账本。
- 来源责任必须保留多领域集合；未知控制角色不得默认解释为可执行顺序节点。
- 后续主验证前增加对象基数预检，避免“完整来源账本 × 图数量”的隐性复制。

本验证器验收后冻结为 `historical_evidence`。S8B2 不重跑本阶段主入口；只有 S8B3 正式多 entry
目录集成直接触达该契约时，运行其自身的现行聚焦门。
