# 本地命令行战斗

已跑通首个真实来源战斗：阿兰 E0 / 1 级对两只 2 级重子，双方手动控制，
从正式出生、普通行动、终结技插入一直到胜利。当前是单波战斗雏形，支持范围见下文。

使用工作区已有的 `.venv`，无需安装新依赖。在仓库根目录运行：

```bash
export PYTHONPATH=hsr_v075_baseline_clean
.venv/bin/python -m hsr.simulator_v8_clean_core.cli play \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/arlan_vs_antimatter.json \
  --output /tmp/arlan-battle.json.gz
```

双方都由操作者选择动作和目标。输入动作编号，再输入目标编号或 ID；`j` 查看完整合法动作，
`q` 保存当前会话并退出。能量满足条件时可请求插入终结技，随后选择队列中的执行动作。
退出会话不会伪造胜负。输出路径必须尚不存在。

复现内置胜利操作：

```bash
.venv/bin/python -m hsr.simulator_v8_clean_core.cli run \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/arlan_vs_antimatter.json \
  --commands hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/arlan_vs_antimatter.commands.json \
  --output /tmp/arlan-scripted.json.gz
```

操作文件包含双方选择，并包含同速顺序选择、终结技请求及执行；它不是敌方 AI。

只查询首次决策：

```bash
.venv/bin/python -m hsr.simulator_v8_clean_core.cli query \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/arlan_vs_antimatter.json
```

验证保存的战斗：

```bash
.venv/bin/python -m hsr.simulator_v8_clean_core.cli replay /tmp/arlan-battle.json.gz
```

回放会从原始配置重新出生、初始化时间线、提交全部操作，并逐步比较状态、事件、随机结果、mutation 和结算。规则指纹不同或记录被修改会使校验失败。归档也保存了入场过程的原生事件与 mutation。

推荐 `.json.gz`：完整来源审计包含大量重复内容，压缩能显著减少磁盘占用，不省略任何事实。
仍支持普通 `.json`。首次编译和完整回放可能需要几分钟，当前没有跨进程编译缓存。

脚本执行使用 `run 场景路径 --commands 操作路径 --output 记录路径`。操作文件形如 `{"commands": [...]}`，
每项填写 `actor_id`、`action_id`、`action_level`、`target_ids`，或使用查询返回的 `command_template`。
可信动作元数据由 `DecisionSystem` 补齐；同一个系统校验目标、资源与时机。
脚本结束时战斗尚未结束，退出码为 `3`；执行或校验失败为 `2`，完成为 `0`。

## 配置与当前边界

示例采用阿兰零星魂、1 级、无额外行迹、无装备，以及数据库关卡 `200020050` 的两只 2 级 `8011010`。角色面板由正式构筑装配；敌人面板由来源波次和怪物卡生成，不手写伤害或属性答案。技能等级由构筑解析。

阿兰普攻、战技损血与即时天赋增伤、终结技及击杀回能已经过正式执行检查；怪物攻击及受击回能
使用同一内核。怪物的四个公共韧性监听器/属性状态在出生时真实安装，未击破减伤只计算一次。
表现控制器只有在结构与所选来源范围都证明没有战斗输出时才排除；修改引用范围会重新检查。

共享预治疗结算已接入受治疗者的 `OnBeforeBeingHeal` / `Target_HealTakenRatio`，与治疗者
加成在同一乘区计算。真实 Sam 条件与修正任务的定向检查得到
`1000 × (1 + 0.5 - 0.9) = 600`；这是该规则的接入，不代表整个 Sam 战斗已可运行。

可修改场景中的角色构筑、入场 HP/能量、站位和来源关卡波次；不受支持的配置会报具体错误。
角色 `input_fingerprint` 可以省略并自动计算；若提供则必须匹配。装备构筑仍使用正式
`EquipmentBuildInput` 生成的成品及指纹，不能随意编辑指纹绕过校验。

`battle_setup.metadata.stage_scope="wave_only"` 明确表示只采用该关卡的怪物波次。它不是主线关卡复刻，不加载关卡模板中的全局能力（包括 `StageAbility_Elation`）。当前不提供 UI、养成过程或敌方 AI。

尚未确认的战斗机制不得用估值补齐。超出已准入内容的构筑、任务、目标或上下文会返回具体阻断原因；失败的正式动作不会提交部分状态。支持范围以实际贯通验证为准，不能用静态数据卡数量代表可玩的角色数量。

本轮 MVP 范围（2026-09-28 用户最新确认）：先交付一个确定配置和操作路径能够完整结束、保存并
回放的命令行战斗。当前就是上述阿兰对两只重子的场景。其他角色、任意操作路线和通用机制
扩展不作为这个雏形的完成条件。虚韧性等特殊韧性机制、特殊韧性计数、多波出生延后。
`RedStance` 仅保留为来源标识；当前研究
没有确认它与虚韧性的对应关系，不再将它直译为“红韧性”。

当前执行边界：

- 示例的雷攻击不命中敌人的冰/风弱点，整场不发生击破。正式能力图已接入共享削韧结算，
  已确认的普通单体普攻以 30 点旧制削韧量乘来源逐段比例；伤害在本段削韧前结算。
  普通击破公式、状态参数和已确认的自然恢复规则已补接，但完整公共事件链仍因
  `TriggerBreak(Caster)` 的通知映射未确认而阻断。组件级检查不等于完整击破已贯通；
  其他技能量与特殊时序仍按内容接入验证。
- PR #8 已研究普通回能及 ERR、固定回能、终结技扣能与返能、击杀回能，程序已接入。
  非致死多请求现按最新 PR #8 的 `SPHitBase × 请求 SPHitRatio × (1 + 受击方 ERR)` 逐次回能
  并截顶；真实双请求源的定向执行与审计已通过。完整弹射动作仍须接其投射物/目标内容链。
  致死受击回能按用户决定等待游戏实测，当前仍主动阻断，因此不能保证任意操作路线完成败北结算。
- CLI 拒绝多波场景，避免后续波次绕过尚未接通的完整被动出生流程。当前没有通用全内容支持声明。

已确认 PR #8 的普通规则直接作为实现依据；未找到 native 赋值位置不构成拒绝已确认公式的理由。
上述保留项分别记录具体规则依据或执行链的缺口；明确延期项不作为本轮 MVP 验收阻断。

检查以真实行为为目的：运行示例战斗并独立回放，对受击回能、多盾、击破、状态/随机调用保留必要行为
正例。不以覆盖率、全量检查数量或重复验证内核已拒绝的非法输入作为交付目标。

2026-09-28 本地实跑结果：内置九次操作得到 `victory`，阿兰剩余 HP `5.25078`、能量 `15`，
两只重子 HP 均为零。独立 CLI replay 返回 `ok=true, step_count=19, errors=[]`。
最终源码下的本轮归档在 `/tmp/hsr-mvp-pr8-shared-final-20260928.json.gz`；运行和回放日志分别为
`/tmp/hsr-mvp-pr8-shared-final-20260928-run.log`、
`/tmp/hsr-mvp-pr8-shared-final-20260928-replay.log`。

逐项机制、内容和验证边界见 [2026-09-28 已知缺口清单](docs/MVP_KNOWN_GAPS_2026-09-28.md)。
