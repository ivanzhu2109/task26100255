"""异常定义。"""


class MergeRejected(Exception):
    """合并被拒绝（源与目标存在祖先关系）。"""


class CategoryNotFound(Exception):
    """给定的分类ID不存在（既不是存续ID也不是历史ID）。"""
