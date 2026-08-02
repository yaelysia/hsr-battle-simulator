# P9-S1 Ability Source Graph - accepted

## 状态与范围

- 状态：`accepted`。
- 硬基线：`59a882b22a18183bc1bbccf630a2499302844883`。
- P9-S1 已通过独立代码、来源、负例和 evidence 验收；本报告、Checklist 与交接状态随同一检查点提交。
- 报告位于仓库级 `live_validation_reports/`；旧的 `simulator_v8_clean_core/docs/` 草稿已移除。

验收结论：S1 的 `lowering_gap` 为零；剩余 41 条均有真实关系来源和结构化阻断，不是本阶段
遗漏。验收未把 source gap 伪装成可执行，也未提前进入 S2。

## 最新独立验收差量

- `TBGDLowering._avatar_action_binding()` 的 TriggerAbility child 现在将零候选和同类多候选统一记入 unresolved；唯一 gameplay 仍优先于 presentation，presentation-only 仍为 client-only audit。
- unresolved 在任何 phase/task lowering 之前立即返回 `_blocked_action_binding()`；返回的 phase 及 `_LoweredAbility` 的 task/effect/condition/formula/target 等全部正式通道为空。
- source graph builder、Catalog 构造边界与 RuleBook `query_action()` 统一先按 owner 收窄：own=1 可解析，own>1 才按 kind/duplicate 阻断，无 own 且仅 foreign 才是 `cross_character_blocked`。
- validator 增加缺失 child、多义 child 的空通道负例、gameplay/presentation 优先级探针、owner-first 正例与 foreign-only 负例，并从同一 catalog 输出 cross-character gap 的 typed source path、json path、own/foreign candidate IDs 和形态。
- 前次唯一主运行在 owner-first synthetic 正例构造阶段失败：fixture 只改 owner、未同步 config/skill source evidence，生产构造器按预期拒绝。fixture 协调后，独立审查又发现 Catalog 仍按全局 action ID 判歧义；本轮同步修正为 `(action_id, owner_avatar_id)` 并加入同源契约探针。
- 经明确额外授权后，相同主入口一次通过；TriggerAbility 空通道 direct、owner-first query/Catalog 正反例及 cross-character typed source 摘要均已落盘。

## 前一轮验收差量

- 新增精确 `CharacterNonGameplaySkillSourceIR`。每条记录持有 owned graph、owner、selected skill、raw AttackType、raw SkillEffect、action-table row index、文件 digest、稳定身份和 `maze_normal_without_skill_trigger` retired reason。
- 退役判定只接受结构条件：raw `SkillTriggerKey` 为缺失/空字符串且 `AttackType=MazeNormal`。SkillEffect 只保留为 evidence，不参与判定。无 trigger 的 BPSkill、Ultra 或未知类型不会退役，继续 fail-closed。
- owned graph/catalog 显式持有 non-gameplay source IDs。每个 selected skill 必须恰好属于 gameplay action source、non-gameplay retired source、`missing_action_source_blocked` gap 三类之一；重叠、遗漏、跨 owner/graph 和重复 retired source 均在构造边界拒绝。
- 角色卡继续保留 S0 所选 inventory 行的完整 raw SkillList；没有从 `selected_skill_ids` 删除探索技能。
- RuleBook 查询 `avatar_skill:<retired skill>` 返回 blocked、专用 source ID 和 `non_gameplay_skill_retired`。focused `_avatar_action_binding()` 透传同一 reason，不生成 phase/task。
- retired source 不进入 definition/binding/gap relation ledger，不产生 task、condition、target、event、effect、mutation 或 RNG。

## 当前生产观测

- S0 来源 80：角色主来源 79、共享来源 1；selected version 为 base 69、enhanced 10。
- definitions 1,440；gameplay action sources 440；typed retired sources 79。
- 79 仅为当前 raw observation，不是固定 gate。独立 oracle 对账缺失 0、额外 0。
- retired AttackType：MazeNormal 79。SkillEffect：MazeAttack 77、SingleAttack 2。
- relation outcomes 1,563：resolved bindings 1,522、blocked gaps 41。
- gap kinds：`source_gap_blocked` 35、`cross_character_blocked` 3、`missing_entry_blocked` 3；`missing_action_source_blocked` 当前为 0。
- 当前公共 action ID 的跨 owner 碰撞组为 0；因此 `_avatar_action_binding()` 未获得 owner 上下文的既有限制没有当前 raw 执行依赖，本阶段不宣称 runtime materialization 支持未来跨 owner 公共 action。
- 3 条 `cross_character_blocked` 均为 relation-level phase 请求，类型化核对均为 own candidates=0、foreign candidates=1：owner 1112 的 `Avatar_Topaz_00_Config.json` 在 `$.SkillAbilityList[2]` 请求 `Avatar_Klara_00_Skill03_EnterReady`，同一 source/path 还请求 `Avatar_Klara_00_Skill03_Phase01`；owner 1201 的 `Avatar_Qingque_00_Config.json` 在 `$.SkillAbilityList[3]` 请求 `Avatar_Pela_00_Skill03_Cutin`。它们不是可由 owner 唯一消歧的公共 action。
- 上一轮的 1,642 条关系/120 gaps 中有 79 条探索技能伪 gap；本轮将其移入独立 retired catalog 后，关系和 gap 各减少 79。
- binding kinds：entry 356、phase 411、passive 233、presentation 356、standalone 166。
- raw relation oracle 对账 1,563 条，缺失、额外、结果不一致均为 0；`lowering_gap=0`。
- 当前 raw entry-only 动作 4；重复 phase action/name 组和重复 phase relation 均为 0。数量均由 raw 派生，不作为非零 gate。

