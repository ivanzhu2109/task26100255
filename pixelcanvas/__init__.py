"""PixelCanvas 分类合并库：分类合并、历史 ID 解析与内容引用转归。"""

from .store import CategoryStore
from .types import (
    AlreadyInitializedError,
    AncestorMergeError,
    Category,
    CategoryView,
    ContentRef,
    MergeResult,
    PixelCanvasError,
    UnknownCategoryError,
)

__all__ = [
    "CategoryStore",
    "Category",
    "CategoryView",
    "ContentRef",
    "MergeResult",
    "PixelCanvasError",
    "UnknownCategoryError",
    "AncestorMergeError",
    "AlreadyInitializedError",
]
