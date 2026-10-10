# 本地命令行战斗

已跑通阿兰、希露瓦与娜塔莎指定构筑的单人、双人和三人战斗路线，双方手动控制，
从正式出生、普通行动、终结技插入一直到胜利。当前支持单波，具体边界见下文。

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

归档使用 `hsr_battle_archive_v2` 引用表与 `hsr_battle_session_v2` 会话结构：相同审计对象只保存
一次，读取时恢复共享内容，回放仍逐项核对完整事实。支持 `.json.gz` 和普通 `.json`，推荐前者。
场景与操作文件仍是普通 JSON。按用户决定不兼容旧格式或旧规则指纹；分别明确返回格式错误
或 `canonical_ir_fingerprint_mismatch`，后者在重建战斗前拒绝。
首次编译和完整回放仍有成本，当前没有跨进程编译缓存。

角色卡及星魂/行迹选择账本现在按场景所选角色构建，完整共享来源目录仍保留校验。
2026-10-10 同一希露瓦双人路线实测：角色卡由 92 张降至 2 张，编译由 68.388 秒降至
59.448 秒；来源审计组装拆分后的独立文件回放 43 步全部一致。上述编译降幅约 13%，
不能当作整场加速倍数，也不表示全部来源编译都已按场景裁剪。

脚本执行使用 `run 场景路径 --commands 操作路径 --output 记录路径`。操作文件形如 `{"commands": [...]}`，
每项填写 `actor_id`、`action_id`、`action_level`、`target_ids`，或使用查询返回的 `command_template`。
可信动作元数据由 `DecisionSystem` 补齐；同一个系统校验目标、资源与时机。
脚本结束时战斗尚未结束，退出码为 `3`；执行或校验失败为 `2`，完成为 `0`。

## 阿兰、希露瓦与娜塔莎三人路线（2026-10-10）

三人均为 E0 / 1 级、零初始能量、空装备、无额外行迹，对来源关卡 `200021050` 的两只
8 级重子。十九次提交覆盖阿兰损血、娜塔莎定向治疗与持续治疗、希露瓦两目标攻击与感电，
随后娜塔莎从战技与受击获得 90 能量，在自己普通回合插入终结技，实际治疗三名受伤队友。
终结技队列完成后继续普通行动，保留感电跳伤及击杀，最终获胜。

```bash
export PYTHONPATH=hsr_v075_baseline_clean
.venv/bin/python -B -m hsr.simulator_v8_clean_core.cli run \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/arlan_serval_natasha_vs_antimatter.json \
  --commands hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/arlan_serval_natasha_vs_antimatter.commands.json \
  --output /tmp/arlan-serval-natasha-battle.json.gz
.venv/bin/python -B -m hsr.simulator_v8_clean_core.cli replay /tmp/arlan-serval-natasha-battle.json.gz
```

群疗分别结算三名目标，阿兰 HP `138.72`、希露瓦 HP `72.5216483384`、娜塔莎 HP `114.8391060172`
恢复至各自满血；能量扣至零后返还 5，不消耗战技点。最终阿兰 HP `163.2` / 能量 `100`，
希露瓦 HP `124.8` / 能量 `100`，娜塔莎 HP `108.8179530086` / 能量 `45`，SP `2`，两怪 HP `0`。
本路线的感电两次命中判定一成一败，天赋追加伤害只结算实际感电的目标；不把基础概率当成必然。
它复用现有角色机制，验证同队执行时的目标、资源和状态归属；不扩大到未验收构筑。
固定脚本的来源场景检查通过，独立 CLI 回放返回 `ok=true, step_count=39, errors=[]`。
归档约 411 KB；本次生成 162.53 秒、独立回放 171.83 秒。

## 希露瓦与娜塔莎的完整胜利路线（2026-10-09）

新增两名 E0 / 1 级、无额外行迹与装备，对来源关卡 `200021050` 两只 8 级重子的示例。
双方从零能量出生，21 次提交覆盖希露瓦普攻、战技、感电、天赋追加伤害和终结技。
终结技仍分申请与队列执行；本例在敌人行动前插入，击败当前行动者后由调度器关闭其回合，
另一个敌人在下一次行动前被感电击败，最终获胜。

