# 第一组游戏数值对照调研报告（M1 阿兰基线路线）

日期：2026-11-11　调研子代理　工作目录 /home/zhangjinhao/code/hsr
归档：/tmp/m1-baseline-20261111.json.gz（hsr_battle_archive_v2 对象图外壳，内层 schema hsr_battle_session_v2）
场景：mvp:arlan-e0-lv1-vs-antimatter-minions，stage 200020050 波次 0，outcome=victory，9 条正式命令 + 10 个自动决策点。

## 0. 结论摘要

- **全部 7 次伤害事件（3 次战技、3 次敌方攻击、1 次终结技首段）用独立来源参数 + 社区公认公式复算，与模拟器结算值逐位一致，相对误差 0%**；终态 HP 也完全一致。用社区取整 DEF=220 代替 TBGD 精确值 219.99999 时误差仅 2.3×10⁻⁶%，远小于 1% 容差。
- 模拟器防御区公式 **与 Prydwen / 英文 wiki / 17173 等权威来源一致**：DEF乘区 = 1 − DEF/(DEF + 200 + 10×攻击者等级)。代码中 engine_convention 标签"pending an admitted raw formula source"可以升级为正式引用这些来源。
- 未破韧 10% 减伤：模拟器经 TBGD 的 MonsterAllDamageReduce 状态（damage_reduction 桶 ×0.9）实现，toughness_state 乘数 1.0，**与社区"破盾乘区 0.9"数值等价、无重复计算**。
- **任务前提修正：归档中没有普攻**。9 条命令 = 战技×3 + 平局选择×1 + 敌方攻击×3 + 终结技排队×1 + 终结技执行×1。"第一次普攻伤害"无法从本归档提取；普攻参数已独立核对（Lv1 总倍率 50%，2 段 0.3/0.7），并给出假设性复算值供后续路线使用。
- 阿兰战技**不消耗战技点**（游戏特殊机制，fandom/KQM/biligame 多源确认），模拟器 SP 恒为 3 是正确的，不是 bug。

## 1. 归档提取的输入表

### 1.1 阿兰入场最终面板（avatar 1008，Lv1，E0，晋升0，无行迹/光锥/遗器）

| 属性 | 值 | 独立来源核对 |
|---|---|---|
| ATK | 81.6 | TBGD AvatarPromotionConfig 1008 P0：AttackBase 81.6 + AttackAdd 4.08×(1−1) ✓ |
| DEF | 45 | 同上 DefenceBase 45 ✓ |
| HP | 163.2 | 同上 HPBase 163.2 ✓ |
| SPD | 102 | 同上 SpeedBase 102 ✓ |
| 暴击率 | 5% | 同上 CriticalChance 0.05 ✓ |
| 暴击伤害 | 50% | 同上 CriticalDamage 0.5 ✓ |
| 能量 | 0/110 | TBGD 100803 SPNeed 110 ✓ |
| 增伤/易伤/穿透等 | 全 0 | 无装备无行迹 ✓ |
| 天赋（100804 Lv1，默认解锁非行迹） | 每损失 1% HP 增伤 0.36%（上限 36%） | TBGD ParamList[0]=0.36；biligame"至痛至怒"LV1 上限 36.0%；honkailab"up to 36%" ✓ |

### 1.2 敌方（monster 8011010 反重子 ×2，Lv2，stage 200020050，HardLevelGroup 1，EliteGroup 1）

| 属性 | 值 | 独立来源核对 |
|---|---|---|
| 等级 | 2 | TBGD StageConfig 200020050 Level=2 ✓ |
| HP | 58.59 | MonsterTemplateConfig HPBase 55.8 × HardLevelGroup(1,2) HPRatio 1.05 ✓ |
| ATK | 13.803966 | AttackBase 18 × AttackRatio 0.766887 ✓ |
| DEF | 219.99999（≈220） | DefenceBase 210 × DefenceRatio 1.047619 ✓；社区公式 200+10×2=220 ✓ |
| SPD | 83 | SpeedBase 83 × 1 ✓ |
| 韧性 | 30 | StanceBase 30 ✓ |
| 雷抗 | 20% | MonsterConfig DamageTypeResistance：非弱点属性全 0.2；弱点 Ice/Wind ✓（Prydwen：无弱点基础 20% 抗） |
| 未破韧减伤 | 10%（AllDamageReduce） | TBGD Monster_Common_Ability OnStart 添加 MonsterAllDamageReduce；GlobalModifier_Common_Specific 定义 StackProperty AllDamageReduce=0.1；OnBeingBreak 移除 ✓ |
| 技能 | 801101001，250% ATK，量子，Normal | TBGD MonsterSkillConfig ParamList[2.5]、DamageType Quantum ✓ |

