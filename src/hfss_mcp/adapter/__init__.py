"""AEDT adapter package: narrow semantic protocol + implementations."""

from hfss_mcp.adapter.fake import FakeAdapter
from hfss_mcp.adapter.protocol import AedtAdapter

__all__ = ["AedtAdapter", "FakeAdapter"]