```bash
export PYTHONPATH=hsr_v075_baseline_clean
.venv/bin/python -m hsr.simulator_v8_clean_core.cli run \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/serval_natasha_vs_antimatter.json \
  --commands hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/serval_natasha_vs_antimatter.commands.json \
  --output /tmp/serval-battle.json.gz
.venv/bin/python -m hsr.simulator_v8_clean_core.cli replay /tmp/serval-battle.json.gz
```

战技对两个感电目标各结算一次天赋追加伤害；终结技把存活目标的感电从 2 回合延长到 4 回合。
独立状态副本检查覆盖两个目标均存活的情况：感电剩余 1/2 回合分别延长至 3/4 回合，
完整目标随机记录由已有任务图原子执行器提交；任一目标实例不合法时不提交部分延长。
终态希露瓦 HP124.8/能量25、娜塔莎 HP158.4/能量90、SP2，两怪 HP0。
目标筛选、持续时间、伤害与回放使用共享内核，正式逻辑不按角色名分支。
此结果只验收上述构筑与路线，额外星魂/行迹、属性变化时的 DOT 快照刷新及重施仍需单独贯通。

内部快照复用已有不可变子树，公开 JSON 导出保持深度独立；同一实际状态的十次内部快照构造
微测从 3.34 秒降到约 0.003 秒。该数字不代表整场加速倍数，首次来源编译仍约 70–94 秒，
完整审计导出与跨进程重复编译仍有成本。
2026-10-10 根因修复：伤害 metadata 不再嵌入整包别名，DoT 账本通过键与索引关联单份求值证据，
击败与击杀回能通过 HP mutation ID 关联致死来源。审计检查对应同次执行中的 HP 变化与来源，
不会把引用作为战斗规则输入。会话、原子提交证据和来源审计复用不可变数据，默认导出仍独立。
归档保留原子发布、禁止覆盖、重复键和非有限数拒绝；引用表还拒绝循环、悬空及无关对象。
回放直接读取引用表并复用已比较的共享子树，删除旧的逐转换分帧与暂存读取器。
旧结构的同路线基线为展开约3.27GB、压缩约86MB，生成9分23秒、文件回放13分14秒，
峰值内存分别约3.6/3.9GiB；全文读取曾超过14GiB。上述数字仅用于修复前后的实测对比。

新结构同路线实测：压缩363808字节（约364KB），JSON引用表3204883字节（约3.2MB），
12225个不同对象。生成并保存2分27.96秒、峰值926924KiB（约0.88GiB）；独立文件回放
2分36.48秒、峰值895936KiB（约0.85GiB），返回 `ok=true, step_count=43, errors=[]`。
两次进程均未换页，胜利终态不变。归档为 `/tmp/hsr-serval-audit-v2-20261010.json.gz`，
同名前缀的 `-run.log/-run.time` 与 `-replay.log/-replay.time` 保留完整退出码和成本证据。
本批73项不同的定向检查通过；整场只生成一次、独立文件回放一次，没有叠加同场内存回放。
当前残余成本包括来源编译与战斗执行，不能把归档读取加速当成所有性能问题已解决。

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

## 第二个可运行波次（2026-09-30）

`examples/cli/arlan_lv20_vs_mixed_antimatter.json` 使用阿兰 E0/20 级和来源关卡 `80010011` 的单波：
`8011020`、`8011010` 各一只，双方仍由操作文件逐步选择。两种怪物的纯表现控制器
共享单位私有 `TimeSlowSpeed` 键；来源审计现在只在两者都证明无战斗输出时排除它们，
并继续检查控制器外部对该键及全局 modifier 名称的引用。

```bash
.venv/bin/python -m hsr.simulator_v8_clean_core.cli run \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/arlan_lv20_vs_mixed_antimatter.json \
  --commands hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/arlan_lv20_vs_mixed_antimatter.commands.json \
  --output /tmp/arlan-mixed-battle.json.gz
.venv/bin/python -m hsr.simulator_v8_clean_core.cli replay /tmp/arlan-mixed-battle.json.gz
```

2026-10-08 已依据 PR #8 的已确认研究修正 `LoseHPByRatio.Floor`：它是剩余 HP 下限，
不是损血量的取整标志。阿兰该请求保留至少 1 HP；正常损血保留小数，已经低于下限时
不会因此获得治疗。定向检查覆盖正常 HP、濒死 HP、1 HP 和缺少下限绑定时零提交。
本示例的 2026-09-30 胜利数值仍是当时记录，不作为本次修复后的新结果。

## 双人治疗胜利路线（2026-10-08）

