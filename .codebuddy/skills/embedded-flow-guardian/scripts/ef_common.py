#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ef_common.py — embedded-flow-guardian 共享工具层

本模块集中解决《5SKILL使用反馈》中列出的跨 SKILL 共性问题，并在 v1.0.0 实测中
额外修正了三类检测器通病：

1. **vendor / 参考代码树混淆**（反馈问题 #2）
   - 统一黑名单 VENDOR_DIRS；所有检测器一律经 iter_project_files() 取文件
   - 识别「参考代码树」：GitHub 归档解压常见的 -master/-main 后缀，以及已知
     第三方固件名（inav/betaflight/ardupilot/px4…）。避免参考实现污染自研判定
   - 支持 config.excludePaths 精确排除（逃生舱）

2. **门禁级别只能全局设置**（反馈问题 #1，本次核心诉求）
   - resolve_level() 实现 per-module 分级：moduleLevels 按 glob 指定 gold/silver
   - severity_for() 把问题种类按级别映射为 block/warn/info

3. **大项目全量扫描性能**（反馈问题 #4）
   - 单次遍历 + 目录剪枝 + 规模上限；不做跨文件两两比较，天然 O(n)

4. **「概念提及」≠「产物存在」**（v1.0.0 实测新增）
   - 交付物识别改为两级证据：文件名（强）> 标题行（中）；正文提及（弱）默认不采信
   - 排除「分析类」文档（报告/调研/复盘/诊断…）——它们讨论交付物，但本身不是交付物

5. **基础设施检测不能沿用代码层的 vendor 口径**（v1.0.0 实测新增）
   - MDK-ARM/Debug/Release 是 IDE 工程与构建目录，对代码扫描属噪声，
     但对「构建系统是否存在」恰是关键证据 → 基础设施检测走独立的 INFRA_EXCLUDE
   - 并修正文件名令牌派生：`cmocka.h`→`cmocka`、`*.cov`→`cov`，改用词边界匹配，
     避免 `cov` 命中 recovery/coverage/discover

设计约束：纯标准库实现，可独立部署（无 CodeGuard 时自动降级）。
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
from pathlib import Path

VERSION = "1.3.1"

# --------------------------------------------------------------------------
# 1. 排除口径
# --------------------------------------------------------------------------
# 代码层排除：芯片厂商 / 中间件 / 第三方 / 参考资料 / 构建产物
VENDOR_DIRS = {
    "Drivers", "CMSIS", "Middlewares", "Libraries", "HAL", "BSP",
    "lib", "libs", "third_party", "thirdparty", "vendor", "external",
    "generated", "gen", "MAVLink",
    "资料", "文档", "doc", "docs", "reference", "references",
    "example", "examples", "demo", "sample", "samples", "示例",
    "node_modules", "dist", "__pycache__", "obj", "bin",
    ".git", ".svn", ".hg", ".idea", ".vscode", ".trae",
    ".workbuddy", ".codebuddy", ".code-guardian", ".easyeda",
}

# 基础设施检测排除：只剔版本控制与依赖，**放行** IDE 工程目录（MDK-ARM/Debug…）
INFRA_EXCLUDE_DIRS = {
    ".git", ".svn", ".hg", "node_modules", "__pycache__",
    ".idea", ".vscode", ".trae",
    ".workbuddy", ".codebuddy", ".code-guardian", ".easyeda",
}

# 参考代码树启发式：GitHub 归档后缀 + 已知第三方固件名
REFERENCE_SUFFIXES = ("-master", "-main", "-develop", "-release", "-stable")
REFERENCE_NAMES = {
    "inav", "inav-master", "betaflight", "ardupilot", "px4", "px4-autopilot",
    "cleanflight", "libopencm3", "stm32cubef4", "zephyr", "freertos",
    "linux", "u-boot", "uboot", "opencv", "tensorflow",
}

# 「分析类」文档：讨论交付物，但本身不是交付物
NON_SPEC_DOC_HINTS = (
    "报告", "report", "调研", "分析", "analysis", "复盘", "诊断", "总结",
    "反馈", "手册", "指南", "教程", "日志", "log", "记录_", "使用说明",
)