规划期 M01 的“17 条记录、19 个缺口”和开工窄复核的“9 条记录、13 个缺口”是机制规划观察，不是生产 relation ledger gate。最终数量来自 S0 selected-version 闭包、逐 raw relation 分类及独立 non-gameplay admission，不硬编码数量或 hash。

## 验证记录

- 较早诊断主验证：失败，6.34 秒，峰值 452,624 KiB；修复 Canonical card skill ID 的 raw int/规范字符串比较。
- 较早最终主验证：失败，7.19 秒，峰值 452,496 KiB；移除验证器对真实 ambiguous/missing-phase gap 必须非零的过时前提。
- 上一轮额外最终主验证：通过，7.83 秒，峰值 457,392 KiB；随后独立验收发现 79 个 MazeNormal 探索技能被错误报告为 source gap，因此该结果未被视为验收通过。
- 本轮按新增差量授权最多一次主验证，未先跑诊断：一次通过。内部墙钟 7.621 秒，`/usr/bin/time` 墙钟 7.80 秒，峰值 457,480 KiB（468,459,520 bytes），evidence 11,021 bytes，validator 867 个非空行。
- 最新授权的唯一一次主验证：失败，退出码 1，墙钟 7.17 秒，峰值 457,412 KiB。catalog 与独立关系 oracle 已构建，随后在 `_negative_matrix` 的不协调 synthetic owner fixture 构造处失败；focused TriggerAbility direct 尚未运行，summary 未落盘，未追加重跑。
- 失败后静态门禁通过：compileall 0.03 秒 / 15,456 KiB，静态 import 0.15 秒 / 22,456 KiB，`git diff --check` 0.01 秒 / 9,972 KiB；validator 900 个非空行。
- 本轮额外授权的相同主入口一次通过：内部墙钟 7.835 秒，`/usr/bin/time` 墙钟 8.43 秒，峰值 457,300 KiB（内部 468,275,200 bytes），evidence 13,516 bytes，validator 900 个非空行。
- 本轮静态前置通过：compileall 0.04 秒 / 21,656 KiB，静态 import 0.12 秒 / 22,744 KiB，`git diff --check` 0.01 秒 / 10,052 KiB。
- 本轮构建：S0 snapshot 1、scope projection 1、source graph 1、窄 Canonical 闭包探针 1；完整 lowering 0、完整 Canonical IR 0、完整 RuleBook 0。
- 静态前置一次通过：compileall 0.16 秒 / 57,092 KiB，静态 import 0.26 秒 / 29,844 KiB，`git diff --check` 0.01 秒 / 9,976 KiB。
- retired 变形负例通过：MazeNormal 无 trigger 可退役；BPSkill、Ultra、未知类型不可退役；伪 row/digest/attack/owner、跨 graph membership、gameplay/gap 重叠和 selected skill 遗漏均被拒绝。
- 既有同类多 definition、缺 ability、presentation audit、跨 owner/kind、伪 relation/card ref、输入重排、可变容器和内部模型子类负例继续通过；新增 Catalog owner-scoped ambiguity 正反例通过。
- direct 通过：camera + gameplay、enhanced selected-version、retired focused lowering 和 TriggerAbility 缺失/多义 child fail-closed 共用现有 snapshot/catalog；两个 child 负例 phase lowering 调用均为 0，全部正式通道为空。

证据：

- `/tmp/p9_s1_non_gameplay_final_20260803_once/p9_s1_ability_source_graph_summary.json`
- `/tmp/p9_s1_non_gameplay_final_20260803_once.resource.txt`
- `/tmp/p9_s1_non_gameplay_final_20260803_once.stdout.json`
- `/tmp/p9_s1_non_gameplay_final_20260803_once.stderr.txt`（0 bytes）
- `/tmp/p9_s1_trigger_failclosed_final_20260803_once.resource.txt`
- `/tmp/p9_s1_trigger_failclosed_final_20260803_once.failure.txt`
- `/tmp/p9_s1_catalog_owner_final_20260803_once/p9_s1_ability_source_graph_summary.json`
- `/tmp/p9_s1_catalog_owner_final_20260803_once.resource.txt`

## 未覆盖范围

- S0 的 213 个 decode-required 记录和 unit-topology 外部依赖保持原名与未闭合状态。
- 41 个真实 relation gap 保持 blocked；本阶段不执行其 task/effect。
- source graph query/Catalog 已支持 owner 消歧；`_avatar_action_binding()` 对未来真实跨 owner 公共 action 的 runtime materialization 未覆盖。当前 raw 碰撞为 0，不构成现行执行依赖。
- 未构建完整 Canonical IR/RuleBook，未运行 P1-P8 聚合、完整 lowering、旧大验证或 `validate_v0_209`。
- runtime、servant/monster 语义、行迹、星魂及 S2 均未覆盖。

## 修改路径

- `simulator_v8_clean_core/rules/__init__.py`
- `simulator_v8_clean_core/rules/ir.py`
- `simulator_v8_clean_core/rules/rulebook.py`
- `simulator_v8_clean_core/tbgd/__init__.py`
- `simulator_v8_clean_core/tbgd/character_ability_source_graph.py`
- `simulator_v8_clean_core/tbgd/character_cards.py`
- `simulator_v8_clean_core/tbgd/lowering.py`
- `simulator_v8_clean_core/tools/validate_p9_s1_ability_source_graph.py`
- `live_validation_reports/P9-S1_ABILITY_SOURCE_GRAPH_ready_for_review.md`

开工前已有的 `simulator_v8_clean_core/ARCHITECTURE_BOUNDARY_CONTRACT.md` 修改及两个未跟踪 UI 文件均未触碰、暂存或清理。