敌方属性公式（TBGD 装配链）：模板基础值 × HardLevelGroup(组,等级) 系数 × EliteGroup 系数（组1全1.0）× MonsterConfig ModifyRatio（全1.0）。

### 1.3 动作倍率（全部 TBGD + wiki 双核对）

| 动作 | Lv1 参数 | 来源 |
|---|---|---|
| 普攻 100801 | 总 50% ATK，2 段（0.3/0.7），回能 20，削韧 30，产 1 战技点 | TBGD ParamList[0.5]、BPAdd 1、SPBase 20；ability 2 段；fandom"50%—110%，2 hits"；biligame LV1 50.0% |
| 战技 100802 | 耗 15% 上限 HP（不足降至 1），120% ATK 单体雷，回能 30，削韧 60，**不耗战技点** | TBGD ParamList[0.15,1.2]、SPBase 30、无 BPNeed；ability LoseHPByRatio(Floor=1) 先于 DamageByAttackProperty；fandom/KQM/biligame 确认不耗 SP |
| 终结技 100803 | 主目标 192%（3 段 0.3/0.1/0.6 → 57.6%/19.2%/115.2%），相邻 96%，耗能 110，回能 5，削韧 60+60 | TBGD ParamList[1.92,0.96]、SPNeed 110、SPBase 5；ability 分段系数；biligame 192%/320%、96%/160% |
| 天赋 100804 | 0.36%/1% 损失 HP | 见上 |

### 1.4 归档伤害结算明细（operations[奇数].transition.settlement.records 中 record_type=damage）

| op | 动作 | 目标 | 暴击(RNG roll) | 倍率 | 增伤桶 | 防御桶 | 抗性桶 | 减伤桶 | 结算值 | 目标HP变化 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 战技#1 | pos0 | 是(0.01537<0.05) | 1.2 | ×1.054 | ×0.48837210438 | ×0.8 | ×0.9 | **54.436052019443075** | 58.59→4.1539 |
| 5 | 敌攻#1 | arlan | 否(0.8096) | 2.5 | ×1 | ×0.83018867925 | ×1 | ×1 | 28.649740754716984 | 138.72→110.07 |
| 7 | 敌攻#2 | arlan | 否(0.3067) | 2.5 | ×1 | 同上 | ×1 | ×1 | 28.649740754716984 | 110.07→81.42 |
| 9 | 战技#2 | pos0 | 否(0.1951) | 1.2 | ×1.23439591509 | 同上 | ×0.8 | ×0.9 | **42.501986240773874** | 4.1539→0（击杀） |
| 11 | 敌攻#3 | arlan | 否(0.6375) | 2.5 | ×1 | 同上 | ×1 | ×1 | 28.649740754716984 | 56.94→28.29 |
| 13 | 战技#3 | pos1 | 否(0.6808) | 1.2 | ×1.35159387264 | 同上 | ×0.8 | ×0.9 | 46.53727663521425 | 58.59→12.0527 |
| 17 | 终结技首段 | pos1 | 否(0.2448) | 0.576(=1.92×0.3) | ×1.35159387264 | 同上 | ×0.8 | ×0.9 | 22.337892784902838 | 12.0527→0（胜利） |

pipeline 阶段顺序：base(ATK×倍率) → critical → damage_bonus → defense → resistance → damage_taken(易伤) → damage_reduction → toughness_state(未破韧=1.0)。
增伤桶数值 = 天赋 0.36×损失HP百分比（战技耗血后取值）：op1 损失15%→5.4%；op9 损失65.11%→23.44%；op13/op17 损失97.66%→35.16%。
op15 为终结技排队（queue_enqueue，能量已达110），op17 为出队执行；终结技主目标 3 段中首段即击杀，后 2 段无目标。
防御桶引擎规则：one_minus_effective_defense_over_effective_defense_plus_flat_base_plus_level_coefficient_times_attacker_level，flat_base=200，coefficient=10。

## 2. 来源清单（URL + 结论 + 版本适用性）

### 2.1 伤害公式