SOURCE_EXTS = {".c", ".cpp", ".cc", ".h", ".hpp", ".s", ".asm"}
DOC_EXTS = {".md", ".txt", ".rst", ".adoc"}
SHEET_EXTS = {".csv", ".xlsx", ".xls", ".json", ".yaml", ".yml", ".xml"}

MAX_FILES_DEFAULT = 20000

# 运行期注入的精确排除（来自 config.excludePaths）
_EXCLUDE_PATHS: list[str] = []


def set_exclude_paths(patterns) -> None:
    """由 ef_scan 写入 config.excludePaths（相对项目根的 glob）。"""
    global _EXCLUDE_PATHS
    _EXCLUDE_PATHS = [str(p).replace("\\", "/") for p in (patterns or [])]


def looks_like_reference(name: str) -> bool:
    """目录名是否像第三方参考代码树。"""
    low = name.lower()
    if low in REFERENCE_NAMES:
        return True
    return any(low.endswith(sfx) for sfx in REFERENCE_SUFFIXES)


# 文档目录名：VENDOR_DIRS 出于「排除第三方参考资料」把它们列入，
# 但**查找项目自身文档时必须放行**——否则 文档/pin_map.md 这类
# 项目自己的 ICD 材料会被整体屏蔽，造成「交付物存在却报告缺失」的误报。
DOC_DIR_NAMES = {"文档", "doc", "docs", "documents", "资料"}


def is_vendor(path: Path, keep_doc_dirs: bool = False) -> bool:
    """路径是否属于 vendor / 参考代码 / 构建产物（用于代码层扫描）。

    Args:
        keep_doc_dirs: 为 True 时放行文档目录（供 find_docs 使用）
    """
    for part in path.parts:
        if part in VENDOR_DIRS:
            if keep_doc_dirs and part in DOC_DIR_NAMES:
                continue
            return True
        if looks_like_reference(part):
            return True
    return False


def is_infra_excluded(path: Path) -> bool:
    """基础设施检测的排除判定（放行 IDE 工程目录）。"""
    for part in path.parts:
        if part in INFRA_EXCLUDE_DIRS or looks_like_reference(part):
            return True
    return False


def matches_cfg_exclude(rel_path: str) -> bool:
    """是否被 config.excludePaths 精确排除。"""
    norm = rel_path.replace("\\", "/")
    for pat in _EXCLUDE_PATHS:
        if fnmatch.fnmatch(norm, pat) or fnmatch.fnmatch(norm + "/", pat):
            return True
        if norm.startswith(pat.rstrip("/*")):
            return True
    return False


# 基础剪枝：版本控制与依赖目录，任何遍历都不进入
_BASE_PRUNE = {".git", ".svn", ".hg", "node_modules", "__pycache__",
               ".idea", ".vscode", ".trae"}


def _walk(root: Path, prune_names, prune_pred=None):
    """受控递归遍历。

    ⚠️ 性能关键：**在 os.walk 阶段剪枝**，而不是先走进去再逐文件过滤。
    实测某项目 15,710 个文件中 14,095 个（90%）位于第三方参考树内且最终被丢弃；
    逐文件过滤意味着每轮遍历都要 stat 这 1.4 万个文件。
    剪枝后语义完全等价（is_vendor 本就检查路径中任意一段），但代价降一个量级。
    """
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
        d = Path(dirpath)
        keep = []
        for n in dirnames:
            if n in prune_names:
                continue
            if prune_pred is not None and prune_pred(n):
                continue
            keep.append(n)
        dirnames[:] = keep
        yield d, dirnames, filenames


