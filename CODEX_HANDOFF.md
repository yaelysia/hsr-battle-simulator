# HSR 战斗模拟器：当前项目入口

更新于 2026-10-10。本文件供从仓库根目录进入的协作 AI 快速定位；当前进度的唯一权威是
[当前交接](hsr_v075_baseline_clean/hsr/CODEX_HANDOFF.md)。旧 v7 / model_pack 资料只供对照，
不再是 v8 的运行入口或兼容目标。先读 [项目约束](AGENTS.md)，再按具体任务读取必要文件。

## 当前可运行成果

- 正式内核在 hsr_v075_baseline_clean/hsr/simulator_v8_clean_core，保持 L0 来源编译、
  L1 通用机制执行、L2 内容装配、L3 外部操作，以及横切的来源审计、结算和 replay。
- 已交付一个限定场景的命令行 MVP：阿兰 E0、1 级对两只 2 级重子，双方手动选择，
  单波九次提交获胜；独立 replay 的 19 步校验成功。命令和示例见
  [CLI_MVP.md](hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/CLI_MVP.md)。
  这条路线不发生击破，不能证明任意战斗、任意角色或完整击破链可运行。
- 新增希露瓦+娜塔莎 E0/1级对两只8级重子的21次提交胜利路线，覆盖希露瓦普攻、战技、
  感电、天赋与终结技。新归档采用共享证据引用表，压缩约364KB；生成2分28秒、独立文件回放
  43项操作一致，耗时2分36秒、峰值约0.85GiB。旧归档不兼容；构筑、命令、证据和丹恒
  剩余缺口见当前交接及 `CLI_MVP.md`。
- PR #8 中用户已确认的规则可直接落到正式规则输入，不以在 TBGD 找到同值为前提，
  但必须标注实际研究来源；未确认的语义仍只阻断相关分支。近期已接多请求受击回能、
  普通多盾并行吸收、加权选择与 RNG 调用、部分普通击破数值及恢复、冻结行动跳过、
  行动前 DOT 致死调度等。准确边界与证据见当前交接和
  [已知缺口](hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/MVP_KNOWN_GAPS_2026-09-28.md)。

## 后续方向与协作边界

- 2026-10-08 用户明确采用逆向研究驱动，目标为尽量还原实际战斗，不完整复刻原生引擎。
  已修阿兰低 HP 战技下限，并贯通阿兰+娜塔莎的静态构筑治疗胜利路线。
  当时的方向与来源使用边界见[历史交接快照](hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/archive/CODEX_HANDOFF_PRE_SLIM_2026-10-19.md#reverse-driven-20261008)。
- [当前路线](hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md)
  按实际内容追踪行为依赖，修准入误判和真正机制缺口；特殊机制由具体内容需求推动。
  不把所有旧 P9 未勾选项、特殊韧性、多波或 UI 变成现有 MVP 的前置。
- 致死受击回能待游戏实测；公共击破状态 TriggerBreak(Caster) 与现有回调的原生映射、
  归属和顺序未确认；首次状态计时仍有争议。其他条件性缺口以当前清单为准，
  不能把局部规则实现写成整条技能或整个角色已贯通。
- 实战对比的“逐项记录器”目前只是讨论，**没有实现**。先前擅自新增的独立页面已撤回。
  若今后决定做，应优先复用现有模拟器的配置、动作、快照与 replay；
  游戏观测只作并列记录，不作为内核运行规则。
- 2026-09-30 已核对用户的新提交：`master@6733fd350ddbbf72b30d808153e8abc2a538c48c`，
  父提交为 `2d60a4305206bc11b67edf445a55478d90c96257`。近期 CLI 与内核成果已进入该提交，
  TBGD submodule 指针未变；2026-09-30 校准时未核实远端推送、未重跑测试，本次新验证见上文。
- 2026-09-30 用户曾要求同步 MCP 看板的信息层。该次账本为 4 条 completed、
  3 条 cancelled；只更新说明的两次请求也被终态转换校验拒绝，故看板尚未写入成功。
  当前接口没有工作流外成果补录入口；不直接改账本，不伪造批准、审核或新任务完成记录。
  该次 MCP 同步记录见[历史交接快照](hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/archive/CODEX_HANDOFF_PRE_SLIM_2026-10-19.md#mcp-status-20260930)。

验证以能说明实际行为的最小正例、真实 CLI 战斗和独立 replay 为主，不追覆盖率或形式性
非法输入矩阵。
