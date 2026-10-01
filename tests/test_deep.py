"""5000层深层同名分支完整合并，不因层数截断。"""
from pixelcanvas import CategoryStore

DEPTH = 5000


def make_chain(start, name, parent):
    cats = []
    prev = parent
    for i in range(start, start + DEPTH):
        cats.append((i, name, prev))
        prev = i
    return cats


def test_deep_same_name_chains_fold_fully():
    s = CategoryStore(":memory:")
    cats = [(10_000_000, "root", None)]
    cats += make_chain(1, "node", 10_000_000)            # 源链 1..5000
    cats += make_chain(5001, "node", 10_000_000)         # 目标链 5001..10000
    refs = [(1, 5000), (2, 10_000), (3, 2500)]           # 源链底/目标链底/源链中
    s.initialize(cats, refs)

    assert s.merge(1, 5001)

    # 源链全部退役，逐级折叠到目标链对应层
    live = {r[0] for r in s._conn.execute("SELECT id FROM categories")}
    assert live == {10_000_000} | set(range(5001, 10001))
    for i in range(1, DEPTH + 1):
        assert s.get_category(i).id == 5000 + i
    # 深层引用不丢失、不截断
    assert s.get_content_categories(1) == [10_000]
    assert s.get_content_categories(2) == [10_000]
    assert s.get_content_categories(3) == [7500]
    # 目标链结构完整
    assert s.get_category(10_000).parent_id == 9999
