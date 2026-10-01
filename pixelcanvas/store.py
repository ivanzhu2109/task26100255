"""PixelCanvas 分类合并库：分类树与内容引用持久化到 SQLite。"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .errors import CategoryNotFound, MergeRejected


@dataclass(frozen=True)
class CategoryInfo:
    """分类查询结果。"""

    id: int
    name: str
    parent_id: int | None
    child_ids: tuple[int, ...]



_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES categories(id)
);
CREATE INDEX IF NOT EXISTS idx_categories_parent ON categories(parent_id);
CREATE TABLE IF NOT EXISTS aliases (
    old_id INTEGER PRIMARY KEY,
    live_id INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_aliases_live ON aliases(live_id);
CREATE TABLE IF NOT EXISTS content_refs (
    content_id INTEGER NOT NULL,
    category_id INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_refs_content ON content_refs(content_id);
CREATE INDEX IF NOT EXISTS idx_refs_category ON content_refs(category_id);
"""


class CategoryStore:
    """分类合并库主入口，由上层内容管理系统直接调用。"""

    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def initialize(
        self,
        categories: list[tuple[int, str, int | None]],
        content_refs: list[tuple[int, int]],
    ) -> None:
        """初始化分类树及内容引用。初始数据保证合法。"""
        with self._conn:
            self._conn.executemany(
                "INSERT INTO categories(id, name, parent_id) VALUES (?, ?, ?)",
                categories,
            )
            self._conn.executemany(
                "INSERT INTO content_refs(content_id, category_id) VALUES (?, ?)",
                content_refs,
            )

    def merge(self, source_id: int, target_id: int) -> bool:
        """把源分类并入目标分类。返回是否实际发生合并。"""
        src_live = self._resolve(source_id)
        tgt_live = self._resolve(target_id)
        if src_live == tgt_live:
            return False
        if self._has_ancestor_relation(src_live, tgt_live):
            raise MergeRejected(
                f"cannot merge {source_id} into {target_id}: ancestor relation"
            )
        with self._conn:
            self._merge_live(src_live, tgt_live)
        return True

    def _resolve(self, category_id: int) -> int:
        """把任意有效ID（含历史ID）解析为当前存续ID。"""
        row = self._conn.execute(
            "SELECT live_id FROM aliases WHERE old_id = ?", (category_id,)
        ).fetchone()
        if row is not None:
            return row[0]
        row = self._conn.execute(
            "SELECT 1 FROM categories WHERE id = ?", (category_id,)
        ).fetchone()
        if row is None:
            raise CategoryNotFound(f"unknown category id: {category_id}")
        return category_id

    def _has_ancestor_relation(self, a: int, b: int) -> bool:
        """单次查询判断两个存续分类是否互为祖先（含自身链）。"""
        row = self._conn.execute(
            """
            WITH RECURSIVE
            up_a(id) AS (
                SELECT parent_id FROM categories WHERE id = :a
                UNION ALL
                SELECT c.parent_id FROM categories c
                JOIN up_a ON c.id = up_a.id WHERE up_a.id IS NOT NULL
            ),
            up_b(id) AS (
                SELECT parent_id FROM categories WHERE id = :b
                UNION ALL
                SELECT c.parent_id FROM categories c
                JOIN up_b ON c.id = up_b.id WHERE up_b.id IS NOT NULL
            )
            SELECT
                EXISTS(SELECT 1 FROM up_a WHERE id = :b)
                OR EXISTS(SELECT 1 FROM up_b WHERE id = :a)
            """,
            {"a": a, "b": b},
        ).fetchone()
        return bool(row[0])

    def _merge_live(self, src_id: int, tgt_id: int) -> None:
        """执行合并：子分类按同名折叠（迭代实现，支持深层），源ID退役。"""
        stack = [(src_id, tgt_id)]
        retired = []
        while stack:
            src, tgt = stack.pop()
            children = self._conn.execute(
                "SELECT id, name FROM categories WHERE parent_id = ?", (src,)
            ).fetchall()
            for child_id, child_name in children:
                row = self._conn.execute(
                    "SELECT id FROM categories WHERE parent_id = ? AND name = ?",
                    (tgt, child_name),
                ).fetchone()
                if row is not None:
                    stack.append((child_id, row[0]))
                else:
                    self._conn.execute(
                        "UPDATE categories SET parent_id = ? WHERE id = ?",
                        (tgt, child_id),
                    )
            retired.append(src)
            self._conn.execute(
                "UPDATE aliases SET live_id = ? WHERE live_id = ?", (tgt, src)
            )
            self._conn.execute(
                "INSERT INTO aliases(old_id, live_id) VALUES (?, ?)", (src, tgt)
            )
        self._conn.executemany(
            "DELETE FROM categories WHERE id = ?", [(r,) for r in reversed(retired)]
        )

    def get_category(self, category_id: int) -> CategoryInfo:
        """查询分类（支持历史ID），返回存续ID及父子关系。"""
        row = self._conn.execute(
            """
            SELECT c.id, c.name, c.parent_id FROM categories c
            WHERE c.id = COALESCE(
                (SELECT live_id FROM aliases WHERE old_id = ?),
                (SELECT id FROM categories WHERE id = ?)
            )
            """,
            (category_id, category_id),
        ).fetchone()
        if row is None:
            raise CategoryNotFound(f"unknown category id: {category_id}")
        live_id = row[0]
        children = self._conn.execute(
            "SELECT id FROM categories WHERE parent_id = ? ORDER BY id", (live_id,)
        ).fetchall()
        return CategoryInfo(
            id=live_id,
            name=row[1],
            parent_id=row[2],
            child_ids=tuple(r[0] for r in children),
        )

    def get_content_categories(self, content_id: int) -> list[int]:
        """查询内容当前关联的存续分类去重集合。"""
        rows = self._conn.execute(
            """
            SELECT DISTINCT COALESCE(a.live_id, r.category_id)
            FROM content_refs r
            LEFT JOIN aliases a ON a.old_id = r.category_id
            WHERE r.content_id = ?
            """,
            (content_id,),
        ).fetchall()
        return [r[0] for r in rows]
