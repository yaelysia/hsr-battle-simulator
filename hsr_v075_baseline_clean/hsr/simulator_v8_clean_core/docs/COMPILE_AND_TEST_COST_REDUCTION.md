# 编译与测试耗时优化

执行：dsh / DeepSeek；约束与集中验收：Codex。基线 `35289a0`。
本批改善相同输入下的重复工作，不改变规则、来源范围、动作、审计或归档指纹。

## 第一轮验收（2026-10-21）

三项改动均已验收，来源枚举权限回归已修复：匹配名字先于目录分类，分类权限错误保留
同层匹配项，匹配 JSON 自身的 stat 错误继续透出。Codex 最终快测 30 项通过；原复现及
链接前后顺序、嵌套拒绝访问和匹配链接边界均与 pathlib 一致。

交付最终热加载 2.65–3.38 s、会话初始化 8.88 s；集成模块交付复验 122.54 s，Codex
调整分支顺序的独立运行 126.01 s（4 项通过），原参考为 272 s。规则指纹、pending、完整
归档和 final 快照摘要与基线一致。冷编译约 38–48 s、九步执行约 75 s 及内存尚未优化。
下文保留第一轮基线与实施约束；第二轮先做调用级剖析，再集中确定改动。

## 已测事实（2026-10-20）

使用已有 `.venv`，固定希儿自动插入行动场景及九步命令，串行加锁。
一次公开 `BattleSession.advance/submit` 路线分段计时，全部提交成功：

| 部分 | 耗时 |
| --- | ---: |
| 已命中缓存的 build_battle_rulebook | 6.37 s |
| 其中两次 _cache_key，合计 | 4.96 s |
| 其中 _read_cache | 1.17 s |
| RuleBook 建索引 | 0.05 s |
| BattleSession 初始化 | 14.95 s |
| 前八次公开 advance/submit | 60.40 s |
| 第九次 advance/submit（含自动插入排空） | 21.96 s |
| 以上九步路线合计（不含导出、replay） | 103.68 s |

该进程墙钟 106.50 s，峰值 RSS 948820 KiB。内部计时包含轻量包装器，属于分段基线，
不是 CLI 导出/回放的耗时。测试模块现有三项 integration 都独立执行相同八步前置；
首份初始化加八步为 75.34 s。去除两份重复，仅八步操作部分按本次计时估算约 121 s，
另省两次会话初始化；后续初始化已可命中规则身份缓存，收益以同机模块实测为准。

另一次只测初始化及目录枚举的窄检查确认：

- FormalBuildManifest 创建时，canonical_ir_fingerprint 花费 5.65 s；Session 随后又算同一
  IR 的指纹，花费 5.52 s。两处结果相同；已有正式构筑清单可复用，不需要新建指纹缓存。
- 对全部 123396 条 JSON 路径保留同样的大小、mtime_ns、ctime_ns 和 inode，Path.rglob + stat
  用时 1.74 s，os.scandir + DirEntry.stat 用时 0.32 s，排序后的元数据列表完全相同。
  这是目录枚举微测，不是编译提速的最终结果；缓存键还包含生产代码内容等输入。
- 当前源码已排除绝大多数 systems 文件与 core/executor.py 引起的 IR 缓存失效。
  本次没有测冷编译内部各阶段，不能把热加载成本归因于 lowering，也不以此宣称冷编译提速。

临时诊断记录：`/tmp/hsr_compile_test_cost_35289a0.{json,log}`、
`/tmp/hsr_startup_inventory_cost_35289a0.{json,log}`。永久事实以上表为准。

## 同批完成的三项改动

1. **共享真实测试前置**：修改 tests/test_automatic_insert_action_closure.py，模块内只构建一次
   规则库，只通过公开操作执行一次八步前置，取得正式 pending 状态。成功、取消、晚期失败
   都从该状态验证。成功路线保留其会话历史和第九次公开提交；其它用例只消费保存的只读
   pending 状态，不能读取已被成功用例推进的 session.state。每个分支的 scheduler、
   monkeypatch、候选状态和可变历史独立，不新增生产 clone/restore 接口来服务测试。
