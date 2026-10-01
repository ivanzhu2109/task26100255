"""PixelCanvas 分类合并库的核心存储实现（SQLite 持久化）。"""

from __future__ import annotations

import sqlite3
from typing import Iterable, Optional, Set

from .types import (
    AlreadyInitializedError,
    AncestorMergeError,
    Category,
    CategoryView,
    ContentRef,
    MergeResult,
    UnknownCategoryError,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id INTEGER
);
CREATE TABLE IF NOT EXISTS alias (
    id INTEGER PRIMARY KEY,
    live_id INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS content_ref (
    content_id TEXT NOT NULL,
    category_id INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_content_ref_content ON content_ref(content_id);
"""


class CategoryStore:
    """分类合并库入口，由上层内容管理系统直接调用。

    所有数据持久化到本地 SQLite 文件；单进程串行调用。
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        # 内存索引：存续分类树
        self._name: dict = {}
        self._parent: dict = {}
        self._children: dict = {}
        # 内存索引：历代 ID -> 当前存续 ID（惰性路径压缩）
        self._alias: dict = {}
        self._load()

    def _load(self) -> None:
        cur = self._conn.execute("SELECT id, name, parent_id FROM categories")
        for cid, name, parent_id in cur:
            self._name[cid] = name
            self._parent[cid] = parent_id
            self._children[cid] = {}
        for cid, _name, parent_id in self._conn.execute(
            "SELECT id, name, parent_id FROM categories"
        ):
            if parent_id is not None:
                self._children[parent_id][self._name[cid]] = cid
        raw_alias = {}
        for cid, live_id in self._conn.execute("SELECT id, live_id FROM alias"):
            raw_alias[cid] = live_id
        # 迭代解析链式映射并做路径压缩，避免深层递归
        for cid in raw_alias:
            self._resolve_in(raw_alias, cid)
        self._alias = raw_alias

    def close(self) -> None:
        if self._conn is not None:
            self._conn.commit()
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "CategoryStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @staticmethod
    def _resolve_in(alias_map: dict, cid: int) -> int:
        """在 alias 映射中迭代解析最终存续 ID，并沿途路径压缩。"""
        root = cid
        seen = []
        while True:
            nxt = alias_map[root]
            if nxt == root:
                break
            seen.append(root)
            root = nxt
        for item in seen:
            alias_map[item] = root
        return root

    def _resolve(self, cid: int) -> int:
        if cid not in self._alias:
            raise UnknownCategoryError(cid)
        return self._resolve_in(self._alias, cid)

    def initialize(
        self,
        categories: Iterable[Category],
        content_refs: Iterable[ContentRef],
    ) -> None:
        """写入初始分类森林与内容引用（仅允许在空库上调用一次）。"""
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key='initialized'"
        ).fetchone()
        if row is not None:
            raise AlreadyInitializedError("数据库已初始化")
        cats = list(categories)
        refs = list(content_refs)
        with self._conn:
            self._conn.executemany(
                "INSERT INTO categories(id, name, parent_id) VALUES (?,?,?)",
                [(c.id, c.name, c.parent_id) for c in cats],
            )
            self._conn.executemany(
                "INSERT INTO alias(id, live_id) VALUES (?,?)",
                [(c.id, c.id) for c in cats],
            )
            self._conn.executemany(
                "INSERT INTO content_ref(content_id, category_id) VALUES (?,?)",
                [(r.content_id, r.category_id) for r in refs],
            )
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES ('initialized','1')"
            )
        for c in cats:
            self._name[c.id] = c.name
            self._parent[c.id] = c.parent_id
            self._children[c.id] = {}
            self._alias[c.id] = c.id
        for c in cats:
            if c.parent_id is not None:
                self._children[c.parent_id][c.name] = c.id

    def merge(self, source_id: int, target_id: int) -> MergeResult:
        """把源分类并入目标分类，折叠同名子分类并转归内容引用。"""
        src = self._resolve(source_id)
        tgt = self._resolve(target_id)
        if src == tgt:
            return MergeResult(changed=False, source_id=src, target_id=tgt)
        # 祖先关系检查：沿父链向上走，任一方是另一方祖先则拒绝
        node = self._parent[src]
        while node is not None:
            if node == tgt:
                raise AncestorMergeError(
                    f"目标 {tgt} 是源 {src} 的祖先，拒绝合并"
                )
            node = self._parent[node]
        node = self._parent[tgt]
        while node is not None:
            if node == src:
                raise AncestorMergeError(
                    f"源 {src} 是目标 {tgt} 的祖先，拒绝合并"
                )
            node = self._parent[node]

        moves = []    # (child_id, new_parent_id)
        retires = []  # 退出当前树的存续 ID
        # 迭代展开同名层级，避免递归深度限制
        stack = [(src, tgt)]
        while stack:
            s_node, t_node = stack.pop()
            for child_name, child_id in list(self._children[s_node].items()):
                existing = self._children[t_node].get(child_name)
                if existing is not None:
                    stack.append((child_id, existing))
                else:
                    # 独有分支整体移入目标，保留 ID
                    del self._children[s_node][child_name]
                    self._children[t_node][child_name] = child_id
                    self._parent[child_id] = t_node
                    moves.append((child_id, t_node))
            # 源节点退出当前树，历代 ID 跟随到目标侧节点
            retires.append((s_node, t_node))

        with self._conn:
            self._conn.executemany(
                "UPDATE categories SET parent_id=? WHERE id=?",
                [(p, c) for c, p in moves],
            )
            self._conn.executemany(
                "UPDATE alias SET live_id=? WHERE id=?",
                [(t, s) for s, t in retires],
            )
            self._conn.executemany(
                "DELETE FROM categories WHERE id=?",
                [(s,) for s, _ in retires],
            )
        for s_node, t_node in retires:
            self._alias[s_node] = t_node
            parent = self._parent[s_node]
            if parent is not None and parent in self._children:
                # 父节点可能已在同一次级联合并中退出当前树
                self._children[parent].pop(self._name[s_node], None)
            del self._children[s_node]
            del self._name[s_node]
            del self._parent[s_node]
        return MergeResult(changed=True, source_id=src, target_id=tgt)

    def get_category(self, category_id: int) -> CategoryView:
        """查询分类：任意历代 ID 均可，返回其当前存续分类的信息。"""
        live = self._resolve(category_id)
        return CategoryView(
            id=live,
            name=self._name[live],
            parent_id=self._parent[live],
            child_ids=tuple(sorted(self._children[live].values())),
        )

    def list_categories(self) -> list:
        """查询分类：返回全部存续分类的 (id, name, parent_id) 列表。"""
        return [
            CategoryView(
                id=cid,
                name=self._name[cid],
                parent_id=self._parent[cid],
                child_ids=tuple(sorted(self._children[cid].values())),
            )
            for cid in sorted(self._name)
        ]

    def get_content_categories(self, content_id: str) -> Set[int]:
        """查询内容分类：返回内容当前指向的存续分类去重集合。"""
        cur = self._conn.execute(
            "SELECT category_id FROM content_ref WHERE content_id=?",
            (content_id,),
        )
        return {self._resolve(row[0]) for row in cur}