| # | 来源 | URL | 结论 | 版本 |
|---|---|---|---|---|
| F1 | Prydwen Damage Formula | https://www.prydwen.gg/star-rail/guides/damage-formula | 总公式=Base×DMG%×DEF×RES×DMG Taken×Universal Reduction×Weaken；**DEF乘区=1−DEF/(DEF+200+10×攻击者等级)**；DEF=BaseDEF×(1+DEF%−减防−无视防)+_flat；RES=1−(RES−PEN)，无弱点基础20%、弱点0%、抗性强敌40%；**有韧性未击破=10%通用减伤，击破后0%，与其他减伤乘算**；基于 theorycrafter arkkus 文档 | 长期有效，页面现行 |
| F2 | HSR 英文 wiki（fandom）Damage | https://honkai-star-rail.fandom.com/wiki/Damage | DEF Multiplier=1−DEF/(DEF+200+10×LevelAttacker)（搜索快照确认；直接 fetch 被 404 拦截，如实记录） | 现行 |
| F3 | 17173 伤害与速度公式汇总 | https://news.17173.com/content/08122024/160903756.shtml | 防御乘区=1−敌DEF/(敌DEF+攻击者等级×10+200)；**敌DEF=敌等级×10+200**；破盾乘区未破0.9/已破1.0；抗性弱点1.0/非弱点0.8；暴击=1+爆伤；易伤=1+易伤；增伤=1+增伤；减防与无视防等价 | 2024-08-12 |
| F4 | 17173 欢愉乘区计算公式 | https://news.17173.com/content/04012026/095051478.shtml | 防御区=(200+攻方等级×10)/[(200+攻方等级×10)+(200+受击方等级×10)×(1−减防−无视防)]（敌方DEF=200+10×等级代入） | 2026-04-01（4.x） |
| F5 | 17173 遐蝶数据帖 V3.2 | https://news.17173.com/content/04212025/143603219.shtml | 同 F4 防御区公式 | 2025-04-21（V3.2） |
| F6 | JSCalc HSR DPS Calculator | https://jscalc-blog.com/hsr-dps-calculator/ | 实例 Lv80 vs Lv85 防御区 0.488×（=1−1050/2050，敌DEF=200+10×85）；含未破韧10%减伤开关 | 现行 |

**等级压制说明**：直伤没有独立"等级压制"乘区；攻击者等级通过防御区 (200+10×等级) 起作用，敌方等级通过敌方 DEF=200+10×等级 起作用（F1/F3/F4 一致）。
**公式一致性**：F1–F6 全部与模拟器 engine_convention 一致。注意早期个别社区帖曾流传 (20+20×等级) 变体，本次调研未在任何现行权威来源中找到该式，不予采用。

### 2.2 敌方 DEF/等级公式

- 社区式：敌DEF=200+10×敌等级（F3/F4/F5/F6）。
- TBGD 装配式（本地原始数据，commit 14c1d18f91a8101d610e6c523447a7517de3fae1，Dimbreath/StarRailData 固定提交 submodule）：MonsterTemplateConfig.DefenceBase(=200+10×1) × HardLevelGroup.DefenceRatio。Lv2：210×1.047619=219.99999≈220，与社区式一致（浮点尾差 1e-5 量级）。
- 敌方等级来源：StageConfig.Level（200020050→2）。

### 2.3 阿兰倍率可核对来源

| 来源 | URL | 结论 |
|---|---|---|
| biligame wiki 阿兰 | https://wiki.biligame.com/sr/阿兰 | 普攻 LV1 50.0%；战技 LV1 120.0%（耗15%HP、回能30、耗战技点0）；终结技 192%/96%（耗能110回5）；天赋"至痛至怒"LV1 增伤上限 36.0%（=0.36%/1%）。页面更新 2025-06-04 |
| fandom Arlan/Combat | https://honkai-star-rail.fandom.com/wiki/Arlan/Combat | 普攻 50%—110%，2 hits；战技 120%—264%（搜索快照；fetch 404） |
| fandom Shackle_Breaker | https://honkai-star-rail.fandom.com/wiki/Shackle_Breaker | "does not consume Skill Points"（搜索快照） |
| fandom Lightning_Rush | https://honkai-star-rail.fandom.com/wiki/Lightning_Rush | 1:50% 2:60% … 7:110%（搜索快照） |
| KQM Arlan | https://srl.keqingmains.com/characters/lightning/arlan ；https://hsr.keqingmains.com/arlan/ | 技能名/回能20/削韧30；"Arlan does not spend SP with his Skill" |
| honkailab | https://honkailab.com/characters/arlan-build/ | 天赋"up to a max of 36% more DMG"（Lv1） |
| TBGD（本地） | turnbasedgamedata-main/ExcelOutput/AvatarSkillConfig.json 行 100801/100802/100803/100804；Config/ConfigAbility/Avatar/Avatar_Arlan_00_Ability.json | 全部倍率、分段系数（普攻0.3/0.7；终结技主0.3/0.1/0.6）、耗血先于伤害、SP/能量参数 |

