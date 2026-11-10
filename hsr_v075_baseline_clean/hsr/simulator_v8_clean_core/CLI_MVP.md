# 本地命令行战斗

已跑通阿兰、希露瓦与娜塔莎指定构筑的单人、双人和三人战斗路线，双方手动控制，
从正式出生、普通行动、终结技插入一直到胜利；另有真实两波的限定清怪路线，具体边界见下文。

使用工作区已有的 `.venv`，无需安装新依赖。在仓库根目录运行：

首次选择一组内容时编译规则并缓存；相同来源、代码和内容范围的后续启动及独立回放复用缓存。
范围编译会递归纳入怪物表 `SummonIDList` 声明的子怪物卡、动作和被动，避免召唤时缺少定义。
加载依赖不会让子怪物提前出生，也不代表召唤已可执行；动态 ID、启动或生命周期缺口仍须通过正式准入。
修改操作脚本或初始战斗数值无需重新展开规则。缓存损坏或输入变更时自动重建；默认缓存目录
为 `/tmp/hsr-v8-ir-cache-<uid>`，可通过 `HSR_IR_CACHE_DIR` 指定保存位置。

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

普通增益秘技可在场景的 `battle_setup` 中声明已经激活的秘技；入场时由内核按角色构筑的
实际技能等级执行来源任务，不需要手工填写状态或倍率。例如队员 ID 为 `danheng` 时：

```json
"techniques": [{"actor_id": "danheng", "action_ref": "avatar_skill:100207"}]
```

秘技在出生初始化后、入场通知和时间线初始化前执行，记录正式 mutation 与结算。
归属不符、重复激活和未准入的秘技会拒绝。当前接通纯 `OnStart` 战前效果；攻击秘技和
依赖额外行动窗口的形式仍需对应战斗机制。

秘技与弹射示例为 `asta_bounce_danheng_technique.json`，操作文件同名加 `.commands.json`。
艾丝妲与丹恒 E0/Lv1、空装备、初始能量 0；丹恒秘技按来源提供 40% 攻击增益、持续
3 回合。正式四次提交包括艾丝妲五段战技、敌方行动和继续操作，最终胜利；只使用来源波次。
将上述 `run` 命令的场景及操作路径替换即可复用，网页样例列表也会加载该配置。

普通物理击破交战示例为 `serval_natasha_physical_break.json`，操作文件同名加
`.commands.json`；将上述两个输入路径替换即可运行。希露瓦与娜塔莎 E0/Lv40、空装备，
面对来源波次的两只 Lv28 反重子，五次提交内发生两次物理击破、一次敌方攻击并获胜。
网页场景选择中同样可用；这是波次配置，尚不包含完整关卡环境。

## V2 五元素普通击破自然路线（2026-10-19）

五条普通单韧性自然击破路线集中在
`tests/test_ordinary_element_break_natural_routes.py`；示例与固定操作各一对：

- 火：`asta_fire_break_natural`
- 雷：`arlan_thunder_break_natural`
- 冰：`march7th_ice_break_natural`
- 量子：`lynx_quantum_break_natural`
- 虚数：`trailblazer_imaginary_break_natural`

每个场景同名加 `.commands.json`，将上述 `run` 命令的场景与操作路径替换即可复现。路线在交付链
完成后可能战斗未完，CLI 返回 `3` 并保存可继续会话；量子示例（含独立归档回放 13 步、0 错误）：

```bash
export PYTHONPATH=hsr_v075_baseline_clean
.venv/bin/python -B -m hsr.simulator_v8_clean_core.cli run \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/lynx_quantum_break_natural.json \
  --commands hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/lynx_quantum_break_natural.commands.json \
  --output /tmp/hsr-v2-quantum-postfix.json.gz
```

五元素差异：火/雷是击破 DOT（灼烧/触电）tick；冰冻结消耗目标回合且该回合不恢复，解冻后下一
自然回合才恢复；量子由实际命中增加纠缠计数并在到期时一次结算；虚数禁锢提供减速与行动延后，
到期恢复。计划角色因正式准入阻断，实际使用同元素合法角色（冰为三月七、量子为玲可、虚数为
同谐主），示例文件名已按实际角色命名；五行结果与剩余依赖见
[V2 执行说明](docs/V2_ORDINARY_ELEMENT_BREAK_ROUTES.md)。

## 银鬃尉官战斗内自然召唤（2026-10-22）

