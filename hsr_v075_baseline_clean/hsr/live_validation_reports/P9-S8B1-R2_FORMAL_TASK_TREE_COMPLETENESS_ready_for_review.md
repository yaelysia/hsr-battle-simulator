# P9-S8B1-R2 正式能力任务树完整性验收报告

## 结论

状态：`accepted`。S8B3A 预检发现的上游正式任务树缺失已在 compiler/lowering 根因处闭合，
可以继续 S8B3A 的能力调用关系和正式目录工作。本报告不宣称 runtime 已迁移。

## 生产结果

- 角色正式 ability lowering 不再只递归条件分支和单一固定循环，而是消费 S8A 已验收的
  branch、template definition 和唯一 template reference。
- 根 callback 从真实 ability 对象中的类型化任务列表发现。当前来源实际为 `OnStart`、
  `OnAdd`、`OnInsertAbort`；该值域来自目录扫描，不写成生产白名单。
- 正式实例路径与 raw JSON path 分离。共享模板被多处引用时形成不同 task 实例，但每个实例
  仍反查同一模板文件和记录位置。
- 正式来源上下文只构建一次，顶层索引只读；82 个使用中的文件均实时核对内容指纹。
- 该路径只对 P9 角色正式 lowering 显式启用。外部内容域保留旧路径，runtime 未修改。

## 验收证据

唯一主入口：

```text
python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8b1_r2_formal_task_tree_completeness
```

结果：

- `ok=true`
- 1,084 个非表现 ability 定义
- 14,640 个正式 task 实例
- 9,943 个 callback 根 task
- 4,697 条父子边
- callback 定义数：`OnStart=1045`、`OnAdd=28`、`OnInsertAbort=19`
- 模板引用：document global 105、local 24、shared global 39
- 来源文件 82，分支/模板 child 差异 0，定义投影失败 0
- 墙钟 20.84 秒，峰值 RSS 335,932 KiB，evidence 1,385 bytes
- 完整 Canonical IR build 0 次

生产负例覆盖：来源 payload 篡改、非权威上下文、模板缺失/歧义及模板环均被拒绝。

复杂 direct 使用此前失败的 Acheron Phase02：现已成功物化 37 个 graph node，不再出现
`formal_branch_child_missing`。同动作 Phase01 仍因 TriggerAbility 尚未关联正式 phase 而 blocked，
该问题精确归属 S8B3A，不是本卡任务树投影缺失。

`compileall`/import smoke、`git diff --check` 通过。未运行历史 S8A/S8B1 主入口、完整 lowering、
runtime 聚合或无关 direct。

## 过程复盘

主入口首次运行在进入业务判定前因验证器 Counter 用法错误退出；修正验收器后只补跑一次，
生产实现和业务场景未随之修改。更重要的规划遗漏是：旧闭合地图只核对内部 branch，没有先枚举
ability 根 callback 字段，因而遗漏了 `OnAdd` 和 `OnInsertAbort`。流程规范现已补充：来源目录与
正式投影分阶段建立时，消费迁移前必须按唯一来源定义同时核对根入口与全部 branch/template child。