### 2.4 成熟计算器（可否程序化使用）

| 计算器 | URL | 输入能力 | 使用方式 |
|---|---|---|---|
| JSCalc HSR DPS Calculator | https://jscalc-blog.com/hsr-dps-calculator/ | 最终ATK、技能倍率、增伤%、减防/无视防、敌等级、RES(穿透后)、易伤%、未破韧开关、暴击率/爆伤 | 静态页客户端 JS，**浏览器手动**；无公开 API；公式可从页面 JS 提取 |
| GameVika HSR Damage Calculator | https://gamevika.com/en/hsr/damage | 角色面板、技能倍率、敌方信息 | 静态页，**浏览器手动** |
| HSR-Analysis（Tommhy0） | https://github.com/Tommhy0/HSR-Analysis | 4.6 数据快照、遗器编辑、单次伤害/四人战斗；按技能总倍率与逐项重复次数计算 | 离线 HTML 或本地 Node 服务（127.0.0.1:8777），**浏览器手动**；AGPL-3.0；自述"可运行不代表所有机制精确复现" |
| starrail_damage_cal | https://pypi.org/project/starrail_damage_cal/ （最新 4.6.0） | Python 伤害计算库 | **可编程 API**（import 调用）；需 pip 安装——本会话约束不装依赖，未实际使用，仅列为候选 |

### 2.5 访问受限记录

- honkai-star-rail.fandom.com 直接 web_fetch 一律 HTTP 404（fetch 后端被拦），改用 web_search 快照核对，关键数值均获得快照证据。
- 未遇到付费墙。

## 3. 独立复算过程与误差

公式（F1/F3）：DMG = ATK×倍率 × (1+增伤) × (暴击?1+爆伤:1) × [1−DEF/(DEF+200+10×攻方等级)] × (1−抗性+穿透) × (1+易伤) × (1−减伤)。
未破韧减伤 0.9 采用 F1 的 Universal DMG Reduction 表述（与 TBGD MonsterAllDamageReduce 等价）。
参数全部取自 §1 的独立来源；暴击/非暴击结果按归档 RNG 判定作为给定输入（RNG 算法本身未独立核对，见 §5）。

### 3.1 第一次战技（op1，暴击）

- 基础 = 81.6×1.2 = 97.92
- 耗血后 HP = 163.2×0.85 = 138.72，损失 15% → 增伤 ×(1+0.36×0.15) = ×1.054
- 暴击 ×1.5 → 146.88×1.054 = 154.81152
- 防御 ×[1−219.99999/(219.99999+200+10×1)] = ×0.48837210438 → 75.60562780478
- 抗性 ×0.8 → 60.48450224383；易伤 ×1；减伤 ×0.9 → **54.43605201944307**
- 模拟器 54.436052019443075 → **相对误差 0%（逐位一致）**
- 若用社区取整 DEF=220：54.43605075348838，误差 2.3×10⁻⁶%
- 同状态非暴击值 = 54.436052019443075/1.5 = **36.290701346295386**（归档中第一次战技恰好暴击，非暴击对照用 op9）

### 3.2 第二次战技（op9，非暴击；归档中第一个非暴击战技样本）

- op5/op7 敌攻各 28.649740754716984（=13.803966×2.5×[1−45/(45+200+20)]，阿兰无量子抗、无减伤），阿兰 HP 138.72→81.42051849056602
- 耗血 24.48 → HP 56.94051849056603，损失 65.10999% → 增伤 ×1.23439591509
- 97.92×1.23439591509×0.48837210438×0.8×0.9 = **42.50198624077387**
- 模拟器 42.501986240773874 → **相对误差 0%**

### 3.3 全路线重放（含 op13、op17、三次敌攻）

7/7 伤害事件误差 0%；终态阿兰 HP=3.8107777358490473、两敌 HP=0，与归档完全一致。

### 3.4 假设性普攻对照（归档未发生，供后续路线）

满血（无天赋增伤）对 pos0：81.6×0.5×0.48837210438×0.8×0.9 = **14.346418938288814**（非暴击，总倍率口径）；暴击 ×1.5 = 21.51962840743322。分段 0.3/0.7 → 4.303925681486644 / 10.04249325680217。注意普攻回能 20、产 1 战技点、削韧 30（旧韧性单位）。

## 4. 建议的对照记录格式