场景 `silvermane_lieutenant_summon_natural.json`，操作文件同名加 `.commands.json`。
来源为 StageConfig `307311` wave 0 的单只 Lv44 银鬃尉官 `monster:1003010`；阿兰
`avatar:1008` E0/Lv80/P6 与娜塔莎 `avatar:1105` E0/Lv80/P6 使用既有空装备正式构筑。
18 次公开提交依次完成：外部选择召唤技能、两名 `1002040` 士兵出生并各行动一次、娜塔莎自然
击败其中一名、尉官存活时再次召唤、新实例行动与一次后续公开普攻；脚本结束时战斗未结束，CLI
返回 `3` 并保存可继续会话：

```bash
export PYTHONPATH=hsr_v075_baseline_clean
.venv/bin/python -B -m hsr.simulator_v8_clean_core.cli run \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/silvermane_lieutenant_summon_natural.json \
  --commands hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/silvermane_lieutenant_summon_natural.commands.json \
  --output /tmp/hsr-v3-lieutenant-summon.json.gz
```

来源分支选择、卡片级 CustomValues 绑定、省略 ResetValue 语义、出生后启动与再召唤收口边界见
[自然召唤执行说明](docs/MONSTER_SUMMON_NATURAL_ROUTE_CLOSURE.md)。

## 希儿增强版普攻后置监听（2026-10-20）

场景 `seele_post_attack_listener_natural.json`，操作文件同名加 `.commands.json`。希儿
`avatar:1102` E0/Lv1/P0 与娜塔莎 E0/Lv80/P6 均空装备，进入来源波次 `400020800` wave0。
四次公开提交依次为希儿增强版普攻 `avatar_skill:1110201`、娜塔莎普攻、敌方行动和希儿再次
普攻；脚本结束时战斗未结束，CLI 返回 `3` 并保存可继续会话：

```bash
export PYTHONPATH=hsr_v075_baseline_clean
.venv/bin/python -B -m hsr.simulator_v8_clean_core.cli run \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/seele_post_attack_listener_natural.json \
  --commands hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/seele_post_attack_listener_natural.commands.json \
  --output /tmp/hsr-seele-post-attack.json.gz
```

真实后置监听 `MAvatar_Advanced_Seele_00_Skill02_AutoInsertListen` 的
`OnListenAfterAttack` 回调会消费本次已准入行动的完整目标表（
`ParamEntityAttackTargetList.SortByHP` 的 Retarget）。满血目标的 HP 比例条件为假时选择空集，
不新增状态也不插入行动。路线、来源子图组件证据与剩余依赖见
[希儿后置监听路线](docs/SEELE_POST_ATTACK_LISTENER_ROUTE.md)；完整增强版自动追击、特殊追加
行动和其它技能分支不在本批范围。

## 希儿增强版自动插入行动（2026-10-20）

场景 `seele_automatic_insert_natural.json`，操作文件同名加 `.commands.json`。希儿
`avatar:1102` E0/Lv1/P0 与娜塔莎 `avatar:1105` E0/Lv32/P2 均空装备，进入来源波次
`400020800` wave0。前八次公开提交复现真实监听阈值路线；第八次希儿普攻使目标进入真实
HP 比例阈值后，正式 `TurnInsertAction` 入队并在下一步排空：开始回调按类型化 tag 命中、
自动以希儿实际动作集与有效等级执行战技、正文后完成 MuteSp/Clean/Ready/InsertCheck 清理。
第九次为自动战技后的公开行动（娜塔莎治疗战技 110502 对自身）；脚本结束时敌方仍有一只存活，CLI 返回 `3`：

```bash
export PYTHONPATH=hsr_v075_baseline_clean
.venv/bin/python -B -m hsr.simulator_v8_clean_core.cli run \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/seele_automatic_insert_natural.json \
  --commands hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/seele_automatic_insert_natural.commands.json \
  --output /tmp/hsr-seele-automatic-insert.json.gz
```

实现边界、取消/清理语义与验收入口见
[自动插入行动路线](docs/SEELE_AUTOMATIC_INSERT_ACTION_ROUTE.md)。

关卡公共环境示例为 `arlan_common_stage_environment.json`，操作文件同名加 `.commands.json`。
阿兰 E0/Lv80、空装备，对关卡 `200020050` 的两只 Lv2 重子；配置使用 `full_stage`，
由关卡模板安装公共战斗能力和欢愉公共环境，再执行出生与入场通知。三次双方操作后获胜，
来源审计与归档回放通过。将上述 `run` 命令的场景及操作路径替换即可运行，网页也可直接加载。
这条路线没有欢愉角色或击破，不代表这些环境的全部分支、特殊评分和副关卡已完成。