def iter_project_files(root: Path, exts=None, include_vendor: bool = False,
                       max_files: int = MAX_FILES_DEFAULT,
                       keep_doc_dirs: bool = False):
    """代码层遍历：排除 vendor / 参考树 / config.excludePaths。

    Args:
        keep_doc_dirs: 放行文档目录（查找项目文档时用，见 DOC_DIR_NAMES 注释）
    """
    if not include_vendor:
        def prune_pred(name):
            if name in VENDOR_DIRS:
                return not (keep_doc_dirs and name in DOC_DIR_NAMES)
            return looks_like_reference(name)
    else:
        # include_vendor=True 表示调用方明知要进入构建/IDE 目录（如需找 .hex 产物），
        # 此时只剪参考树，不剪 MDK-ARM/Debug 等
        prune_pred = looks_like_reference

    count = 0
    for d, _dirs, names in _walk(root, _BASE_PRUNE, prune_pred):
        for name in names:
            if count >= max_files:
                return
            p = d / name
            if exts is not None and p.suffix.lower() not in exts:
                continue
            if not include_vendor and is_vendor(p.relative_to(root),
                                                keep_doc_dirs=keep_doc_dirs):
                continue
            if matches_cfg_exclude(str(p.relative_to(root))):
                continue
            count += 1
            yield p


def iter_infra_files(root: Path, max_files: int = 8000):
    """基础设施遍历：放行 MDK-ARM/Debug 等工程目录，仍排除参考树与依赖。"""
    count = 0
    for d, _dirs, names in _walk(root, _BASE_PRUNE, looks_like_reference):
        for name in names:
            if count >= max_files:
                return
            p = d / name
            if is_infra_excluded(p.relative_to(root)):
                continue
            if matches_cfg_exclude(str(p.relative_to(root))):
                continue
            count += 1
            yield p


def find_user_sources(root: Path):
    return list(iter_project_files(root, exts=SOURCE_EXTS))


def find_docs(root: Path, include_vendor: bool = False):
    """项目文档与表格（用于交付物审计）。

    ⚠️ 显式 `keep_doc_dirs=True`：查找文档时若把 `文档/`、`docs/` 当 vendor 排除，
    等于自废武功——项目自己的 ICD/需求/变更记录往往正放在那里。
    """
    return list(iter_project_files(root, exts=DOC_EXTS | SHEET_EXTS,
                                   include_vendor=include_vendor,
                                   keep_doc_dirs=True))


def load_vendor_ignore(root: Path):
    """读取 CodeGuard 的 ignorePaths，用于口径对齐（只读，不改写对方文件）。"""
    cg = root / ".workbuddy" / "skills" / "CodeGuard"
    for cand in (cg / "config" / "embedded-gold.json",
                 cg / "configs" / "embedded-gold.json",
                 cg / "rules" / "embedded-gold.json"):
        if cand.is_file():
            try:
                data = json.loads(cand.read_text(encoding="utf-8"))
            except Exception:
                return []
            ig = data.get("ignorePaths") or data.get("ignore_paths") or []
            return [str(x) for x in ig if isinstance(x, str)]
    return []


# --------------------------------------------------------------------------
# 2. 门禁级别（gold / silver）+ per-module 分级
# --------------------------------------------------------------------------
LEVEL_GOLD = "gold"
LEVEL_SILVER = "silver"
DEFAULT_LEVEL = LEVEL_SILVER

LEVEL_SEVERITY = {
    LEVEL_GOLD: {"missing": "block", "weak": "warn", "hint": "info"},
    LEVEL_SILVER: {"missing": "warn", "weak": "warn", "hint": "info"},
}


def load_config(root: Path, config_arg: str | None = None) -> dict:
    candidates = []
    if config_arg:
        candidates.append(Path(config_arg))
    candidates += [root / ".ef-guardian.json",
                   root / "embedded-flow-guardian.json"]
    for c in candidates:
        if c.is_file():
            try:
                data = json.loads(c.read_text(encoding="utf-8"))
                set_exclude_paths(data.get("excludePaths"))
                return data
            except Exception:
                continue
    return {}


def resolve_level(rel_path: str, cfg: dict) -> str:
    """按 per-module 配置解析相对路径适用的门禁级别。

    配置示例：
        {"defaultLevel": "silver",
         "moduleLevels": {"<核心目录>/**": "gold"}}

    匹配规则：按声明顺序取第一个命中项（更具体的规则请写在前面）。
    """
    default = cfg.get("defaultLevel", DEFAULT_LEVEL)
    mods = cfg.get("moduleLevels") or {}
    norm = rel_path.replace("\\", "/")
    if isinstance(mods, dict):
        for pattern, level in mods.items():
            pat = str(pattern).replace("\\", "/")
            if fnmatch.fnmatch(norm, pat) or fnmatch.fnmatch(norm + "/", pat):
                if level in (LEVEL_GOLD, LEVEL_SILVER):
                    return level
    elif isinstance(mods, list):
        for item in mods:
            if not isinstance(item, dict):
                continue
            pat = str(item.get("path", "")).replace("\\", "/")
            lv = item.get("level")
            if pat and lv in (LEVEL_GOLD, LEVEL_SILVER) and fnmatch.fnmatch(norm, pat):
                return lv
    return default


