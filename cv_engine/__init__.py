"""板书数字化 · 纯算法内核（零 Web 依赖，仅标准库）。

阶段实现请只依赖这三个模块：
    from cv_engine import contracts as k          # 字段权威
    from cv_engine import RunWriter, BoardItem     # 唯一落盘口
    from cv_engine.schema import validate_manifest
"""
from . import contracts
from .contracts import *          # noqa: F401,F403  —— 契约类型与常量
from .writer import ExperimentWriter, RunWriter


def __getattr__(name):
    """schema 相关按需加载：保证 `python -m cv_engine.schema` 不触发 runpy 警告。"""
    if name in ("schema", "validate_manifest", "validate_file", "export",
                "MANIFEST_SCHEMA", "EXPERIMENT_SCHEMA", "SCHEMA_FILES"):
        import importlib
        mod = importlib.import_module(".schema", __name__)
        return mod if name == "schema" else getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["contracts", "RunWriter", "ExperimentWriter", *contracts.__all__]