护盾反击示例为 `arlan_march_shield_counter.json`，操作文件同名加 `.commands.json`。
阿兰与三月七均 E0/Lv1、空装备。四次操作依次为阿兰普攻、三月七给阿兰施盾、选择左侧
敌人先行动、敌人攻击阿兰；随后自动反击造成约 15.2958 冰伤，剩余反击次数从 2 减为 1。
这是首次反击的操作前缀，脚本结束时战斗未完，CLI 返回 `3` 并保存进度，可用 `resume`
继续；网页选择“阿兰＋三月七 · 护盾与反击”可手动操作。同样仅采用波次配置。
在网页配置中将三月七星魂改为 4，同样四步已通过：反击约 25.5809 冰伤、次数从 3 减为 2，
包含正式入场效果与防御附加伤害。未据此认定全部星魂分支或其它追加攻击均已完成。

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

从已保存的进度继续操作（例如重启 WSL 或服务后）：

```bash
.venv/bin/python -B -m hsr.simulator_v8_clean_core.cli resume /tmp/arlan-battle.json.gz \
  --output /tmp/arlan-continued.json.gz
```

先完整回放校验，全部一致才进入原进度的交互操作；也可加 `--commands 后续操作.json`。
新归档保留恢复前后的全部历史，原文件不覆盖。损坏记录或规则指纹不符不会生成恢复会话。
同版 CLI 与网页共用规则指纹；网页恢复后生成的新归档已通过独立 CLI 的 25 步回放。
只能恢复已经保存的进度；尚未保存的内存会话在进程退出后无法找回。
已用下述两波路线验证中途保存、独立进程续打获胜和最终 9 步回放一致；篡改终态时拒绝恢复。

归档使用 `hsr_battle_archive_v2` 引用表与 `hsr_battle_session_v2` 会话结构：相同审计对象只保存
一次，读取时恢复共享内容，回放仍逐项核对完整事实。支持 `.json.gz` 和普通 `.json`，推荐前者。
场景与操作文件仍是普通 JSON。按用户决定不兼容旧格式或旧规则指纹；分别明确返回格式错误
或 `canonical_ir_fingerprint_mismatch`，后者在重建战斗前拒绝。
首次编译和完整回放仍有成本；后续进程复用上述持久化 IR 缓存，回放本身仍逐步执行。

角色卡及星魂/行迹选择账本现在按场景所选角色构建，完整共享来源目录仍保留校验。
2026-10-10 同一希露瓦双人路线实测：角色卡由 92 张降至 2 张，编译由 68.388 秒降至
59.448 秒；来源审计组装拆分后的独立文件回放 43 步全部一致。上述编译降幅约 13%，
不能当作整场加速倍数，也不表示全部来源编译都已按场景裁剪。

脚本执行使用 `run 场景路径 --commands 操作路径 --output 记录路径`。操作文件形如 `{"commands": [...]}`，
每项填写 `actor_id`、`action_id`、`action_level`、`target_ids`，或使用查询返回的 `command_template`。
可信动作元数据由 `DecisionSystem` 补齐；同一个系统校验目标、资源与时机。
脚本结束时战斗尚未结束，退出码为 `3`；执行或校验失败为 `2`，完成为 `0`。

## 浏览器持续战斗（2026-10-11）

在仓库根目录启动，打开 `http://127.0.0.1:8765`：

```bash
PYTHONPATH=hsr_v075_baseline_clean/hsr .venv/bin/python -B -m simulator_v8_ui.server
```