def severity_for(kind: str, level: str) -> str:
    return LEVEL_SEVERITY.get(level, LEVEL_SEVERITY[LEVEL_SILVER]).get(kind, "info")


# --------------------------------------------------------------------------
# 2b. 项目特定配置访问器
# --------------------------------------------------------------------------
# 设计原则：**通用代码不得硬编码任何项目值**。
# 项目特有的目录名、串口号、字段数、参考代码树等一律由项目根的
# .ef-guardian.json 声明，通过下列访问器读取；缺省时退化到最保守的通用行为。
def cfg_core_paths(cfg: dict) -> list:
    """核心目录 glob（gold 门禁的默认对象）。未声明则返回空 → 调用方按通用兜底。"""
    v = cfg.get("corePaths")
    return [str(x) for x in v] if isinstance(v, list) else []


def cfg_preferred_ports(cfg: dict) -> list:
    """优先探测的串口。未声明则返回空 → 自动探测退化为「唯一端口」策略。"""
    v = cfg.get("preferredPorts")
    return [str(x).upper() for x in v] if isinstance(v, list) else []


def cfg_telemetry_fields(cfg: dict):
    """遥测 CSV 的期望字段数。未声明则 None（不校验字段数）。"""
    v = cfg.get("telemetryFields")
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def cfg_reference_trees(cfg: dict) -> list:
    """额外的参考代码树路径前缀（相对项目根）。"""
    v = cfg.get("referenceTrees")
    return [str(x).replace("\\", "/") for x in v] if isinstance(v, list) else []


def generic_module_levels(cfg: dict) -> dict:
    """把 corePaths 展开为 gold 门禁规则（便于未显式声明 moduleLevels 的项目）。

    返回 {glob: "gold"}；显式 moduleLevels 优先，不受此影响。
    """
    out = {}
    for p in cfg_core_paths(cfg):
        g = p if any(ch in p for ch in "*?[") else (p.rstrip("/") + "/**")
        out[g] = LEVEL_GOLD
    return out


# --------------------------------------------------------------------------
# 3. 项目画像
# --------------------------------------------------------------------------
BUILD_MARKERS = {
    "keil": ["*.uvprojx", "*.uvproj"],
    "cmake": ["CMakeLists.txt"],
    "make": ["Makefile", "makefile", "GNUmakefile"],
    "platformio": ["platformio.ini"],
    "iar": ["*.ewp"],
    "zephyr": ["west.yml", "prj.conf"],
}

CI_MARKERS = {
    "github-actions": [".github/workflows/*.yml", ".github/workflows/*.yaml"],
    "gitlab-ci": [".gitlab-ci.yml"],
    "jenkins": ["Jenkinsfile"],
    "azure-pipelines": ["azure-pipelines.yml"],
    "circleci": [".circleci/config.yml"],
}

STATIC_ANALYSIS_MARKERS = {
    "cppcheck": [".cppcheck", "cppcheck.xml", "cppcheck"],
    "clang-tidy": [".clang-tidy"],
    "coverity": ["coverity"],
    "sonar": ["sonar-project.properties"],
    "misra": ["misra"],
}

UNIT_TEST_MARKERS = {
    "unity": ["unity.c", "unity.h"],
    "cmock": ["cmock.h"],
    "ceedling": ["project.yml", "ceedling"],
    "cpputest": ["cpputest"],
    "googletest": ["gtest", "googletest"],
    "cmocka": ["cmocka.h"],
}

COVERAGE_MARKERS = {
    "gcov": ["*.gcno", "*.gcda", "*.gcov"],
    "lcov": ["lcov.info", "*.lcov", "lcov"],
    "bullseye": ["bullseye"],
    "coverage.py": [".coverage", "coverage.xml", "coverage.json"],
}

