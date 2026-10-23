#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""空/过简异常处理检测（_check_empty_except）回归测试

## 为什么需要它

2026-10-04 实测发现该检测器存在 **3 类假阴性**——**不报错、安静地漏掉**，
比误报危险得多：

| 漏报形态 | 原因 |
|---|---|
| `pass  # 行尾注释` | `_is_simple_body` 未剥离注释 ⇒ `"pass  # 说明"` 不匹配 |
| `return None` | 未识别为"静默吞异常" |
| `continue` | 未识别为"静默吞异常" |

**讽刺点**：`pass  # 说明我是故意吞的` 恰是最常见写法，**越是认真标注越检不出**。

修复后在本仓 `.codebuddy` 下实测：**61 条 → 110 条（新增 49 条，+80%）**，
抽查新增项均为真阳性（静默跳过导致数据缺失）。

## 测试要点

**必须用真实换行**：本环境的 shell 会把 heredoc 里的 `\\n` 转成字面 `/n`，
曾导致我三次测到"2 行假文件"、得出"多行全漏"的错误结论。
因此这里全部用三引号真实多行字符串。

运行：
    python tests/test_empty_except.py
    python tests/test_empty_except.py -v
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import quality_core_collector as cc      # noqa: E402
import quality_security as sec            # noqa: E402


def _scan(code: str):
    """写入真实文件后检测，返回命中行号列表。"""
    d = Path(tempfile.mkdtemp(prefix="ee_test_"))
    p = d / "sample.py"
    p.write_text(code, encoding="utf-8", newline="")
    col = cc.IssueCollector()
    sec._check_empty_except(p.read_text(encoding="utf-8"), str(p), col)
    return [i["line"] for i in col.issues if i["category"] == "error_handling"]


# ---------------------------------------------------------- 应检出（真阳性）
def test_multiline_pass():
    """多行 pass —— 最基本的形态。"""
    assert _scan("""def f():
    try:
        g()
    except Exception:
        pass
"""), "多行 pass 未被检出"


def test_pass_with_trailing_comment():
    """`pass  # 注释` —— 修复前**漏报**（最常见写法）。"""
    assert _scan("""def f():
    try:
        g()
    except Exception:
        pass  # 故意忽略
"""), "带行尾注释的 pass 未被检出（回退到修复前行为）"


def test_return_none():
    """`return None` —— 修复前**漏报**（静默返回 None，调用方无法区分错误）。"""
    assert _scan("""def f():
    try:
        return g()
    except Exception:
        return None
"""), "return None 未被检出（回退到修复前行为）"


def test_continue():
    """`continue` —— 修复前**漏报**（循环里静默跳过出错项）。"""
    assert _scan("""def f():
    for i in items:
        try:
            g(i)
        except Exception:
            continue
"""), "continue 未被检出（回退到修复前行为）"


def test_bare_except():
    """裸 `except:` + pass。"""
    assert _scan("""def f():
    try:
        g()
    except:
        pass
"""), "裸 except 未被检出"


def test_inline_pass():
    """同行 `except X: pass`。"""
    assert _scan("""def f():
    try:
        g()
    except Exception: pass
"""), "同行 pass 未被检出"


def test_print_only():
    """仅 print —— 属"过简"（缺日志/上报）。"""
    assert _scan("""def f():
    try:
        g()
    except Exception:
        print("err")
"""), "仅 print 未被检出"


# ------------------------------------------------- 不该检出（零误报）
def test_logged_exception_not_flagged():
    """有日志的异常处理**不该**被报（防误报回归）。"""
    assert not _scan("""def f():
    try:
        g()
    except Exception as e:
        logger.warning("failed: %s", e)
"""), "有日志的异常处理被误报"


def test_reraise_not_flagged():
    """`raise` 重新抛出不**该**被报。"""
    assert not _scan("""def f():
    try:
        g()
    except Exception:
        raise
"""), "re-raise 被误报"


def test_return_with_log_not_flagged():
    """先记录再返回 —— 不**该**被报（首行是日志调用）。"""
    assert not _scan("""def f():
    try:
        return g()
    except Exception as e:
        logger.error("bad: %s", e)
        return None
"""), "先记录再 return 被误报"


def test_return_none_expression_not_flagged():
    """`return None if cond else f()` 不该按"简单体"误报（判据限定独占一行）。"""
    assert not _scan("""def f(cond):
    try:
        return g()
    except Exception:
        return None if cond else h()
"""), "条件表达式形式的 return None 被误判为简单体"


# ------------------------------------------------------------- runner
def main():
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    verbose = "-v" in sys.argv
    passed, failed = 0, []
    print("=" * 68)
    print("  空/过简异常处理检测 —— 回归测试")
    print("=" * 68)
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  ✅ {name}")
        except AssertionError as e:
            failed.append(name)
            print(f"  ❌ {name}\n       {e}")
        except Exception as e:                   # noqa: BLE001
            failed.append(name)
            print(f"  ❌ {name}\n       {type(e).__name__}: {e}")
        if verbose:
            print(f"       ({fn.__doc__ or ''})")
    print("-" * 68)
    print(f"  {passed}/{len(tests)} 通过" + (f"，{len(failed)} 失败" if failed else " ✅"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
