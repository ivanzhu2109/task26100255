"""PixelCanvas 分类合并库的公共类型定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Category:
    """初始数据中的一个分类节点。"""

    id: int
    name: str
    parent_id: Optional[int]  # None 表示顶层分类


@dataclass(frozen=True)
class ContentRef:
    """一条内容到分类的直接引用。"""

    content_id: str
    category_id: int


@dataclass(frozen=True)
class CategoryView:
    """查询分类时返回的存续分类视图。"""

    id: int
    name: str
    parent_id: Optional[int]
    child_ids: tuple


@dataclass(frozen=True)
class MergeResult:
    """一次合并调用的结果。"""

    changed: bool          # False 表示源与目标已指向同一存续分类，未做任何修改
    source_id: int         # 源解析后的存续 ID
    target_id: int         # 目标解析后的存续 ID


class PixelCanvasError(Exception):
    """本库所有异常的基类。"""


class UnknownCategoryError(PixelCanvasError, KeyError):
    """给定的分类 ID 从未存在过。"""


class AncestorMergeError(PixelCanvasError, ValueError):
    """源与目标存在祖先/后代关系，拒绝合并。"""


class AlreadyInitializedError(PixelCanvasError, RuntimeError):
    """数据库已初始化，不能重复写入初始数据。"""
