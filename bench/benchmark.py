"""PixelCanvas 规模场景基准：

- 10 万个分类（含 5000 层深链）、50 万条直接内容引用；
- 一个初始叶分类关联 10 万条内容引用，其存续分类连续并入 5000 个不同兄弟分类；
- 随后 1 万次旧 ID / 内容分类查询；
- 计时不含初始化，要求总耗时 <= 30 秒。
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pixelcanvas import Category, CategoryStore, ContentRef

N_CATEGORIES = 100_000
N_REFS = 500_000
DEPTH = 5_000
N_MERGES = 5_000
LEAF_REFS = 100_000
N_QUERIES = 10_000


def build_initial_data():
    cats = []
    refs = []
    # 1) 5000 层深链：id 1..5000
    for i in range(1, DEPTH + 1):
        cats.append(Category(i, "chain", i - 1 if i > 1 else None))
    # 2) 兄弟合并场景：父 P=5001，叶 c0..c5000 为 id 5002..10002
    parent = DEPTH + 1
    cats.append(Category(parent, "P", None))
    leaf0 = parent + 1
    for i in range(N_MERGES + 1):
        cats.append(Category(leaf0 + i, "leaf%d" % i, parent))
    # 3) 其余分类填充到 10 万：宽树 300 x ~296
    next_id = leaf0 + N_MERGES + 1
    remaining = N_CATEGORIES - next_id + 1
    width = 300
    parents = []
    for i in range(remaining):
        if i % (width + 1) == 0:
            cats.append(Category(next_id, "grp%d" % next_id, None))
            parents.append(next_id)
        else:
            cats.append(Category(next_id, "node%d" % next_id, parents[-1]))
        next_id += 1
    # 4) 内容引用：叶 c0 独占 10 万条，其余 40 万条散布到其他分类
    for i in range(LEAF_REFS):
        refs.append(ContentRef("leaf-doc-%d" % i, leaf0))
    spread_ids = [c.id for c in cats if c.id != leaf0]
    for i in range(N_REFS - LEAF_REFS):
        refs.append(
            ContentRef("spread-doc-%d" % i, spread_ids[i % len(spread_ids)])
        )
    return cats, refs, leaf0, parent


def main():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    try:
        cats, refs, leaf0, parent = build_initial_data()
        store = CategoryStore(path)
        t0 = time.perf_counter()
        store.initialize(cats, refs)
        t1 = time.perf_counter()
        print("初始化（不计时）: %.2fs, 分类 %d, 引用 %d"
              % (t1 - t0, len(cats), len(refs)))

        start = time.perf_counter()
        # 连续并入 5000 个不同兄弟，每次都用最早 ID 发起
        for i in range(1, N_MERGES + 1):
            store.merge(leaf0, leaf0 + i)
        t_merge = time.perf_counter()
        # 1 万次查询：旧 ID 分类查询与内容分类查询交替
        for i in range(N_QUERIES):
            if i % 2 == 0:
                store.get_category(leaf0)
            else:
                store.get_content_categories("leaf-doc-%d" % (i % LEAF_REFS))
        t_query = time.perf_counter()
        total = t_query - start
        print("合并 5000 次: %.2fs" % (t_merge - start))
        print("查询 10000 次: %.2fs" % (t_query - t_merge))
        print("总耗时: %.2fs (要求 <= 30s) -> %s"
              % (total, "通过" if total <= 30 else "超时"))

        # 结果抽查
        view = store.get_category(leaf0)
        assert view.id == leaf0 + N_MERGES, view
        got = store.get_content_categories("leaf-doc-0")
        assert got == {leaf0 + N_MERGES}, got
        print("抽查通过: 最早 ID -> %d, 内容分类 -> %s" % (view.id, got))
        store.close()
    finally:
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(path + suffix):
                os.unlink(path + suffix)


if __name__ == "__main__":
    main()
