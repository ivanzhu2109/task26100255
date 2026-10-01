# PixelCanvas 分类合并库

由上层内容管理系统直接调用的 Python 库：把重叠的分类分支并入目标分类，
折叠同名子分类，历史内容引用与旧书签通过历代 ID 永久解析到当前存续分类。
所有数据持久化到本地 SQLite 文件，无外部服务依赖。

## 环境要求

- Python 3.9+（仅标准库，无第三方依赖）
- 本机 SQLite 文件即可，不需要数据库服务

## 快速开始

```python
from pixelcanvas import CategoryStore, Category, ContentRef

with CategoryStore("pixelcanvas.db") as store:
    # 1. 初始化（仅允许在空库上调用一次；初始数据需保证合法）
    store.initialize(
        categories=[
            Category(id=1, name="组件", parent_id=None),
            Category(id=2, name="元件", parent_id=None),
            Category(id=3, name="按钮", parent_id=1),
            Category(id=4, name="按钮", parent_id=2),
        ],
        content_refs=[
            ContentRef(content_id="page-1", category_id=3),
            ContentRef(content_id="page-1", category_id=4),
        ],
    )

    # 2. 合并分类：源(1) 并入 目标(2)，同名子分类“按钮”折叠，保留目标侧 ID 4
    store.merge(source_id=1, target_id=2)

    # 3. 查询分类：任意历代 ID 均可，返回当前存续分类
    view = store.get_category(1)        # -> CategoryView(id=2, name='元件', ...)
    view = store.get_category(3)        # -> CategoryView(id=4, name='按钮', parent_id=2, ...)
    forest = store.list_categories()    # 全部存续分类的父子关系

    # 4. 查询内容分类：返回当前存续分类的去重集合
    cats = store.get_content_categories("page-1")   # -> {4}
```

## API 一览

| 方法 | 说明 |
| --- | --- |
| `CategoryStore(db_path)` | 打开（或创建）SQLite 数据库并加载分类树；支持 `with` 语法 |
| `initialize(categories, content_refs)` | 写入初始分类森林与内容引用，仅限空库一次 |
| `merge(source_id, target_id)` | 合并分类；源与目标无需同名，可用任意历代 ID |
| `get_category(category_id)` | 返回该 ID 当前存续分类的 `CategoryView` |
| `list_categories()` | 返回全部存续分类的 `CategoryView` 列表 |
| `get_content_categories(content_id)` | 返回内容指向的存续分类 ID 去重集合 |
| `close()` | 提交并关闭数据库 |

## 合并语义

- 目标保留自己的 ID、名称和位置；源分类退出当前树。
- 源的子分类在目标下无同名节点时，整条分支移入目标并保留 ID；
  有同名节点时按相同规则逐层向下合并（迭代实现，支持 5000 层深度）。
- 退出当前树的每个 ID 永久有效，解析到实际并入的存续分类；
  存续分类再次被合并后，所有历代 ID 继续跟随。
- 内容引用随各自节点的去向转归；同一内容指向同一存续分类时只算一次；
  独有分支上的引用不会丢失或转移到分支根部。
- 源与目标已指向同一存续分类时不做任何修改（`MergeResult.changed=False`）；
  任一方是另一方的祖先时抛出 `AncestorMergeError`，所有数据保持原样。

## 异常

- `UnknownCategoryError`：分类 ID 从未存在过
- `AncestorMergeError`：源与目标存在祖先/后代关系，合并被拒绝
- `AlreadyInitializedError`：对已初始化的数据库重复调用 `initialize`

## 运行测试与基准

```bash
python3 -m unittest discover -s tests -v   # 自动化测试
python3 bench/benchmark.py                 # 规模场景基准
```

基准场景：10 万分类（含 5000 层深链）、50 万条内容引用；
关联 10 万条引用的叶分类连续并入 5000 个兄弟分类，再做 1 万次查询。
本机实测总耗时约 0.11 秒（要求 30 秒以内，初始化不计时）。

## 实现要点

- `categories` 表只保存存续分类；`alias` 表保存全部历代 ID 的指向；
  `content_ref` 表保存原始内容引用，合并时无需改写，查询时经 alias 解析去重。
- 打开数据库时将分类树与 ID 映射加载为内存索引，合并与查询均为内存操作
  加单次事务落盘；正常关闭并重开后语义不变。
