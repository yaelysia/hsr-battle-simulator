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
| [m1-arlan-e0-lv1-vs-antimatter-minions-001](records/m1-arlan-e0-lv1-vs-antimatter-minions-001.yaml) | 阿兰基线路线（M1 方法验证，非名单条目交付） | 公式一致性 PASS（7/7 误差 0%）；游戏对照待外部输出 |
| [m2-arlan-e0-lv80-p6-full-traces-102-302-23002-001](records/m2-arlan-e0-lv80-p6-full-traces-102-302-23002-001.yaml) | M2 阿兰条目（80 级满行迹构筑） | 公式一致性 PASS（8/8 误差 0%）；游戏对照待外部输出；击破分支未验证（需雷弱点关卡，现成路线被 XP_Minion 被动准入回归阻断，见交接） |
