# P9-S8B6 旧任务拓扑退役与聚合审计验收报告

## 结论

P9-S8B6 已通过验收，P9-S8B 原子任务图事务聚合随之完成。

正式角色 ability 与角色状态 callback 现在只从 S8A 来源控制流物化的任务图读取 root、后继和
分支；正式 task 不再写入旧父子字段，缺图或身份不一致会在首条 mutation 前 blocked。公共 task
模型暂未全局删除旧字段，因为怪物、装备、召唤物、全局及特殊模式内容尚未迁移到 S8A 来源图；
这些依赖由 Canonical IR 在安装正式图目录时重新计算并严格核对，不能被漏记或伪造成正式回退。

## 完成结果

- formal lowering 独立保存 root 账本，task 上四个旧拓扑字段及对应来源 evidence 均为空。
- materializer 直接消费 S8A branch/template child；来源 occurrence 与 owner 图位置分别建模，
  同一 shared template 来源可在不同 owner 位置展开而不被静默合并。
- RuleBook 提供唯一正式图查询，同时闭合 entry、graph、owner、callback 与完整 task 集合。
- action、ability、status callback、status application、damage modifier 和 scenario startup 均已迁移。
- 正式入口先验证完整图身份，再应用启动项等业务选择过滤；过滤结果不能冒充完整图。
- 外部内容继续通过显式 `external_legacy` 或类型化 source mode 使用旧路径；未知 owner、重复 owner、
  缺失来源或不完整依赖账本在 Canonical 构造边界 fail-closed。
- 当前 30 个运行时旧字段读取均位于 15 个明确的外部旧域或 authority-gated 函数，没有正式角色/
  状态 fallback。该允许集合是上限，后续内容域迁移可继续减少至零。

## 五面验收

| 审查面 | 结果 |
|---|---|
| 来源范围 | 正式来源拓扑只来自 S8A；shared template 的来源位置与 owner 图位置双身份闭合，未按固定角色或文件选样 |
| 生产不变量 | formal task 双写为零；任务图 codec 拒绝旧字段；外部 owner 缺失、重复和账本不一致由构造边界拒绝 |
| 正式调用者 | CodeGraph、AST 与逐处代码审查覆盖 core、systems、scenario 和 RuleBook；正式缺图不回退，外部域保持原行为 |
| gap 归属 | 公共字段最终删除归各外部内容来源闭包；projectile、barrier、parallel 和随机顺序仍只归 S8C |
| 验证质量 | 独立 AST 残留账本、双 formal lowering、shared-source 双 owner 探针、strict codec 和外部账本反例；总门显式区分 bool 与 int |

## 验证结果

- 唯一最终主入口 10/10 谓词通过：墙钟 0.92 秒，峰值 RSS 50,444 KiB。
- evidence 共 4,999 bytes；验证器 150 个非空行；完整 Canonical IR build 和历史主入口均为 0。
- 最小 direct 通过：taskless formal callback、正式图查询的 resolved/篡改/空选择、ability/status owner
  图位置篡改拒绝。
- 全包 `compileall` 与 `git diff --check` 通过。
- 开发期曾做一次按来源结构选取的真实单 phase 诊断：12 个 task 全部 materialized，旧字段写入为
  零；该诊断峰值 489,776 KiB，超过本卡 384 MiB 主入口预算，因此只作调查记录，没有冒充最终门。
- 未运行 S8B1-S8B5、完整 lowering、catalog/full 聚合或历史验证器。

最终证据位于：

```text
/tmp/hsr_v8_p9_s8b6_legacy_topology_retirement_final/
/tmp/hsr_v8_p9_s8b6_final_time_v.txt
```

## 实施与流程复盘

本阶段由规划/验收线程直接实施，未派生执行代理；在最终主入口前完成一轮集中生产审查。审查共
发现三类问题：外部伤害路径被正式查询误覆盖、taskless callback 残留未定义变量、owner 图位置未与
lowering 来源 evidence 闭合。三类均在主入口前集中修复，因此最终业务主入口一次通过，验收后没有
新增系统性问题类别。

可复用结论已写入工作流：退役共享字段前先按类型化 producer/consumer 域分类；任何局部选择过滤
必须发生在完整图身份验证之后。来源 occurrence 与 owner 图位置分离的既有规则继续保留。

本验证器验收后标记为 `historical_evidence`。下一阶段唯一入口是
`docs/p9_execution_cards/P9-S8C_HIT_BARRIER_RANDOM_SEQUENCE.md`。