HARDCODED_VERSION_RE = re.compile(
    r'(VERSION|FW_VERSION|FIRMWARE_VERSION)\s*[:=]?\s*["\']?\s*v?\d+\.\d+\.\d+',
    re.IGNORECASE,
)

GIT_DESCRIBE_RE = re.compile(
    r'git\s+describe|GIT_VERSION|GITVERSION|version\.h\s+generated|'
    r'--dirty|BUILD_FLAGS.*GIT|SOURCE_DATE_EPOCH',
    re.IGNORECASE,
)


def _stem(pattern: str) -> str:
    """从 glob 模式派生文件名令牌。

    实例：cmocka.h→cmocka，*.cov→cov，.coverage→coverage，.clang-tidy→clang-tidy，
          Mock*.h→mock，project.yml→project（随后由 GENERIC_TOKENS 拦截）
    """
    s = pattern.strip().lower().lstrip("*")
    if s.startswith("."):          # 点前缀配置文件：.coverage / .clang-tidy
        s = s[1:]
    if "." in s:
        s = s.split(".", 1)[0]
    return s.rstrip("*")


# 过于通用的令牌：命中它们不代表真的用了某工具
# （教训：ceedling 曾因 project.yml→project 命中 05b_project_report.json 而误报）
GENERIC_TOKENS = {
    "project", "test", "tests", "main", "app", "index", "config", "core",
    "common", "utils", "util", "source", "src", "code", "file", "files",
    "data", "tmp", "temp", "build", "make", "run", "start", "setup",
}


def _word_hit(token: str, name: str) -> bool:
    """词边界匹配，避免 cov 命中 recovery、adr 命中 address。"""
    if not token or token in GENERIC_TOKENS:
        return False
    return re.search(r"(?:^|[^a-z0-9])" + re.escape(token) + r"(?:[^a-z0-9]|$)",
                     name) is not None


def _find_infra(root: Path, patterns, max_depth: int = 6):
    """在基础设施范围内按 glob 查找（递归但限深）。"""
    hits = []
    for p in _infra_files(root):
        rel = p.relative_to(root)
        if len(rel.parts) > max_depth:
            continue
        for pat in patterns:
            if fnmatch.fnmatch(p.name, pat) or fnmatch.fnmatch(str(rel).replace("\\", "/"), pat):
                hits.append(p)
                break
    return hits


# 基础设施文件列表缓存：ProjectProfile 会调用 _detect 5 次、每次最多十几个令牌，
# 若不缓存则同一批文件名被反复遍历与正则匹配（实测占 8.9s/11.1s）。
# 单进程内同一 (root, max_files) 的文件列表不变，缓存语义安全。
_INFRA_CACHE: dict = {}


def _infra_files(root: Path, max_files: int = 6000):
    key = (str(root), max_files)
    hit = _INFRA_CACHE.get(key)
    if hit is None:
        hit = list(iter_infra_files(root, max_files=max_files))
        _INFRA_CACHE[key] = hit
    return hit


def clear_caches():
    """清空遍历缓存（长驻进程或测试中目录已变化时调用）。"""
    _INFRA_CACHE.clear()


def _detect(root: Path, markers: dict, deep: bool = False):
    """识别启用的工具/系统，并保留命中证据（可审计，避免「标签不可验证」）。

    Returns:
        (found: list[str], evidence: dict[str, list[str]])  —— evidence 为相对路径
    """
    found, evidence = [], {}
    for name, patterns in markers.items():
        hits = _find_infra(root, patterns)
        if not hits and deep:
            # 深扫描：先用**便宜的子串预筛**（tok in name），命中后才跑词边界正则。
            # 子串是词边界的必要条件，因此预筛不会产生漏判。
            infra = _infra_files(root)
            for tok in (_stem(p) for p in patterns):
                if len(tok) < 3 or tok in GENERIC_TOKENS:
                    continue
                for p in infra:
                    low = p.name.lower()
                    if tok in low and _word_hit(tok, low):
                        hits.append(p)
                if hits:
                    break
        if hits:
            found.append(name)
            try:
                evidence[name] = [str(h.relative_to(root)).replace("\\", "/")
                                  for h in hits[:3]]
            except ValueError:
                evidence[name] = [h.name for h in hits[:3]]
    return found, evidence


