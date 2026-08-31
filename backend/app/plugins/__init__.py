"""插件系统公共导出：抽象基类、数据结构与全局注册表。"""
from .base import BasePlugin, CheckinResult, FieldSpec
from .registry import registry

__all__ = ["registry", "BasePlugin", "FieldSpec", "CheckinResult"]