1. 保持“持续战斗”模式，选择已有场景并点击“加载”。可在开战配置中修改等级、晋阶、星魂；
   “加载角色目录”后可以添加、移除或切换角色，队伍保留 1–4 人。新增和切换使用 1 级、零星魂、
   默认行迹和空装备；增删后站位自动连续，保留其余队员的相对顺序与构筑。
   含预置路线、状态或召唤物的草稿需先处理关联；目录收录不表示该角色的全部战斗机制已支持。
   例如阿兰单人场景将星魂改为 1，构筑指纹自动重新计算。点击“加载行迹选项并校验构筑”后，
   可选择技能等级、属性行迹与额外能力，再次校验会展示正式装配面板和生效技能等级。
   “加载光锥与遗器选项”提供装备表单；选择光锥、等级、晋阶和叠影后点击应用，空选择表示卸下。
   遗器按部位选择套装与稀有度，加载词条后设置等级、主词条和副词条；点击应用只替换该部位。
   副词条沿用正式成品输入的基础份数与累计附加档位，校验结果展示实际数值，不模拟强化过程。
   各角色的“初始生命值与能量”可设置满血、生命比例（0–1）或指定生命值，以及普通初始能量。
   这些值作为出生前的场景输入，随后照常执行被动与入场效果；生命值须大于零，出生计划按正式
   装配面板检查上限，越界拒绝，不静默截断。特殊资源仍由正式能力初始化。
   多人队伍可在“我方站位”中左移或右移角色；只交换现有站位，保留角色身份与构筑，下次开战生效。
   缺失或重复的站位需先在 JSON 中修正。调整站位不加载规则，正式邻位与目标仍由内核解析。
   展开“替换敌方波次”，可按关卡名称或编号搜索来源目录，再应用所选波次；保留我方构筑，
   替换原敌方，从第 1 波开始。此按钮默认只采用怪物波次；完整环境可加载上述示例，
   或在 JSON 中设置 `battle_setup.metadata.stage_scope="full_stage"`，由开战流程检查实际依赖。
   搜索仅展示前 100 个匹配项；目录记录不代表战斗可用，正式开战仍会拒绝未闭合的内容。
   等级、晋阶、前置行迹和来源缺口均由内核判定；装配通过后，开战仍需检查被动启动、敌人与关卡。
   完整配置仍可在下方 JSON 查看和编辑。
2. 点击“开始战斗”。只有此时加载所选规则并执行正式入场；页面加载不编译全目录。
3. 点击内核返回的动作和目标。双方均由人控制；同速行动者选择、终结技请求与队列执行都使用
   原始命令模板。每次提交沿同一 `BattleSession` 继续，不重跑先前路线、不重新编译。
4. 点击事件查看该步伤害、状态、资源和来源检查。动作执行受阻时可改选其它动作，阻断记录保留。
5. “下载战斗记录”得到标准 `.json.gz` 归档；“校验回放文件”会独立重建并逐步核对，保留当前战斗。
   同一文件也可交给前述 CLI `replay`。Web 上传限 10 MB 解压后的 JSON，超出时使用 CLI。
6. “载入归档继续战斗”会完整校验记录，在成功后替换当前会话；可继续选择双方动作。
   导入失败保留旧战斗。网页事件列表展示续打部分，下载归档保留恢复前后的完整历史。
7. 事件回放下方可选择任一次历史提交，点击“回到所选提交前”后重新选择动作。
   内核从初始配置重放并核对操作前缀，成功后切换到新会话；规则直接复用，校验失败保留原会话。
   需要比较原路线时，请先下载其归档。恢复过的归档历史同样提供可选分支点。
8. “游戏实测对照”中选择当前单位，填写同一时刻的生命、能量、韧性或护盾，未知项留空。
   可记录游戏版本和复刻说明，服务端直接读取正式状态并计算“观测 − 模拟”的十进制差值，
   不推断显示取整或容差，不改写战斗。韧性须使用同一数值单位，不能用百分比代替绝对值。
   输入绑定填写时的局面；推进、回溯或重开后须清空数值重新填写，过期请求不会自动重试。
   点击保存用例或导出观测 JSON 保留记录，并下载对应战斗归档。观测独立保存，不嵌入战斗归档；
   每条记录保留规则、配置和操作路径指纹以及操作序号，避免混淆不同构筑或分支。

刷新网页可恢复服务中的当前战斗。当前服务只保存一个内存会话，重启服务前应先下载归档；
“按配置重新开战”成功后替换当前会话，配置不合法则保留旧战斗。重复点击、过期页面或其它标签页
的旧决策不能重复提交。浏览器与 CLI `resume` 均可恢复已保存进度；未保存的内存进度无法恢复，
可以从历史动作提交前建立分支，页面尚不同时管理多条分支。

这是现有测试台接入持续操作后的入口，仍不是完整 UI v2：环境范围暂通过场景或 JSON 选择，
多分支并排管理尚未交付。内置场景（含两种两波路线）、队伍增删、角色切换、
来源波次搜索、基础构筑、行迹和装备表单已接入，改变构筑仍受
当前真实机制准入限制；装配通过不等于全部分支已验证。“路线测试”模式保留旧测试台流程。

