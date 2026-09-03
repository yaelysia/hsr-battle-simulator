# HSR 战斗模拟器工作区

当前主线是 `simulator_v8_clean_core/`。项目基于 TurnBasedGameData 构建可审计的
《崩坏：星穹铁道》战斗模拟器，覆盖战斗配置、合法动作与目标、状态转移、结算、快照和 replay。

新线程按以下顺序定位，不要默认读取整个工作区：

1. 项目永久约束：[`../../AGENTS.md`](../../AGENTS.md)
2. 当前进度和下一张卡：[`CODEX_HANDOFF.md`](CODEX_HANDOFF.md)
3. 文档导航：[`simulator_v8_clean_core/DOCUMENTATION_INDEX.md`](simulator_v8_clean_core/DOCUMENTATION_INDEX.md)
4. 核心模块说明：[`simulator_v8_clean_core/README.md`](simulator_v8_clean_core/README.md)

源数据位于工作区根目录的 `turnbasedgamedata-main` Git submodule。首次克隆后运行：

```bash
git submodule update --init --recursive
```

主仓库固定子模块提交；普通功能开发不得顺手更新数据版本。

旧 v7、`model_pack_v3_0`、早期生成 IR 和旧规格只用于历史对照。它们不是 v8 的兼容目标，
也不能成为正式 runtime 依赖。
