#!/usr/bin/env python3
"""
Governance Hub Tag Manager — facade 入口（向后兼容）。
实现已拆分至 tag_store / tag_api / tag_check / tag_export / tag_cli。
"""
from tag_api import (  # noqa: F401
    list_tags,
    apply_tag,
    remove_tag,
    get_constraints,
    validate_tags,
)
from tag_check import check_violation  # noqa: F401
from tag_export import export_constraint_doc  # noqa: F401
from tag_cli import main  # noqa: F401


if __name__ == "__main__":
    main()