本批通过内存 HTTP 请求驱动真实阿兰胜利整场、非法目标零提交、旧决策冲突、刷新查询与归档下载；
相同处理器的回放入口另在独立进程检查。当前沙箱禁止监听端口且未安装浏览器，因此未做实际
浏览器布局、点击与文件下载验收；前端命令转发和重复点击保护有独立 Node 检查。

## 阿格莱雅与忆灵普通交战（2026-10-13）

网页场景列表选择 `aglaea_servant_vs_antimatter`。E0/Lv1、空装备，单波两只重子；
17 次公开选择完成召唤、治疗、忆灵两次攻击、金线附加伤害及敌方自然行动，最终胜利。
首次战技生成忆灵并推进主人和忆灵行动，战技随后自动替换为忆灵治疗。
忆灵生命为 `254.3424`，按主人实际 1 级天赋绑定；本路线的治疗额度为 `63.5856`，
发生在忆灵满血时。终结技和联合攻击另见下方样例；完整角色仍未验收。

```bash
PYTHONPATH=hsr_v075_baseline_clean .venv/bin/python -B -m hsr.simulator_v8_clean_core.cli run \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/aglaea_servant_vs_antimatter.json \
  --commands hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/aglaea_servant_vs_antimatter.commands.json \
  --output /tmp/hsr-aglaea-servant.json.gz
```

## 阿格莱雅终结技与联合攻击（2026-10-15）

网页场景列表选择 `aglaea_joint_vs_antimatter`。E0/Lv1、空装备，正式配置初始能量 350，
单波两只重子；8 次公开操作完成召唤、终结技、联合攻击、忆灵普通攻击和敌方自然行动后胜利。
首次联合攻击主人 8 段、忆灵 2 段，共 `96.9142794631` 直接伤害；主人速度从 `102` 增至
`112.2`，忆灵从 `35.7` 增至 `79.7`。强化状态期间只开放强化普攻，战技禁用。
倒计时速度和初始行动值均为 `100`；此短战斗未覆盖到期、忆灵退场或其它构筑。

```bash
PYTHONPATH=hsr_v075_baseline_clean .venv/bin/python -B -m hsr.simulator_v8_clean_core.cli run \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/aglaea_joint_vs_antimatter.json \
  --commands hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/aglaea_joint_vs_antimatter.commands.json \
  --output /tmp/hsr-aglaea-joint.json.gz
```

## 倒计时退场与重新召唤（2026-10-15，2026-10-30 复验）

网页场景列表选择 `aglaea_countdown_resummon`。E0/Lv20、空装备、初始能量350，
使用关卡400020640的两只23级重子波次；**19 次公开操作获胜**（复验记录见下）。
倒计时到期后，忆灵退场，主人回复20能量（本次序列为25→45），机制条归零并关闭，
普通普攻与战技恢复；随后重新召唤忆灵并完成战斗。仅采用敌方波次，不包含完整关卡环境。

行动序说明（2026-10-30）：忆灵在主人强化态下每次攻击按来源 `MServant_AglaeaServant_00_AddSpeed`
逐层提升自身速度（上限来自主人 `SkillP01` 参数 `_MaxLayer`），因此忆灵会比旧记录更早获得
独立行动；旧 15 步命令不再匹配当前合法动作集，已按实际合法动作序列更新为 19 步。
公开命令仍为外部操作选择（含敌方目标选择），到达/重召唤/胜利语义不变。

```bash
PYTHONPATH=hsr_v075_baseline_clean .venv/bin/python -B -m hsr.simulator_v8_clean_core.cli run \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/aglaea_countdown_resummon.json \
  --commands hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/aglaea_countdown_resummon.commands.json \
  --output /tmp/hsr-aglaea-countdown.json.gz
```

可运行检查为 `tools/check_servant_retirement_battle.py OUTPUT_PREFIX`，输出实际配置、操作序列和结果。

## 两波清怪路线（2026-10-12）

`arlan_serval_natasha_two_waves` 使用三人 E0/Lv80/晋阶6、空装备，取真实关卡 `201010110`
的两波敌人。仅采用波次配置，未接完整关卡环境。浏览器可从场景列表加载同名配置；
依次操作：希露瓦战技打首波近战兵 → 阿兰战技打第二波枪兵 → 娜塔莎普攻打左侧近战兵 →
希露瓦战技打同一近战兵。四次提交获胜，未手改血量、能量或战场状态。

