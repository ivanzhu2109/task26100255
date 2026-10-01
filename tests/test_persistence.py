"""连续合并后用最早ID发起合并；重新打开数据后验证树、引用与旧ID解析。"""
from pixelcanvas import CategoryStore


def build(path):
    s = CategoryStore(str(path))
    s.initialize(
        [(1, "root", None), (2, "v1", 1), (3, "v2", 1), (4, "v3", 1), (5, "v4", 1)],
        [(100, 2), (101, 3), (102, 4)],
    )
    return s


def test_chain_merges_then_merge_by_earliest_id(tmp_path):
    db = tmp_path / "cats.db"
    s = build(db)
    s.merge(2, 3)              # v1 -> v2
    s.merge(3, 4)              # v2 -> v3（历史ID 2、3 跟随到 4）
    assert s.merge(2, 5)       # 用最早ID 2 发起合并，效果等同于 4 -> 5
    s.close()

    # 重新打开，验证完整状态
    s2 = CategoryStore(str(db))
    assert s2.get_category(5).child_ids == ()
    assert s2.get_category(1).child_ids == (5,)
    # 全部历代ID解析到 5
    for old in (2, 3, 4):
        assert s2.get_category(old).id == 5
    # 全部内容引用不丢失且正确归属
    assert s2.get_content_categories(100) == [5]
    assert s2.get_content_categories(101) == [5]
    assert s2.get_content_categories(102) == [5]
    s2.close()


def test_reopen_preserves_tree_and_refs(tmp_path):
    db = tmp_path / "cats.db"
    s = build(db)
    s.merge(3, 2)
    s.close()
    s2 = CategoryStore(str(db))
    tree = s2._conn.execute(
        "SELECT id, name, parent_id FROM categories ORDER BY id").fetchall()
    assert tree == [(1, "root", None), (2, "v1", 1), (4, "v3", 1), (5, "v4", 1)]
    assert s2.get_content_categories(101) == [2]
    assert s2.get_category(3).id == 2
    s2.close()
