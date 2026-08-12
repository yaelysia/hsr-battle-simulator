# P9-S8B2 通用原子任务图执行器验收报告

## 结论

P9-S8B2 已通过验收。当前阶段建立了单一领域中立任务图执行器和严格 hook 协议；没有迁移
ability、status、scheduler、event dispatcher 或其他正式领域消费者，也没有宣称真实角色动作已执行。

最终权威证据：

```text
/tmp/hsr_v8_p9_s8b2_atomic_executor_core_final_203c6ac/
validation_summary_p9_s8b2_atomic_executor_core.json
```

## 完成范围

- S8B1 图是唯一控制权威；执行器不读取 raw、S8A catalog、RuleBook 或旧 task payload。
- hook request 不含 child ID/runner；leaf 只返回正式通道，候选状态由现有 reducer 唯一产生。
- 有序路径、布尔/多 case 分支、固定循环、有限进度条件循环、目标循环、template frame 和嵌套图
  调用使用同一执行协议。
- template 参数 sequence 只在对应 fetch 节点执行，不会在 include 时预执行。
- active graph stack 使用图身份检测直接/间接调用环，不设置任意业务深度上限。
- 每个执行投影同时携带 graph、node、formal task 和 invocation path 身份。
- 任一选中节点失败返回原入口对象，正式 mutation/event/RNG/settlement 全空；未选 deferred 分支
  不参与预阻断。

## 五面验收

1. 输入范围：本阶段没有来源分母；只消费 S8B1 已准入图，`source_scan_count=0`。
2. 生产不变量：resolved/blocked 结果、递归不可变、重复通道身份、settlement 链接、reducer 重放、
   图环和进度证明均由生产构造或执行边界裁决。
3. 正式调用者：差量仅新增执行器及系统导出，ability/status 等消费域保持未修改。
4. gap 归属：ability/standalone 归 S8B3，status callback 归 S8B4，跨入口运输归 S8B5，随机、
   projectile、parallel 和 barrier 归 S8C。
5. 验证质量：一个明确标注的 validation fixture 入口，未构建 Canonical IR/RuleBook/战斗世界；
   每个控制结构只保留一个最小证据，业务总门使用精确 bool/int 语义。

## 最终验证

```text
P9-S8B2 focused: 15/15 predicates, ok=true
wall clock: 0.006134 s
peak RSS: 78,912 KiB
evidence: 1,266 bytes
validator nonblank lines: 390
source scan: 0
full Canonical IR build: 0
compileall: pass
git diff --check: pass
```

## 候选证据与流程复盘

- 首次命令在导入阶段失败：验证器引用了错误模块中的数值 lowering；未进入业务执行。
- 第一份候选绿结果经代码审查发现同 leaf 重复 event/RNG 身份会延后抛异常，以及空投影成功结果
  构造边界过宽，已作废。
- 第二份候选绿结果经控制流审查发现“唯一 child 分支即无条件分支”的错误推断，已作废。
- 最终运行在精确分支匹配、统一字段类型矩阵和重复身份反例补齐后生成，是唯一 accepted evidence。

流程已增加三条约束：新验证先做 import-only smoke；新协议先审 resolved/blocked 字段矩阵；分支
语义不得由 child 数量推断。验证器原 250 行估算无法容纳严格 S8B1 fixture，实施前调整为 390 行
目标、400 行硬上限，没有拆隐藏 helper 或压缩为不可维护格式。

本验证器验收后冻结为 `historical_evidence`。S8B3 不重跑本主入口，只对正式 ability 消费链保留
一个现行聚焦门。