`examples/cli/arlan_natasha_vs_antimatter.json` 使用阿兰与娜塔莎 E0/Lv1、空装备、无额外行迹，
对同一波两只 Lv2 重子。十二次提交包括四次阿兰战技、三次治疗、四次怪物攻击及一次同速选择。
第二次治疗选择娜塔莎自身，让阿兰原有的持续治疗触发两次并到期。

```bash
.venv/bin/python -m hsr.simulator_v8_clean_core.cli run \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/arlan_natasha_vs_antimatter.json \
  --commands hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/arlan_natasha_vs_antimatter.commands.json \
  --output /tmp/arlan-natasha-battle.json.gz
.venv/bin/python -m hsr.simulator_v8_clean_core.cli replay /tmp/arlan-natasha-battle.json.gz
```

娜塔莎战技使用角色配置中的友方选择关系；镜头、特效及纯语音选择保留来源后排除。
每次治疗消耗一点战技点，真实 `AddRatio=1` 请求在来源位置增加一次动作 `SPBase=30`，
统一资源计划不提前重复发放。治疗者/受治疗者的瞬时加成通过类型化回调结果传递，不读审计记录。
重复施放的动作动态值按所属单位和本次能力实例读取，不混入历史实例或其他单位的同键值。

本路线实跑得到 `victory`：阿兰 HP `138.72`、能量 `110`，娜塔莎 HP `158.4`、能量 `90`，
剩余战技点 `0`，两只敌人 HP 均为 `0`。持续治疗基数为 `0.048 × 158.4 + 48 = 55.6032`，
在目标回合开始结算并按缺失 HP 截顶。

新进程完整场景检查及 `verify_archive` 回放均已通过；原阿兰九次胜利路线也通过回归。
同一真实条件/参数的低 HP 组件探查确认 30% HP 边界享有 25% 天赋加成：
请求治疗 `101.36`，HP `48.96 → 150.32`；该探查使用状态副本，不改上述胜利脚本历史。

这是静态面板的一条完整战斗路径；普攻与终结技的后续进展见下一节。治疗者属性改变时的
快照采样、同目标覆盖重施的精确刷新语义仍保留缺口，当前结果不能证明这些行为。

## 双人普攻与终结技胜利路线（2026-10-09）

复用上述 E0/Lv1 场景，改用 `arlan_natasha_ultimate_vs_antimatter.commands.json`。
十四次提交包含娜塔莎普攻、两次治疗战技，以及一次终结技的申请和队列执行；怪物攻击目标
由外部操作指定。娜塔莎通过战技、普攻及受击自然获得 90 点能量，在阿兰回合插入终结技，
自动治疗两名队友，随后阿兰继续行动并获胜。两条终结技命令表示申请与执行，不是施放两次。

```bash
.venv/bin/python -m hsr.simulator_v8_clean_core.cli run \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/arlan_natasha_vs_antimatter.json \
  --commands hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/arlan_natasha_ultimate_vs_antimatter.commands.json \
  --output /tmp/arlan-natasha-ultimate-battle.json.gz
.venv/bin/python -m hsr.simulator_v8_clean_core.cli replay /tmp/arlan-natasha-ultimate-battle.json.gz
```

普攻命中后回能 20、增加一点战技点；终结技消耗 90 能量，执行后回能 5，不消耗战技点。
本路线终态为 `victory`：阿兰 HP `163.2` / 能量 `110`，娜塔莎 HP `158.4` / 能量 `5`，
战技点 `4`，两只敌人 HP 均为 `0`。Lv1 群疗基数为 `0.092 × 158.4 + 92 = 106.5728`；
各目标分别进入原有治疗回调与结算链，按各自缺失 HP 截顶。

新进程完整场景检查通过，独立 CLI replay 为 `ok=true / step_count=29 / errors=[]`。
同一正式终结技的状态副本探查确认：30% HP 的目标请求治疗 `133.216`，31% HP 的目标
请求 `106.5728`，分别结算天赋加成；探查不改上述胜利脚本历史。

动作准入使用正式构筑条件，排除未激活星魂/行迹分支；条件事实不足或分支实际激活时仍保留
真实阻断。投射物当前只支持正式来源中单个已选目标、忽略碰撞且等待命中的路径，保留并执行
命中子任务；不建立动画飞行时间轴。异步在途结果、碰撞分支、额外行迹/星魂及完整快照语义
仍需随相应内容接入，不能将这条 E0 路线扩称为完整角色支持。
