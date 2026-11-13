# 游戏数值对照记录（M1-4 固定格式）

正确性判据见 [PROJECT_GOALS.md](../../PROJECT_GOALS.md#数值一致)：模拟数值与游戏实测或成熟计算器
一致，默认相对误差 ≤1%（或落在游戏显示取整范围内）；行动顺序、目标、触发次数、状态层数必须一致。
对照值只用于检验，不写成规则、修正项或固定答案。取不到对照值的条目标"未对照"，不计入完成。

## 记录格式

每个名单条目至少一份记录，存 `records/<id>.yaml`。字段：

| 字段 | 内容 |
| --- | --- |
| id | 条目身份 + 序号，如 m1-arlan-e0-lv1-vs-antimatter-minions-001 |
| game_version | 对照值适用的游戏版本；版本不明时如实记录 |
| data_version | TBGD submodule 固定提交哈希 |
| simulator_version | Git 提交 + engine_rule 版本 + rules_fingerprint（IR 内容指纹）+ scenario 版本；已有记录中的旧指纹字段保留为历史证据 |
| build | 角色、等级、星魂、晋升、行迹、光锥、遗器（完整构筑输入） |
| target | stage、wave、怪物身份、怪物等级、难度组 |
| operations | 公开操作序列（advance/submit 口径） |
| rng | RNG 模式与影响对照值的各 roll（暴击判定等作为给定输入时注明） |
| reference_values | 逐事件对照值：事件、值、来源、independent 标记（参数是否独立于模拟器核对） |
| tolerance | max_relative_error、actual、verdict（PASS/FAIL/未对照） |
| sources | 来源 URL/文献 + 结论 + 适用版本；TBGD 参数注明文件与行 |
| unverified_params | 未独立核对的参数，如实列出 |
| notes | 实现路径差异、分段口径、已知例外 |

## 规则

- `rules_fingerprint` 不使用本机缓存键，不包含部署路径、文件系统时间戳或 Python 版本；相同 IR 内容可跨机器复现。它不代替代码版本，因此同时记录 Git 提交。历史记录保留当时的版本与指纹，不能把新指纹填回旧实验记录。
- **最终对照值来源只有两类：游戏实测、成熟计算器输出**（PROJECT_GOALS 数值一致定义）。
  资料公式 + 独立来源参数复算只是**公式一致性验证**：它证明实现与公认公式一致，
  不能替代游戏对照，不能据此标记条目"数值已对照"。复算记录保留为中间证据，
  条目完成仍需补一组明确构筑的外部输出（实测或成熟计算器）。
- 用公式复算时，公式与参数都必须注明独立来源；只有公式独立而参数取自模拟器时，
  该参数标 independent: false 并列入 unverified_params。
- 多段伤害按"段"记值，不记动作总额。
- 记录由公开路线归档支撑：归档路径或可复现命令写入 notes；归档本身留 /tmp 或
  live_validation_reports，不复制大体积输出进本目录。
- 调研过程报告存 reports/，作为记录的来源证据；记录本身保持精简。

## 现有记录

| 记录 | 条目 | 判定 |
| --- | --- | --- |
| [m2-ordinary-stage-waves-lv10-001](records/m2-ordinary-stage-waves-lv10-001.yaml) | 来源波次、普通full_stage（两项） | 两波承伤 PASS；插队清场后换波通过，跨波行动顺序边界待实测 |
| [m2-academic-rumors-anchor-001](records/m2-academic-rumors-anchor-001.yaml) | 锚点上下半场及当期增益 | 双半场累计20轮通关；终结技增伤独立对照PASS；四人性能仍不达标 |
| [m2-jingyuan-e0-lv80-lord-001](records/m2-jingyuan-e0-lv80-lord-001.yaml) | 景元及固定构筑（两项） | 普攻独立对照PASS；秘技、神君加段/加速/相邻伤害与重置通过；分段回能时序待实测 |
| [m2-topaz-e0-lv80-numby-001](records/m2-topaz-e0-lv80-numby-001.yaml) | 托帕与账账及固定构筑（两项） | 普攻独立对照PASS；自动负债、80速度、强化次数与标记转移通过；补标记窗口待实测 |
| [m2-lingsha-e0-lv80-fuyuan-001](records/m2-lingsha-e0-lv80-fuyuan-001.yaml) | 灵砂及固定构筑（两项） | 普攻独立对照PASS；90速浮元、次数封顶5、治疗、应急追击、耗尽退场与再召唤通过；最后行动边界待实测 |
| [m2-danhengpt-e0-lv80-dragon-001](records/m2-danhengpt-e0-lv80-dragon-001.yaml) | 丹恒·腾荒及固定构筑（两项） | 普攻独立对照PASS；165速龙灵、同袍转移、强化消耗、附伤与叠盾通过；上限下降边界待实测 |
| [m2-aglaea-e0-lv80-joint-001](records/m2-aglaea-e0-lv80-joint-001.yaml) | 阿格莱雅及固定构筑（两项） | 三段普攻独立对照PASS；连携、倒计时、退场与重召保留速度层数通过；自毁边界待实测 |
| [m2-memory-e0-lv80-support-001](records/m2-memory-e0-lv80-support-001.yaml) | 记忆开拓者及固定构筑（两项） | 普攻独立对照PASS；充能、支援拉条、真伤、史诗耗尽、治疗及被击倒重召通过 |
| [m2-hyacine-e0-lv80-healing-001](records/m2-hyacine-e0-lv80-healing-001.yaml) | 风堇及固定构筑（两项） | 普攻独立对照PASS；治疗、小伊卡额外行动与持续回合通过；满血/溢出累计边界标未实证，须游戏实测 |
| [m2-evernight-e0-lv80-night-001](records/m2-evernight-e0-lv80-night-001.yaml) | 长夜月及固定构筑（两项） | 普攻独立对照PASS；忆灵治疗、强化退场重召、充能耗尽后退出通过；倒下队友计数须游戏实测 |
| [m2-castorice-e0-lv80-netherwing-001](records/m2-castorice-e0-lv80-netherwing-001.yaml) | 遐蝶及固定构筑（两项） | 普攻独立对照PASS；强化、连续吐息、终结、三回合到期、重召及多段锁血通过；整链监听时序须游戏实测 |
| [m2-envoy-lv66-received-damage-001](records/m2-envoy-lv66-received-damage-001.yaml) | 金人勾魂使 | 承伤 PASS；震荡、锁定时序带“未实证”标记，待游戏实测 |
| [m2-trampler-lv40-received-damage-001](records/m2-trampler-lv40-received-damage-001.yaml) | 虚卒·践踏者 | 承伤 PASS；五技能、纠缠叠层及到期路线通过；共享受击时序待实测 |
| [m1-arlan-e0-lv1-vs-antimatter-minions-001](records/m1-arlan-e0-lv1-vs-antimatter-minions-001.yaml) | 阿兰基线路线（M1 方法验证，非名单条目交付） | 公式一致性 PASS（7/7 误差 0%）；游戏对照待外部输出 |
| [m2-arlan-e0-lv80-p6-full-traces-102-302-23002-001](records/m2-arlan-e0-lv80-p6-full-traces-102-302-23002-001.yaml) | M2 阿兰条目（80 级满行迹构筑） | 历史公式一致性 PASS（8/8 误差 0%）；不回填新证据。雷击破旧路线已恢复，名单构筑的击破仍待收口 |
| [m1-arlan-e0-lv80-fullhp-fribbels-001](records/m1-arlan-e0-lv80-fullhp-fribbels-001.yaml) | M1-4 外部对照方法，复用 M2 阿兰构筑 | 满血普攻两段与成熟计算器原生输出对照 PASS，误差0.000203%；面板一致；当前外部计算器的损血天赋不适用，详见记录 |
| [m2-natasha-e0-lv80-23013-101-302-001](records/m2-natasha-e0-lv80-23013-101-302-001.yaml) | 娜塔莎及23013/101/302构筑 | 战技/终结技直接治疗对照 PASS，误差0.0002375%；面板一致，低HP增疗不在外部模型范围内 |
| [m2-serval-e0-lv80-20006-102-302-001](records/m2-serval-e0-lv80-20006-102-302-001.yaml) | 希露瓦及20006/102/302构筑 | 普攻、战技主目标、终结技首次直伤对照 PASS，最大误差0.0002269%；DOT/附伤未外推 |
| [m2-march-e0-lv80-20003-103-304-001](records/m2-march-e0-lv80-20003-103-304-001.yaml) | 存护三月七及20003/103/304构筑 | 满血、40%HP护盾对照 PASS，覆盖琥珀分支，最大误差0.000000912% |
| [m2-pela-e0-lv80-20004-102-302-001](records/m2-pela-e0-lv80-20004-102-302-001.yaml) | 佩拉及20004/102/302构筑 | 两段普攻、驱散后的追歼终结技对照 PASS，最大误差0.000180%；保留真实减防与未击破目标条件 |
| [m2-asta-e0-lv80-20005-102-302-001](records/m2-asta-e0-lv80-20005-102-302-001.yaml) | 艾丝妲及20005/102/302构筑 | 首个普攻与面板对照 PASS，误差0.000168%；五段命中、实际逐段回能与速度增益另有公开路线检查 |
| [m2-danheng-e0-lv80-20000-102-302-001](records/m2-danheng-e0-lv80-20000-102-302-001.yaml) | 丹恒及20000/102/302构筑 | 普攻两段、穿透战技首段、减速目标终结技 PASS，最大误差0.000193% |
| [m2-lynx-e0-lv80-20008-101-302-001](records/m2-lynx-e0-lv80-20008-101-302-001.yaml) | 玲可及20008/101/302构筑 | 终结技与持续治疗对照 PASS，误差0.000276%；真实减防净化、残血救援与生存反应另有公开路线检查 |
| [m2-seele-enhanced-e0-lv80-20000-102-302-001](records/m2-seele-enhanced-e0-lv80-20000-102-302-001.yaml) | 增强版希儿及20000/102/302构筑 | 普攻两段、强化终结技对照 PASS，最大误差0.000212%；未混用原版模型 |
| [m2-basic-enemies-lv40-received-damage-001](records/m2-basic-enemies-lv40-received-damage-001.yaml) | 重子、反重子、银鬃近卫、银鬃射手 | 四种承伤对照 PASS，误差0.000000852%；各自普通动作可执行，不外推为敌方输出的独立对照 |
| [m2-lieutenant-lv44-received-damage-001](records/m2-lieutenant-lv44-received-damage-001.yaml) | 银鬃尉官 | 承伤对照 PASS，误差0.000001633%；四主动动作、反击和两名召唤近卫行动通过 |
| [m2-weaver-lv76-received-damage-001](records/m2-weaver-lv76-received-damage-001.yaml) | 虚数织叶者 | 承伤对照 PASS，误差0.00000357%；扩散、强化三段、增益消耗和被动准入通过 |
| [m2-prowler-lv44-received-damage-001](records/m2-prowler-lv44-received-damage-001.yaml) | 深寒徘徊者 | 承伤对照 PASS，误差0.000001633%；六主动技能、两次吸收、深寒三层和过热恢复通过 |
| [m2-guardian-lv40-received-damage-001](records/m2-guardian-lv40-received-damage-001.yaml) | 守护者之影 | 承伤对照 PASS，误差0.000000852%；三禁令、反击、先净化和八段雷暴/显式随机分支通过 |
| [m2-aurumaton-lv70-received-damage-001](records/m2-aurumaton-lv70-received-damage-001.yaml) | 金人司阍 | 承伤对照 PASS，误差0.000004181%；自然惩戒、双行动、两回合持续时间、虚弱、禁锢与召唤路线通过 |