2. **复用已算出的正式指纹**：Session 初始化优先复用 ScenarioStateBuilder 返回的正式
   build_manifest.rule_identity.canonical_ir_fingerprint。无正式清单的合法组件场景仍走
   原指纹计算路径。先核对所有直接调用者，不重新实现 hash、不改摘要算法/字段/类型。
3. **加快完整来源枚举**：在 tbgd/compile_cache.py 用标准库高效枚举代替 Path 对象逐层遍历，
   利用 DirEntry 元数据；保留来源、代码、scope、limits、Python 版本的完整失效语义。
   调整缓存依赖时，只允许额外排除已证实没有 L0 调用者的 session.py；不顺手扩大排除名单。
   优化代码自身导致一次缓存重建是正常失效，交付将这次成本与后续命中分开记录。

## 必须保持的约束

- 前置来自正式构筑、波次与八次公开提交，不能手工注入 HP、状态、队列、时间线或回调。
  不共享会被多个测试修改的 Session/operations；改变测试顺序不得改变结果。
- 原成功、取消和晚期失败断言全部保留，包括审计、实际等级、窗口身份、资源、后续公开
  操作、失败零 mutation/RNG 与 pending 条目保留。保持 integration 标记，不用删测提速。
- 所有来源 JSON（含 TextMap）的修改、增删、重命名仍必须失效；mtime 恢复也不能掩盖修改。
  隐藏目录、符号链接的枚举及 stat 语义、排序和扫描异常处理与现实现一致。
- 保留读取缓存前后的来源/代码一致性检查，以及冷编译发布前检查；不得删掉第二次扫描，
  不以固定 submodule HEAD、TTL 或仅根目录 mtime 代替文件变化检查。
- 损坏回退、受限反序列化、原子写入、并发冷编译锁及不可变共享照旧；不保存假成功，
  不增加无限保留 IR/RuleBook 的全局强引用缓存。
- 规则指纹必须与原算法逐字节一致。不能拿归档提供的摘要代替当前实际规则身份；
  独立 replay 的规则核验保持。纯性能修改不更改公开接口和归档格式。
- 优先改上述测试、session.py、compile_cache.py 及相关已有小测试；不修改伤害、状态、
  调度规则，不拆编译器、不做分片增量编译、不引入并行重任务或新依赖，不动 submodule。

## 验证与交付

1. 定向快测：test_compile_cache.py、test_ir_import_identity.py、本模块非 integration 用例，
   加上实际修改触及的现有会话/归档小检查。复用已有失效、并发、损坏和跨包前缀检查；
   只补现有检查不能证明的准备次数、测试隔离和正式指纹复用检查。
2. 同一模块三项 integration 合并运行一次：

   ```bash
   flock /tmp/hsr-v8-validation.lock /usr/bin/time -f 'elapsed=%e max_rss_kib=%M' \
     .venv/bin/python -B -m pytest -o addopts='' -q -m integration --durations=5 \
     hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_automatic_insert_action_closure.py
   ```

   硬要求：一次规则准备、一次八步前置、三项原断言通过；记录同机总耗时与峰值。
   复用上批三项 4:32 的记录作为参考，注明冷/热状态；不为补基线再跑三次前置。
3. 来源枚举优化后，用同一场景测一次命中的规则加载并拆分 key/read/RuleBook；如该次
   实为缓存重建，注明 cold，后续命中另测，不能把 cold/hit 混在一起比较。
   比较元数据内容、规则指纹和原断言，不能只比扫描函数的微测数字。
4. 不默认跑全目录、全量回归或重新生成独立 replay。指纹一致且归档核验路径未改时，复用
   已有 19 步 replay；若实际修改触及序列化/恢复/规则核验，才补相应验证。

交付写清三项实测收益、准备次数、失效语义和仍未优化的阶段；整批交回验收，不自行提交。