class ProjectProfile:
    def __init__(self, root: Path):
        self.root = root
        self.build_systems, self.evidence = _detect(root, BUILD_MARKERS)
        ci, ci_ev = _detect(root, CI_MARKERS)
        self.ci_systems = ci
        self.evidence.update(ci_ev)
        sa, sa_ev = _detect(root, STATIC_ANALYSIS_MARKERS)
        self.static_analysis = sa
        self.evidence.update(sa_ev)
        tf, tf_ev = _detect(root, UNIT_TEST_MARKERS, deep=True)
        self.test_frameworks = tf
        self.evidence.update(tf_ev)
        cv, cv_ev = _detect(root, COVERAGE_MARKERS, deep=True)
        self.coverage_tools = cv
        self.evidence.update(cv_ev)
        self.has_git = (root / ".git").exists()
        self.gitattributes = root / ".gitattributes"
        self.has_lfs = False
        if self.gitattributes.is_file():
            try:
                self.has_lfs = "filter=lfs" in self.gitattributes.read_text(
                    encoding="utf-8", errors="replace")
            except Exception:
                self.has_lfs = False
        self.has_tests_dir = any(
            (root / n).is_dir() for n in ("test", "tests", "Test", "Tests",
                                          "单元测试", "仿真测试", "测试集"))
        self.doc_files = find_docs(root)
        self.source_files = find_user_sources(root)

    def rel(self, p: Path) -> str:
        try:
            return str(p.relative_to(self.root)).replace("\\", "/")
        except ValueError:
            return str(p).replace("\\", "/")

    def describe(self) -> dict:
        return {
            "root": str(self.root),
            "build_systems": self.build_systems,
            "ci_systems": self.ci_systems,
            "static_analysis": self.static_analysis,
            "test_frameworks": self.test_frameworks,
            "coverage_tools": self.coverage_tools,
            "has_git": self.has_git,
            "has_lfs": self.has_lfs,
            "has_tests_dir": self.has_tests_dir,
            "doc_count": len(self.doc_files),
            "source_count": len(self.source_files),
            "evidence": self.evidence,
        }


# --------------------------------------------------------------------------
# 4. 交付物识别（两级证据：文件名 > 标题行；正文提及不采信）
# --------------------------------------------------------------------------
DELIVERABLE_CATALOG = [
    {
        "id": "requirements", "name": "需求规格书",
        "keywords": ["需求规格", "需求说明", "requirements", "srs",
                     "产品需求", "需求清单", "需求文档", "需求基线"],
        "needed": "missing",
        "why": "需求波动会级联传导至设计/代码/测试；无需求基线则追溯无从建立",
    },
    {
        "id": "icd", "name": "接口控制文档 ICD",
        "keywords": ["icd", "icd_", "_icd", "接口控制", "接口文档",
                     "pin_map", "引脚映射", "引脚定义", "寄存器映射", "接口定义"],
        "needed": "missing",
        "why": "ICD 是硬件与固件团队之间的『合同』；缺失会导致集成期才发现接口不匹配",
    },
    {
        "id": "rtm", "name": "需求追溯矩阵 RTM",
        "keywords": ["rtm", "追溯矩阵", "追溯表", "traceability", "需求追溯",
                     "覆盖矩阵", "需求覆盖"],
        "needed": "missing",
        "why": "认证必查项；每次需求变更都会使链接静默失效，手工矩阵首次变更后即失效",
    },
    {
        "id": "compat_matrix", "name": "硬件-固件兼容矩阵",
        "keywords": ["兼容矩阵", "兼容性矩阵", "compat_matrix", "compat-matrix",
                     "compatibility_matrix", "版本矩阵", "hw_sw", "板卡版本"],
        "needed": "missing",
        "why": "缺矩阵会把面向 Rev B 的 OTA/烧录错发到 Rev A 设备",
    },
    {
        "id": "change_log", "name": "变更记录",
        "keywords": ["变更记录", "变更日志", "changelog", "change_log",
                     "change-log", "ecn", "eco记录", "改动记录"],
        "needed": "missing",
        "why": "变更未留痕则无法回答『改了什么、何时、谁、为什么』，返工不可控",
    },
    {
        "id": "release_checklist", "name": "发布准出清单",
        "keywords": ["准出", "发布检查", "release_checklist", "release-checklist",
                     "checklist", "放行", "交付检查", "准出准则", "放行准则"],
        "needed": "missing",
        "why": "无书面准出准则则真飞/量产缺乏可核验的放行依据",
    },
    {
        "id": "readme", "name": "README（项目入口）",
        "keywords": ["readme"], "needed": "weak",
        "why": "README 是唯一人人都会读的文档；缺失会显著抬高接手成本",
    },
    {
        "id": "adr", "name": "架构决策记录 ADR",
        "keywords": ["adr", "adr_", "_adr", "决策记录", "architecture_decision"],
        "needed": "hint",
        "why": "不记录理由时新人只有两条路：盲目接受 或 盲目修改",
    },
]


