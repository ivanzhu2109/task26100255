"""多层同名分支与独有分支混合合并。"""
import pytest

from pixelcanvas import CategoryStore


@pytest.fixture()
def store():
    #        1 root
    #   2 src            6 dst
    #   +- 3 tech        +- 7 tech
    #   |   +- 4 ai      |   +- 8 ai   (三层同名: tech/ai)
    #   +- 5 life        +- 9 sports   (各自独有分支)
    cats = [
        (1, "root", None),
        (2, "src", 1),
        (3, "tech", 2),
        (4, "ai", 3),
        (5, "life", 2),
        (6, "dst", 1),
        (7, "tech", 6),
        (8, "ai", 7),
        (9, "sports", 6),
    ]
    refs = [
        (100, 4),   # 源侧深层独有节点
        (101, 8),   # 目标侧深层节点（合并后与100同分类）
        (102, 5),   # 源侧独有分支
        (103, 9),   # 目标侧独有分支
        (104, 2),   # 源根
        (104, 6),   # 同一内容同时引用源根与目标根 -> 合并后去重
        (105, 3),   # 源侧 tech（折叠进7）
    ]
    s = CategoryStore(":memory:")
    s.initialize(cats, refs)
    s.merge(2, 6)
    return s


def test_target_keeps_id_name_position(store):
    info = store.get_category(6)
    assert info.id == 6 and info.name == "dst" and info.parent_id == 1


def test_same_name_branches_folded_keeping_target_ids(store):
    tech = store.get_category(7)
    assert tech.parent_id == 6
    assert tech.child_ids == (8,)          # 目标侧 ai 保留，源侧 ai(4) 已折叠
    assert store.get_category(8).parent_id == 7
    # 源侧历史ID解析到目标侧存续ID
    assert store.get_category(2).id == 6
    assert store.get_category(3).id == 7
    assert store.get_category(4).id == 8


def test_unique_branch_moved_with_ids_kept(store):
    life = store.get_category(5)           # 源侧独有分支整条移入目标
    assert life.id == 5 and life.name == "life" and life.parent_id == 6
    assert set(store.get_category(6).child_ids) == {5, 7, 9}


def test_no_duplicate_names_under_any_parent(store):
    rows = store._conn.execute(
        "SELECT parent_id, name, COUNT(*) c FROM categories "
        "GROUP BY parent_id, name HAVING c > 1"
    ).fetchall()
    assert rows == []


def test_content_refs_preserved_and_deduped(store):
    assert store.get_content_categories(100) == [8]      # 深层引用跟随到目标侧 ai
    assert store.get_content_categories(101) == [8]
    assert store.get_content_categories(102) == [5]      # 独有分支引用留在分支根部
    assert store.get_content_categories(103) == [9]
    assert store.get_content_categories(104) == [6]      # 源根+目标根 -> 去重
    assert store.get_content_categories(105) == [7]


def test_total_ref_count_unchanged(store):
    n = store._conn.execute("SELECT COUNT(*) FROM content_refs").fetchone()[0]
    assert n == 7
