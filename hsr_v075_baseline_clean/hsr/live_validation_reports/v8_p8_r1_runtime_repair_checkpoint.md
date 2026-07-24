# P8-R1 Runtime Repair Checkpoint

日期：2026-07-24

代码检查点：

```text
2d1a3f9
```

## 验收结论

P8-R1 的生产运行时修复通过聚焦验收：

- 合法空召唤 runtime 在正式启动边界建立。
- 召唤目标查询区分合法空集合和关系损坏。
- runtime 与 UnitState 双向核对 owner、summoner、kind、team 和生命周期。
- 联合伪造 owner、缺失 summoner 和阵营伪造均 fail-closed。
- halo relation 覆盖成员加入、离开、来源退场和波次切换。
- 生命周期事件进入 dispatcher、settlement、RNG 和 replay。
- 波次聚焦正例中 8 条生命周期事件对应 8 条派发记录，事件身份唯一。

独立复核：

```text
P8-R1 runtime-only: ok=true
P7-S3 selected graph atomic commit: 9/9
P7-S15 RNG identity/replay: 14/14
git diff --check: pass
```

## 延期证据

旧 P3/P7/P8 目录启动路径在 1.5 GiB 限制下触发 `MemoryError`。用户决定本轮不继续运行该重验证，等待验证体系治理后以低内存、分批目录入口补证。

当前口径：

```text
R1-RUNTIME = accepted
R1-CATALOG = deferred / not_proven
formal_catalog_startup_complete != proven
```

`not_proven` 不是已确认的生产失败，也不能解释为完整目录通过。P8 最终聚合前仍需补齐该证据。