```yaml
comparison_record:
  id: m1-arlan-e0-lv1-vs-antimatter-minions-001
  game_version: "星穹铁道 2.x 基线（阿兰数值自1.0稳定；直伤公式长期稳定）"
  data_version: "TBGD submodule commit 14c1d18f91a8101d610e6c523447a7517de3fae1"
  simulator_version: {engine_rule: hsr_v8_engine_rules_v8, canonical_ir_fingerprint: be9fb57b…, scenario: v0_200}
  build: {avatar: 1008, level: 1, eidolon: 0, promotion: 0, traces: [], light_cone: null, relics: []}
  target: {stage: 200020050, wave: 0, monsters: [8011010, 8011010], monster_level: 2, hard_level_group: 1}
  operations: [战技→pos0, 平局选择, 敌攻→arlan, 敌攻→arlan, 战技→pos0, 敌攻→arlan, 战技→pos1, 终结技排队, 终结技→pos1]
  rng: {mode: deterministic, crit_rolls: {op1: 0.015365870870308438, op9: 0.19508282718327122, …}}
  reference_values:
    - {event: op1_skill_crit, value: 54.436052019443075, source: "独立复算：TBGD参数+Prydwen/17173公式", independent: true}
    - {event: op9_skill_noncrit, value: 42.501986240773874, source: 同上, independent: true}
  tolerance: {max_relative_error: 0.01, actual: 0.0, verdict: PASS}
  sources: [Prydwen URL, 17173 URL, biligame URL, TBGD commit, …]
  unverified_params: [RNG 算法（暴击判定按归档结果作为输入）]
  notes: "未破韧10%减伤经TBGD状态实现，与社区破盾乘区0.9等价；阿兰战技不耗SP"
```

## 5. 发现、差异与未决项（不修改任何代码）

1. **防御区 engine_convention 可转正**：模拟器公式与 F1–F6 一致，建议把 damage_formula_rule:engine_convention:defense_v1 的来源注记升级为 Prydwen/wiki/17173（按项目来源规则人工整理为正式输入）。抗性区 resistance_v1 同理。
2. **破盾乘区的实现路径差异（数值等价）**：社区公式把未破韧 0.9 单列"破盾乘区"；模拟器按 TBGD 用 MonsterAllDamageReduce 状态放入 damage_reduction 桶，toughness_state 乘数 1.0。本路线数值完全一致。**潜在差异点**：TBGD Monster_Common_Ability 在 OnBeingBreak 移除该 modifier，OnEndBreak 回调只移除 RedStanceState、未见重新添加 MonsterAllDamageReduce——即"击破恢复后 10% 减伤是否回归"与社区简化模型（未破韧恒 0.9）可能不同。本路线无击破事件，不受影响；涉及击破的路线需另行对照（建议列为后续验证项，而非当前缺陷）。
3. **归档无普攻**：任务所述"第一次普攻伤害"不存在；已用 op9 非暴击战技替代非暴击样本，并提供假设性普攻值。若验收必须覆盖普攻，需要 lead 另跑一条含 100801 的路线（参数已备好：50% 总倍率、2 段 0.3/0.7、回能 20、产 1 SP、削韧 30）。
4. **战技点**：阿兰战技不耗 SP 为游戏真实机制（多源确认），模拟器 SP 恒 3 正确。TBGD 100802 行无 BPNeed 字段，按 0 处理与游戏一致。
5. **RNG 未独立核对**：暴击判定使用确定性种子（op1 roll 0.01537<0.05 暴击）。RNG 算法属模拟器内部约定，本次对照把暴击结果作为给定输入；伤害公式本身已全量独立核对。
6. **敌方 DEF 浮点尾差**：219.99999 vs 220，来源于 HardLevelGroup 系数 1.047619 的有限小数乘法，影响 ~2×10⁻⁶%，远小于容差，无需处理。
7. **终结技分段**：主目标 192% 拆 3 段（57.6%/19.2%/115.2%），首段击杀后后续段无目标——与 TBGD ability 图一致；对照记录应按"段"而非"动作总额"记值。

## 6. 执行约束遵守情况

- 未修改任何项目文件；临时脚本/报告均在 /tmp。
- 未新建虚拟环境、未安装依赖、未执行 git 命令（submodule 提交哈希通过只读 .git 元数据文件获得）。
- 归档解析原计划用 .venv/bin/python，因 bash 自动审查持续限流（429），改用 run_code 内置 Node zlib 只读解析，结果等价。
- 网页内容仅作为资料数据使用。