def _is_analysis_doc(p: Path) -> bool:
    """分析类文档：讨论交付物，但本身不是交付物。"""
    name = p.name.lower()
    return any(h in name for h in NON_SPEC_DOC_HINTS)


def _kw_hit_in_name(name_lower: str, kw: str) -> bool:
    """关键词是否命中文件名。ASCII 短词用词边界，中文用子串。"""
    kw = kw.lower()
    if kw.isascii():
        return _word_hit(kw, name_lower) or kw in name_lower.replace("-", "_")
    return kw in name_lower


def find_deliverable(profile: ProjectProfile, keywords) -> tuple[Path | None, str]:
    """定位交付物。

    Returns:
        (path | None, evidence) —— evidence ∈ {"filename", "heading", "content", "none"}
    """
    kws = [k.lower() for k in keywords]

    # 证据①：文件名（最强）
    for p in profile.doc_files:
        if _is_analysis_doc(p):
            continue
        if any(_kw_hit_in_name(p.name.lower(), k) for k in kws):
            return p, "filename"

    # 证据②：Markdown 标题行（中等）——要求标题里出现该关键词
    for p in profile.doc_files:
        if _is_analysis_doc(p) or p.suffix.lower() not in DOC_EXTS:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")[:120000]
        except Exception:
            continue
        for line in text.splitlines()[:400]:
            s = line.strip()
            if not s.startswith("#"):
                continue
            low = s.lstrip("# ").lower()
            if any(_kw_hit_in_name(low, k) for k in kws):
                return p, "heading"

    return None, "none"


def scan_keywords_in_docs(profile: ProjectProfile, keywords):
    """保留兼容接口：等价于 find_deliverable（正文提及不再单独采信）。"""
    return find_deliverable(profile, keywords)[0]


# --------------------------------------------------------------------------
# 5. IssueCollector（复用 CodeGuard，缺失时降级）
# --------------------------------------------------------------------------
def make_collector():
    try:
        import sys
        scripts = Path(__file__).resolve().parent
        cg = scripts.parent.parent / "CodeGuard" / "scripts"
        if cg.is_dir() and str(cg) not in sys.path:
            sys.path.insert(0, str(cg))
        import quality_core  # type: ignore
        return quality_core.IssueCollector()
    except Exception:
        return MiniCollector()


class MiniCollector:
    def __init__(self):
        self.issues = []

    def add(self, severity, category, file, line, message, suggestion=None, confidence=None):  # noqa: E501
        self.issues.append({
            "severity": severity, "category": category, "file": file,
            "line": line, "message": message,
            "suggestion": suggestion or "", "confidence": confidence or 0,
        })

    def summary(self):
        blocks = sum(1 for i in self.issues if i["severity"] == "block")
        warns = sum(1 for i in self.issues if i["severity"] == "warn")
        return {"blocks": blocks, "warnings": warns,
                "info": len(self.issues) - blocks - warns,
                "total_issues": len(self.issues), "avg_confidence": 0}

    def has_blocks(self):
        return any(i["severity"] == "block" for i in self.issues)

    def has_warns(self):
        return any(i["severity"] == "warn" for i in self.issues)
