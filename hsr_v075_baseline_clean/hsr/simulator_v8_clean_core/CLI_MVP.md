# 本地战斗操作

在仓库根目录使用已有 `.venv`。当前支持范围、待修问题与数值对照状态只看
[交接](../CODEX_HANDOFF.md)；本文说明命令，不把历史示例等同于当前完整支持。

## 准备

下文命令在同一个 shell 中执行。每次新建输出目录，避免覆盖已有归档：

```bash
export PYTHONPATH=hsr_v075_baseline_clean
hsr_example_dir=hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli
hsr_run_dir=$(mktemp -d /tmp/hsr-cli-XXXXXX)
.venv/bin/python -B -m hsr.simulator_v8_clean_core.cli --help
```

首次选择新内容范围会编译并缓存规则；重复启动复用缓存。默认目录为
`/tmp/hsr-v8-ir-cache-<uid>`，可用 `HSR_IR_CACHE_DIR` 指定。修改规则来源或编译代码会失效，
修改操作脚本不要求重编译。运行不读取旧 v7/model-pack 的规则。
多支队伍需共用规则缓存时，可配置固定的 `compile_scope` 内容池，见
[场景说明](scenarios/README.md#共享编译范围)；不用把全部来源目录编进一次战斗。

会话默认输出精简诊断：保留数值、生产者身份和 RNG，裁掉重复 packet 与展开的来源解释树。
排查具体来源或运行来源审计时，在启动命令前设置 `HSR_DETAILED_DIAGNOSTICS=1`。
新归档为 `hsr_battle_session_v3`，记录自己的诊断模式，回放不依赖当前环境开关；旧归档文件保留，
不保证跨格式回放。

## 查询与交互操作

```bash
.venv/bin/python -B -m hsr.simulator_v8_clean_core.cli query \
  "$hsr_example_dir/arlan_vs_antimatter.json" > "$hsr_run_dir/query.json"
.venv/bin/python -B -m hsr.simulator_v8_clean_core.cli play \
  "$hsr_example_dir/arlan_vs_antimatter.json" --output "$hsr_run_dir/entry.json.gz"
```

双方都由操作者选择动作和目标，程序不代选敌方 AI。输入动作编号，再按提示输入目标编号或 ID；
`j` 查看当前合法动作，`q` 保存退出。请求终结技与执行排队终结技是不同操作。
状态、资源、目标和时机以公开决策返回为准，不从技能名称推断可用性。

## 固定操作与回放

阿兰 1 级、空装备对两只反重子的九步示例用于基本执行回归：

```bash
.venv/bin/python -B -m hsr.simulator_v8_clean_core.cli run \
  "$hsr_example_dir/arlan_vs_antimatter.json" \
  --commands "$hsr_example_dir/arlan_vs_antimatter.commands.json" \
  --output "$hsr_run_dir/battle.json.gz"
.venv/bin/python -B -m hsr.simulator_v8_clean_core.cli replay "$hsr_run_dir/battle.json.gz"
```

操作文件是 `{"commands": [...]}`，包含敌我双方选择。`run` 返回 0 表示正常结束战斗，
3 表示操作已执行完、战斗未结束并保存，2 表示输入或执行阻断；不能把退出码 3 当胜利。
`replay` 返回 `ok/step_count/errors`，从入场重新执行并核对记录，不是直接加载终态。
工程回归通过不等于完成游戏数值对照。

## 保存后继续

在 `play` 第一次决策输入 `q` 保存后，可用固定命令继续：

```bash
.venv/bin/python -B -m hsr.simulator_v8_clean_core.cli resume "$hsr_run_dir/entry.json.gz" \
  --commands "$hsr_example_dir/arlan_vs_antimatter.commands.json" \
  --output "$hsr_run_dir/resumed.json.gz"
```

省略 `--commands` 则进入交互操作。磁盘恢复会先重放验证；活会话的当前分支
`BattleSession.fork()` 与历史分支 `BattleSession.fork(operation_count)` 均直接共享对应边界的
不可变状态，不重放。恢复后的会话也保留这些已验证边界。接口见[会话模块](session.py)。

## 浏览器工作台与内容查询

```bash
PYTHONPATH=hsr_v075_baseline_clean/hsr .venv/bin/python -B -m simulator_v8_ui.server --help
PYTHONPATH=hsr_v075_baseline_clean/hsr .venv/bin/python -B -m simulator_v8_ui.server \
  --host 127.0.0.1 --port 8765
```

在允许监听本地端口的环境中打开 `http://127.0.0.1:8765`。工作台同样调用公开决策与提交接口；
不在前端另算伤害、资源或合法目标。本地端口是否可用由运行环境决定。

CLI 还可查询来源/准入目录，目录出现一项不代表它已通过实战或数值对照：

```bash
.venv/bin/python -B -m hsr.simulator_v8_clean_core.cli support --help
.venv/bin/python -B -m hsr.simulator_v8_clean_core.cli support > "$hsr_run_dir/support.json"
```

`support` 汇总完整来源目录，耗时和输出量明显高于单场景 `query`，不放入日常快测。

## 配置与示例

输入字段见[场景说明](scenarios/README.md)。正式角色以构筑装配面板，敌人以来源关卡波次入场；
场景只配置内容、成品构筑和初始条件，不填固定伤害或自造规则。`kernel_fixture` 仅用于组件检查。

`examples/cli/` 中同名 `.json` / `.commands.json` 是场景与操作对；其它路线的当前状态见交接。
XP_Minion 被动回归影响雷击破示例，不能凭旧报告把该路线标为当前可运行。
2026-11-12 整理前的逐路线操作记录已移至
[历史命令](docs/archive/usage/CLI_MVP_PRE_REFRESH_2026-11-12.md)，不再作为现行验收要求。
