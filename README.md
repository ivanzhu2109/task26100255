# PixelCanvas 分类合并库

创意团队内容管理系统（CMS）使用的分类合并库。分类树与内容引用持久化到本地
SQLite 文件，支持分类合并、同名子分类折叠、历史 ID 永久解析。

## 能力

- **初始化**：`initialize(categories, content_refs)` 导入分类树与内容引用（初始数据需合法）。
- **合并分类**：`merge(source_id, target_id)` 把源分类并入目标分类。
- **查询分类**：`get_category(category_id)` 返回存续 ID、名称、父 ID、子 ID 列表；支持历史 ID。
- **查询内容分类**：`get_content_categories(content_id)` 返回当前存续分类的去重集合。

## 快速开始

```python
from pixelcanvas import CategoryStore, MergeRejected, CategoryNotFound

store = CategoryStore("pixelcanvas.db")          # 本地 SQLite 文件，":memory:" 亦可
store.initialize(
    categories=[(1, "root", None),               # (id, name, parent_id)
                (2, "news", 1),
                (3, "articles", 1)],
    content_refs=[(1001, 2), (1002, 3)],          # (content_id, category_id)
)

store.merge(2, 3)                                 # news 并入 articles，返回 True
store.get_category(2)                             # 历史 ID 仍有效 -> CategoryInfo(id=3, ...)
store.get_content_categories(1001)                # -> [3]
store.close()                                     # 重新打开后语义不变
```

### 合并语义

- 目标保留自己的 ID、名称和位置；源分类退出当前树。
- 源的子分类在目标下无同名节点时，整条分支移入目标并保留 ID；有同名节点时，
  以源侧/目标侧节点为新的一对递归执行同一规则，直至所有层级处理完毕（迭代实现，
  支持 5000 层深度）。
- 退出树的每个 ID 永久有效，解析到实际并入的存续分类；存续分类再次被合并后，
  历代 ID 继续跟随。旧 ID 可用于查询和再次发起合并。
- 内容引用不随合并改写：引用表保留原 ID，查询时经历史 ID 映射解析到存续分类并去重，
  因此引用永不丢失、独有分支上的引用不会错误转移。
- 合并前按存续 ID 判断关系：两者相同则为无操作（返回 `False`，数据不变）；
  任一方是另一方祖先则抛出 `MergeRejected`，数据保持原样。

## 存储设计

| 表 | 说明 |
| --- | --- |
| `categories(id, name, parent_id)` | 当前存续分类森林 |
| `aliases(old_id, live_id)` | 历史 ID -> 当前存续 ID；合并时整体跟随 |
| `content_refs(content_id, category_id)` | 内容直接引用，`category_id` 保留写入时的 ID |

合并只改写 `categories` 与 `aliases`，不触碰 `content_refs`，因此“10 万条引用的
分类连续并入 5000 个兄弟”场景下引用零迁移；查询经 `LEFT JOIN aliases` 解析去重。

## 测试

```bash
python3 -m pytest tests/ -q
```

覆盖：多层同名分支与独有分支混合合并（目标 ID 保留、分支位置、引用不丢失且去重）、
连续合并后用最早 ID 再合并并重开数据库验证、祖先关系拒绝与两旧 ID 同指向的幂等、
5000 层深层同名分支完整合并，以及规模性能场景。

性能实测（Apple Silicon，10 万分类 / 50 万引用）：

```
5000 merges + 10000 queries: 8.40s (budget 30s)
```