```bash
PYTHONPATH=hsr_v075_baseline_clean .venv/bin/python -B -m hsr.simulator_v8_clean_core.cli run \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/arlan_serval_natasha_two_waves.json \
  --commands hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/arlan_serval_natasha_two_waves.commands.json \
  --output /tmp/hsr-two-waves.json.gz
PYTHONPATH=hsr_v075_baseline_clean .venv/bin/python -B -m hsr.simulator_v8_clean_core.cli replay /tmp/hsr-two-waves.json.gz
```

后续怪物现在复用首波的被动执行器，出生通知各一次；被动失败则整波零提交。
扩散伤害主目标死亡但尚未移除时，其位置仍能作为后续邻位查询的参照，死亡单位不能被重新选为攻击目标。
本路线在敌人行动前清怪；枪兵自然施加裂伤及下一回合扣血已在另一条定向路线通过，
尚未据此验证该两波路线中的全部交互。
这证明正式换波和限定整场可用，不表示银鬃兵全部动作或完整关卡已完成；当时的限制见[历史缺口记录](docs/archive/checkpoints/MVP_KNOWN_GAPS_2026-09-28.md#验证缺口与内容范围不是新规则问题)，当前范围以[交接](../CODEX_HANDOFF.md)为准。

两波自然交战样例 `arlan_melee_two_waves` 使用阿兰 Lv80、希露瓦/娜塔莎 Lv1，均 E0 空装备。
浏览器选择“三人队 · 两波近战兵交战”。阿兰战技优先击败枪兵，另外两人普攻近战兵；敌方
近战兵攻击阿兰，同速时先选左侧近战兵，不请求终结技。共 19 次选择提交，近战兵自然攻击
4 次后胜利，覆盖受击回能、两回合减防及再次施加。配套脚本可直接运行：

```bash
PYTHONPATH=hsr_v075_baseline_clean .venv/bin/python -B -m hsr.simulator_v8_clean_core.cli run \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/arlan_melee_two_waves.json \
  --commands hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/arlan_melee_two_waves.commands.json \
  --output /tmp/hsr-melee-two-waves.json.gz
```

距离条件本身没有被伪造为真或假；编译器只接纳两个分支均为已证明的表现任务、同步标记顺序
相同的来源形状，完整保留两分支审计数据。涉及战斗效果的距离分支仍拒绝执行。

## 阿兰一魂构筑对照（2026-10-11）

阿兰 E0/E1、1 级、空装备对两只 2 级重子的整场均已通过。一魂在伤害前 HP 不高于 50%
且使用战技时，向伤害加成加入来源中的 0.1；高血量战技和终结技不获得这一项。
构筑选择、参数读取、条件回调和正式伤害结算已经贯通，不依赖手填伤害答案。

可复制 `arlan_vs_antimatter.json`，将角色与 `character_build` 两处 `eidolon_level` 改为 `1`，
删除原 `character_build.input_fingerprint` 后使用 `play`；新指纹由构筑入口计算。
保留的对照检查自动选择合法操作并生成零魂、一魂两份归档：

```bash
.venv/bin/python -B -m pytest -s -m integration \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_eidolon_source_branches.py
```

一魂归档独立 CLI 回放 19 步零错误；来源身份损坏时整次战技零 mutation/RNG，状态不变。
本批没有击破，也不代表更高星魂、额外行迹或装备组合已全部可用。

## 娜塔莎额外星魂启动与受击（2026-10-11）

浏览器加载“阿兰＋娜塔莎”场景，将娜塔莎星魂改为 4 后开战；保持 1 级、空装备。
阿兰只普攻，先击败第一只敌人再攻击第二只；娜塔莎用战技治疗阿兰，敌人都攻击娜塔莎，
本条对照不请求终结技。自然受击五次后，娜塔莎降至约 27.0474 HP，一魂排入自疗并移除
自身检查状态；恢复至 158.4 满血，最后阿兰普攻击败剩余敌人。

四魂在受击后从正式星魂参数读取 5 点额外回能，与基础 10 点一起结算；到达能量上限时截断。
这些能力由已选构筑的真实 `OnStart` 来源启动，再走共享状态回调、插入队列和治疗执行链。
零魂不挂载一魂/四魂状态，一魂只挂载一魂状态；此验收不代表全部星魂或行迹已完成。

检查会生成这条路线的标准归档，可按前文 CLI `replay` 独立校验：

```bash
.venv/bin/python -B -m pytest -s -m integration \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_character_build_startup.py
```

## 仙舟两件套与速度鞋（2026-10-11）

浏览器选择“阿兰 · 仙舟两件套与速度鞋”，或使用 CLI `play` 打开
`examples/cli/arlan_fleet_vs_antimatter.json`。这是阿兰 E0 / 1 级、仙舟两件套加 15 级速度鞋、
无副词条的已完成成品构筑，不模拟强化过程；两件仙舟主词条均为 0 级生命百分比。
正式装配速度为 `127.032`，入场只获得一份 `0.08` 攻击力百分比增益。
阿兰持续用战技攻击候选列表第一只存活敌人，敌人攻击阿兰，可完成胜利。

定向检查另外对照去掉速度鞋的正式入场，并用明确标注的边界状态验证速度从 `119.999` 到 `120`
时增益撤销/恢复、同区间重复检查不重复施加。这个边界状态检查不是游戏实测，也不写进整场归档。
`OnlyRemoveCasterAdded` 按状态实例的正式 caster 身份过滤，不会移除其它施加者的同名状态。

```bash
.venv/bin/python -B -m pytest -s -m integration \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_equipment_battle.py
```

整场使用未经手工修改的出生状态，输出标准归档供独立 CLI 回放。224 个装备能力图中，
本次修复 7 个编译/查询阻断，仍有 6 个依赖缺省公式、行动延迟运算或快照事件的图保留阻断；
这不是全部装备已完成实战验收。当时的限制见[历史机制缺口](docs/archive/checkpoints/MVP_KNOWN_GAPS_2026-09-28.md#2026-10-11-装备能力查询与保留阻断)，当前范围以[交接](../CODEX_HANDOFF.md)为准。

## 普通败北与敌方回合终结技对照（2026-10-10）

沿用 `arlan_vs_antimatter.json` 的正式构筑、零初始能量及双方合法动作查询。
先对两只敌人各普攻一次，再用战技击败其中一只；自然回能到 110 后，不插入终结技会被
剩余敌人击败，在其回合插入终结技则能获胜。敌方同速选择也由外部提交，不使用 AI 序列。
非法目标、非当前行动者及结束后的继续提交均不产生 mutation/RNG，状态不变。
这两条路径不发生击破，不扩大到任意构筑或特殊死亡内容。

保留的检查会各生成一份归档，随后按前文 CLI `replay` 命令在独立进程验证：

```bash
.venv/bin/python -B -m pytest -s -m integration \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_cli_content_scope.py \
  -k external_target_order
```

本次两项检查通过；两份归档的独立 CLI 回放分别为败北 24 步、胜利 26 步，均零错误。

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
当前 RNG 使用真实执行身份，来源目录指纹不参与抽样。本次两次感电 roll 为 `0.388628`、
`0.480830`，均低于 `0.8` 阈值；天赋追加伤害只结算实际感电的目标。检查核对 roll、阈值和状态
结果，不固定成功/失败组合，也不把基础概率当成必然。
它复用现有角色机制，验证同队执行时的目标、资源和状态归属；不扩大到未验收构筑。
固定脚本的来源场景检查通过，独立 CLI 回放返回 `ok=true, step_count=39, errors=[]`。
此前验证基线为归档约 411 KB、生成 162.53 秒、独立回放 171.83 秒；旧规则指纹归档不兼容。
本轮编译修复后重新生成归档，并通过 39 步独立回放；与 Kafka 来源阻断检查合计 208.10 秒。

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

`battle_setup.metadata.stage_scope="wave_only"` 明确表示只采用该关卡的怪物波次。它不是主线关卡复刻，不加载关卡模板中的全局能力（包括 `StageAbility_Elation`）。UI 入口见前文，不模拟养成过程或敌方 AI。

`stage_scope="full_stage"` 则编译并装配所选关卡的环境依赖；启动顺序沿用关卡模板，
监听器先于单位出生安装，关卡自身入场通知只派发一次。仅编译所选内容，不展开全目录。
当前已贯通普通 `StageCommonTemplate` 的公共环境路线；特殊模板、评分、副关卡、
额外胜负条件和实际触发的未知规则分别拒绝。关卡目录存在或静态准入不等于全部玩法可用。
敌人面板同时应用正式难度组与精英组倍率，缺失或冲突的倍率来源拒绝装配。

尚未确认的战斗机制不得用估值补齐。超出已准入内容的构筑、任务、目标或上下文会返回具体阻断原因；失败的正式动作不会提交部分状态。支持范围以实际贯通验证为准，不能用静态数据卡数量代表可玩的角色数量。

2026-09-28 的初始 MVP 范围是一个确定配置和操作路径能够完整结束、保存并回放的命令行战斗，
已由阿兰对两只重子的场景达到。此后用户要求继续推进工程完结路线，当前范围以 `CODEX_HANDOFF.md`
为准；不能以初始雏形通过代表工程完成。虚韧性等特殊韧性机制和特殊韧性计数仍保留缺口。
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
  2026-10-10 用户确认致死命中仍回能，已移除该阻断；正常败北及敌方回合插入终结技的对照路线
  通过正式 `BattleSession`，不代表任意构筑或特殊死亡流程都已可用。
- CLI 已支持限定两波路线，后续怪物复用正式被动出生流程；所选普通关卡公共环境已有
  `full_stage` 整场证据，特殊环境依赖仍单独阻断。当前没有通用全内容支持声明。

已确认 PR #8 的普通规则直接作为实现依据；未找到 native 赋值位置不构成拒绝已确认公式的理由。
上述保留项分别记录具体规则依据或执行链的缺口；明确延期项不作为本轮 MVP 验收阻断。

检查以真实行为为目的：运行示例战斗并独立回放，对受击回能、多盾、击破、状态/随机调用保留必要行为
正例。不以覆盖率、全量检查数量或重复验证内核已拒绝的非法输入作为交付目标。

2026-09-28 本地实跑结果：内置九次操作得到 `victory`，阿兰剩余 HP `5.25078`、能量 `15`，
两只重子 HP 均为零。独立 CLI replay 返回 `ok=true, step_count=19, errors=[]`。
最终源码下的本轮归档在 `/tmp/hsr-mvp-pr8-shared-final-20260928.json.gz`；运行和回放日志分别为
`/tmp/hsr-mvp-pr8-shared-final-20260928-run.log`、
`/tmp/hsr-mvp-pr8-shared-final-20260928-replay.log`。

当时逐项边界见[历史缺口清单](docs/archive/checkpoints/MVP_KNOWN_GAPS_2026-09-28.md)；当前机制与内容边界见[交接](../CODEX_HANDOFF.md)。

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

## 查询逐内容支持与阻断矩阵

```bash
PYTHONPATH=hsr_v075_baseline_clean .venv/bin/python -B -m hsr.simulator_v8_clean_core.cli support \
  > /tmp/hsr-content-support.json
PYTHONPATH=hsr_v075_baseline_clean .venv/bin/python -B -m hsr.simulator_v8_clean_core.cli support \
  --kind character --kind character_action > /tmp/hsr-character-support.json
PYTHONPATH=hsr_v075_baseline_clean .venv/bin/python -B -m hsr.simulator_v8_clean_core.cli support \
  --scenario hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/arlan_vs_antimatter.json \
  --kind character_build > /tmp/hsr-selected-build-support.json
```

默认复用来源预处理器一次汇总角色、动作、行迹、星魂、怪物、光锥、遗器和关卡；不构造完整
Canonical IR，不逐卡编译或执行战斗。`--scenario` 额外加载所选规则一次，汇入正式构筑装配及
按已选星魂/行迹剪枝的动作静态准入。来源扫描仍有成本，同一网页服务只在首次请求目录时执行
并缓存；推荐使用 `/api/battle/content-support?kind=character` 或 `?content_id=avatar_skill:100801`
筛选，避免默认传输约 49 MiB 的完整目录。

`source_status` 仅表示注明范围的来源结构/绑定检查；`known_source_gaps` 可能是编译表达或接线
缺口，不等于游戏机制未知。`formal_status` 只覆盖当前提供的正式 IR；每条检查保留原因和来源，
未加载内容保持 `unchecked`。构筑装配通过不证明其全部技能、入场或关卡环境可用。
`execution_evidence` 将已有示例标为 `example_available_not_verified`，不凭文件存在宣称实战通过。
关卡环境准入与普通波次来源检查分别报告；未选择编译环境时保持 `unchecked`。
可用 `--content-id` 精确查询；筛选后的
`summary` 仍对应全目录，`rows` 只保留筛选结果，不给出成品完成率。
