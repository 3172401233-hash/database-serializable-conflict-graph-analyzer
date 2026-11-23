# database-serializable-conflict-graph-analyzer

分析可串行化冲突图、危险结构和中止选择。

**重要：本项目只做静态分析，不执行任何数据库事务。** 输入是事务的
元数据（读集、写集、版本、提交顺序、谓词读、已中止标记），输出是依赖
图、违例环与中止方案；不会连接或操作任何数据库。

## 功能

- 构建 `rw`（读-写反依赖）、`wr`（写-读）、`ww`（写-写）三类依赖边。
- 谓词幻读：谓词读（显式键集合或闭区间 `key_range`）匹配到提交顺序
  更晚的写入时产生 `rw` 幻读边。
- 版本化读：读旧版本时，`wr` 指向该版本的写入者，对其后的覆写者产生
  `rw` 反依赖。
- 长事务：以 `commit_ts - start_ts` 作为时长，计入中止代价并被标记为
  长事务，方案排序时优先牺牲短事务。
- 多个可串行化异常可同时存在：枚举所有基本环（危险结构），用最小
  命中集（feedback vertex set）给出能打破全部环的中止集合。
- 每个中止方案都会重算剩余图，输出 `remaining_cycles` 验证残余图无环。
- 多方案 tie break：按（中止数、总代价、事务 id 字典序）确定性排序，
  并给出每个方案的风险等级（none/low/medium/high）。
- 已中止事务不参与构图（它们没有已提交的写入）。

## 用法

```python
from analyzer import Transaction, Predicate, analyze

txns = [
    Transaction("T0", writes={"A": 0, "B": 0}, commit_order=0),
    Transaction("T1", reads={"A": 0, "B": 0}, writes={"A": 1},
                commit_order=1, start_ts=0, commit_ts=3),
    Transaction("T2", reads={"A": 0, "B": 0}, writes={"B": 1},
                commit_order=2, start_ts=0, commit_ts=500),
    # 谓词读示例：
    # Transaction("T3", predicate_reads=[Predicate("r", key_range=(1, 10))],
    #             commit_order=3),
]

report = analyze(txns)
print(report.cycles)            # 违例环，如 [('T1', 'T2')]
print(report.best_plan())       # 最优中止方案（含代价与风险）
residual = report.recompute(report.best_plan().abort_set)
assert residual.is_serializable
print(report.format())          # 人类可读的完整报告
```

## 运行测试

```sh
python -m unittest
```

兼容 Python 3.8.2+。测试覆盖写偏斜、谓词幻读、交叉依赖（wr/rw/ww
混合环）、版本化读、已中止事务排除、多异常并存与多方案 tie break。

## 结构

- `analyzer/model.py` — `Transaction` / `Predicate` / `DependencyEdge`
- `analyzer/graph.py` — 依赖图构建（rw / wr / ww，含幻读）
- `analyzer/cycles.py` — 基本环枚举
- `analyzer/abort.py` — 最小命中集中止方案与风险评估
- `analyzer/analyzer.py` — `analyze()` 入口与 `AnalysisReport`
