"""PixelCanvas 分类合并库的自动化测试（stdlib unittest）。"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pixelcanvas import (
    AlreadyInitializedError,
    AncestorMergeError,
    Category,
    CategoryStore,
    ContentRef,
    UnknownCategoryError,
)


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.path)

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(self.path + suffix):
                os.unlink(self.path + suffix)

    def open_store(self):
        return CategoryStore(self.path)

    def tree_snapshot(self, store):
        return sorted(
            (c.id, c.name, c.parent_id) for c in store.list_categories()
        )


class TestMixedMerge(StoreTestCase):
    """多层同名分支与独有分支混合的合并。"""

    def build(self):
        # 源树 A(1): sub(3){leaf(5), onlyA(7)}, uniqueA(8)
        # 目标树 B(2): sub(4){leaf(6), onlyB(9)}, uniqueB(10)
        cats = [
            Category(1, "A", None),
            Category(2, "B", None),
            Category(3, "sub", 1),
            Category(4, "sub", 2),
            Category(5, "leaf", 3),
            Category(6, "leaf", 4),
            Category(7, "onlyA", 3),
            Category(8, "uniqueA", 1),
            Category(9, "onlyB", 4),
            Category(10, "uniqueB", 2),
        ]
        refs = [
            ContentRef("c-src-root", 1),
            ContentRef("c-src-sub", 3),
            ContentRef("c-src-leaf", 5),
            ContentRef("c-src-onlyA", 7),
            ContentRef("c-src-uniqueA", 8),
            ContentRef("c-tgt-root", 2),
            ContentRef("c-tgt-sub", 4),
            ContentRef("c-tgt-leaf", 6),
            ContentRef("c-tgt-onlyB", 9),
            ContentRef("c-both", 1),
            ContentRef("c-both", 2),
            ContentRef("c-both-sub", 3),
            ContentRef("c-both-sub", 4),
            ContentRef("c-both-leaf", 5),
            ContentRef("c-both-leaf", 6),
        ]
        store = self.open_store()
        store.initialize(cats, refs)
        return store

    def test_target_ids_and_names_preserved(self):
        with self.build() as s:
            s.merge(1, 2)
            view = s.get_category(2)
            self.assertEqual(view.id, 2)
            self.assertEqual(view.name, "B")
            self.assertIsNone(view.parent_id)
            # 同名层级保留目标侧 ID：sub=4, leaf=6
            self.assertEqual(s.get_category(3).id, 4)
            self.assertEqual(s.get_category(5).id, 6)
            self.assertEqual(s.get_category(4).name, "sub")
            self.assertEqual(s.get_category(6).name, "leaf")

    def test_unique_branches_moved_intact(self):
        with self.build() as s:
            s.merge(1, 2)
            # 源独有分支整体移入目标并保留 ID 与内部结构
            self.assertEqual(s.get_category(8).parent_id, 2)
            # 深层独有分支跟随同名节点落到目标侧
            self.assertEqual(s.get_category(7).parent_id, 4)
            # 目标原有分支不动
            self.assertEqual(s.get_category(10).parent_id, 2)
            self.assertEqual(s.get_category(9).parent_id, 4)
            # 最终森林合法：各父级下无重名
            seen = set()
            for c in s.list_categories():
                key = (c.parent_id, c.name)
                self.assertNotIn(key, seen)
                seen.add(key)
            self.assertEqual(
                self.tree_snapshot(s),
                [
                    (2, "B", None),
                    (4, "sub", 2),
                    (6, "leaf", 4),
                    (7, "onlyA", 4),
                    (8, "uniqueA", 2),
                    (9, "onlyB", 4),
                    (10, "uniqueB", 2),
                ],
            )

    def test_content_refs_transferred_and_deduped(self):
        with self.build() as s:
            s.merge(1, 2)
            expected = {
                "c-src-root": {2},
                "c-src-sub": {4},
                "c-src-leaf": {6},
                "c-src-onlyA": {7},
                "c-src-uniqueA": {8},
                "c-tgt-root": {2},
                "c-tgt-sub": {4},
                "c-tgt-leaf": {6},
                "c-tgt-onlyB": {9},
                "c-both": {2},
                "c-both-sub": {4},
                "c-both-leaf": {6},
            }
            for content_id, want in expected.items():
                self.assertEqual(
                    s.get_content_categories(content_id), want, content_id
                )

    def test_old_ids_usable_for_later_merge(self):
        with self.build() as s:
            s.merge(1, 2)
            # 用已退出的旧 ID 继续发起合并，效果等同于其存续 ID
            s.merge(5, 9)
            self.assertEqual(s.get_category(6).id, 9)
            self.assertEqual(s.get_category(5).id, 9)
            self.assertEqual(s.get_content_categories("c-src-leaf"), {9})
            self.assertEqual(s.get_content_categories("c-tgt-leaf"), {9})


class TestChainMergeAndReopen(StoreTestCase):
    """连续合并后用最早 ID 发起合并，并重开数据验证。"""

    def test_chain_merge_then_reopen(self):
        cats = [Category(100, "P", None), Category(200, "T", None)]
        cats += [Category(i, "c%d" % i, 100) for i in range(5)]
        refs = []
        for i in range(5):
            refs.append(ContentRef("doc-%d" % i, i))
        refs.append(ContentRef("shared", 0))
        refs.append(ContentRef("shared", 3))
        with self.open_store() as s:
            s.initialize(cats, refs)
            # 连续并入：0->1->2->3->4，每次都用最早 ID 0 发起
            for i in range(1, 5):
                r = s.merge(0, i)
                self.assertTrue(r.changed)
                self.assertEqual(r.source_id, i - 1)
                self.assertEqual(r.target_id, i)
            # 再用最早 ID 0 并入独立目标 200
            s.merge(0, 200)
            self.assertEqual(s.get_category(0).id, 200)
            for i in range(5):
                self.assertEqual(s.get_category(i).id, 200)
        # 重新打开后验证完整树、全部引用与旧 ID 解析
        with self.open_store() as s:
            self.assertEqual(
                self.tree_snapshot(s),
                [(100, "P", None), (200, "T", None)],
            )
            for i in range(5):
                self.assertEqual(s.get_category(i).id, 200)
                self.assertEqual(
                    s.get_content_categories("doc-%d" % i), {200}
                )
            self.assertEqual(s.get_content_categories("shared"), {200})
            # 重开后旧 ID 仍可发起合并
            r = s.merge(3, 100)
            self.assertTrue(r.changed)
            self.assertEqual(s.get_category(200).id, 100)
            self.assertEqual(s.get_category(3).id, 100)
            self.assertEqual(s.get_content_categories("doc-4"), {100})


class TestRejectAndNoop(StoreTestCase):
    """祖先关系拒绝与同源 noop，数据保持不变。"""

    def build(self):
        cats = [
            Category(1, "A", None),
            Category(2, "sub", 1),
            Category(3, "leaf", 2),
            Category(4, "B", None),
        ]
        refs = [ContentRef("doc", 3), ContentRef("doc2", 4)]
        store = self.open_store()
        store.initialize(cats, refs)
        return store

    def snapshot(self, s):
        return (
            self.tree_snapshot(s),
            s.get_content_categories("doc"),
            s.get_content_categories("doc2"),
        )

    def test_ancestor_rejected_both_directions(self):
        with self.build() as s:
            before = self.snapshot(s)
            with self.assertRaises(AncestorMergeError):
                s.merge(1, 3)  # 源是目标的祖先
            with self.assertRaises(AncestorMergeError):
                s.merge(3, 1)  # 目标是源的祖先
            with self.assertRaises(AncestorMergeError):
                s.merge(2, 3)  # 直接父子
            self.assertEqual(self.snapshot(s), before)

    def test_same_live_category_is_noop(self):
        with self.build() as s:
            s.merge(4, 1)  # 旧 ID 4 与 1 指向同一存续分类
            before = self.snapshot(s)
            self.assertFalse(s.merge(4, 1).changed)
            self.assertFalse(s.merge(1, 4).changed)
            self.assertFalse(s.merge(4, 4).changed)
            self.assertEqual(self.snapshot(s), before)

    def test_unknown_id_raises(self):
        with self.build() as s:
            with self.assertRaises(UnknownCategoryError):
                s.get_category(999)
            with self.assertRaises(UnknownCategoryError):
                s.merge(999, 1)
            with self.assertRaises(UnknownCategoryError):
                s.merge(1, 999)

    def test_double_initialize_rejected(self):
        with self.build() as s:
            with self.assertRaises(AlreadyInitializedError):
                s.initialize([Category(9, "x", None)], [])


class TestDeepTree(StoreTestCase):
    """5000 层深层同名分支必须完整合并，不因层数截断。"""

    def test_deep_same_name_branches(self):
        depth = 5000
        cats = [Category(1, "rootA", None), Category(2, "rootB", None)]
        for i in range(depth):
            parent = 1 if i == 0 else 10 + i - 1
            cats.append(Category(10 + i, "chain", parent))
        for i in range(depth):
            parent = 2 if i == 0 else 50010 + i - 1
            cats.append(Category(50010 + i, "chain", parent))
        # 最深处各挂一个独有叶子
        cats.append(Category(90001, "deepA", 10 + depth - 1))
        cats.append(Category(90002, "deepB", 50010 + depth - 1))
        refs = [
            ContentRef("deep-a", 90001),
            ContentRef("deep-b", 90002),
            ContentRef("mid-a", 10 + depth // 2),
        ]
        with self.open_store() as s:
            s.initialize(cats, refs)
            s.merge(1, 2)
            # 全部源侧 chain 节点退出，解析到目标侧对应层级
            self.assertEqual(s.get_category(10).id, 50010)
            self.assertEqual(
                s.get_category(10 + depth - 1).id, 50010 + depth - 1
            )
            self.assertEqual(s.get_category(1).id, 2)
            # 深层独有叶子跟随到目标侧最深处
            self.assertEqual(
                s.get_category(90001).parent_id, 50010 + depth - 1
            )
            self.assertEqual(s.get_content_categories("deep-a"), {90001})
            self.assertEqual(
                s.get_content_categories("mid-a"), {50010 + depth // 2}
            )
            # 两棵树的 chain 折叠成一条
            self.assertEqual(len(s.list_categories()), 1 + depth + 2)


if __name__ == "__main__":
    unittest.main()
