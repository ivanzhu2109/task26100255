"""祖先关系拒绝与幂等情况，验证数据不变。"""
import pytest

from pixelcanvas import CategoryStore, MergeRejected


def snapshot(store):
    cats = store._conn.execute(
        "SELECT id, name, parent_id FROM categories ORDER BY id").fetchall()
    aliases = store._conn.execute(
        "SELECT old_id, live_id FROM aliases ORDER BY old_id").fetchall()
    refs = store._conn.execute(
        "SELECT content_id, category_id FROM content_refs "
        "ORDER BY content_id, category_id").fetchall()
    return cats, aliases, refs


@pytest.fixture()
def store():
    s = CategoryStore(":memory:")
    s.initialize(
        [(1, "root", None), (2, "a", 1), (3, "b", 2), (4, "c", 1)],
        [(100, 3), (101, 4)],
    )
    return s


def test_merge_ancestor_rejected(store):
    before = snapshot(store)
    with pytest.raises(MergeRejected):
        store.merge(1, 3)      # 1 是 3 的祖先
    with pytest.raises(MergeRejected):
        store.merge(3, 1)      # 反向同样拒绝
    assert snapshot(store) == before


def test_merge_with_old_id_of_ancestor_rejected(store):
    store.merge(4, 2)          # 4 并入 2，4 成为历史ID
    before = snapshot(store)
    with pytest.raises(MergeRejected):
        store.merge(2, 3)      # 2 是 3 的祖先
    with pytest.raises(MergeRejected):
        store.merge(4, 3)      # 旧ID 4 -> 2，仍是 3 的祖先
    assert snapshot(store) == before


def test_two_old_ids_pointing_to_same_category_is_noop(store):
    store.merge(3, 4)          # 3 并入 4
    store.merge(4, 2)          # 4 并入 2；3、4 都解析到 2
    before = snapshot(store)
    assert store.merge(3, 4) is False   # 两个旧ID指向同一存续分类
    assert store.merge(2, 2) is False
    assert snapshot(store) == before
