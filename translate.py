"""
auto-translator: 自动翻译 Markdown 文档工具
支持本地 argos-translate 和 AI（OpenAI 风格 API）两种翻译引擎
"""
import argparse
import csv
import hashlib
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import yaml

# 条件导入 argostranslate
try:
    import argostranslate.package
    import argostranslate.translate
except ImportError:
    argostranslate = None

try:
    import requests
except ImportError:
    requests = None

logger = logging.getLogger(__name__)

# 链接正则
LINK_RE = re.compile(r'(?<!!)\[([^\]]*)\]\(([^)]+)\)')
IMAGE_RE = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')


# ─────────────────────────────────────────────
# 配置加载
# ─────────────────────────────────────────────
def load_config(path: str) -> dict:
    """加载 YAML 配置文件，填充默认值"""
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    # 全局默认值
    defaults = {
        "max_workers": 4,
        "dry_run": False,
        "quiet": False,
        "cache": True,
        "verify": False,
        "deep_translation": False,
    }
    for key, val in defaults.items():
        cfg.setdefault(key, val)

    # file_patterns 默认值
    fp = cfg.setdefault("file_patterns", {})
    fp.setdefault("include", r".*\.md$")
    fp.setdefault("exclude", "")

    return cfg


# ─────────────────────────────────────────────
# 输出路径计算
# ─────────────────────────────────────────────
def compute_output_path(
    filepath: str,
    lang: str,
    output_dir: Optional[str] = None,
    input_dir: Optional[str] = None,
) -> str:
    """
    在文件名最后一个点前插入 _lang 后缀。
    例: v1.2.md -> v1.2_zh.md, README -> README_zh
    若指定 output_dir，保持相对路径放到 output_dir 下。
    """
    base, ext = os.path.splitext(filepath)
    new_name = f"{base}_{lang}{ext}"

    if output_dir and input_dir:
        rel = os.path.relpath(new_name, input_dir)
        return os.path.join(output_dir, rel)

    return new_name


# ─────────────────────────────────────────────
# 缓存管理
# ─────────────────────────────────────────────
class CacheManager:
    def __init__(self, cache_path: str):
        self.cache_path = cache_path
        self._data: dict = {}

    def load(self):
        if os.path.exists(self.cache_path):
            with open(self.cache_path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        else:
            self._data = {}

    def save(self):
        os.makedirs(os.path.dirname(self.cache_path) or ".", exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def get_file_hash(self, filepath: str) -> str:
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def _cache_key(self, rel_path: str, lang: str) -> str:
        return f"{rel_path}::{lang}"

    def check_cache(self, rel_path: str, lang: str, output_path: str) -> bool:
        """返回 True 表示可跳过（哈希未变 + 目标文件存在且非空）"""
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            return False
        key = self._cache_key(rel_path, lang)
        if key not in self._data:
            return False
        stored_hash = self._data[key].get("hash", "")
        if not stored_hash:
            # 哈希未记录（更新时源文件不可访问），输出存在即命中
            return True
        # 若源文件可访问，比较哈希；否则只要 output 存在且有记录即命中
        if os.path.exists(rel_path):
            current_hash = self.get_file_hash(rel_path)
            return current_hash == stored_hash
        return True

    def update(self, rel_path: str, lang: str, output_path: str):
        key = self._cache_key(rel_path, lang)
        src_path = rel_path if os.path.isabs(rel_path) else rel_path
        file_hash = self.get_file_hash(src_path) if os.path.exists(src_path) else ""
        self._data[key] = {"hash": file_hash, "output": output_path}
        self.save()


# ─────────────────────────────────────────────
# Markdown 块解析
# ─────────────────────────────────────────────
def parse_md_blocks(content: str) -> list:
    """
    状态机解析，返回 [(text, translatable), ...]
    - frontmatter (--- 开头结尾) → translatable=False
    - 代码围栏 (``` 或 ~~~) → translatable=False
    - 其他文本 → translatable=True
    """
    blocks = []
    lines = content.splitlines(keepends=True)
    i = 0
    n = len(lines)

    # frontmatter: 文件开头的 ---
    if n > 0 and lines[0].rstrip() == "---":
        j = 1
        while j < n and lines[j].rstrip() != "---":
            j += 1
        if j < n:
            fm = "".join(lines[0: j + 1])
            blocks.append((fm, False))
            i = j + 1

    buf = []

    def flush_buf():
        if buf:
            blocks.append(("".join(buf), True))
            buf.clear()

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # 检测代码围栏开始（``` 或 ~~~）
        if stripped.startswith("```") or stripped.startswith("~~~"):
            flush_buf()
            fence_marker = stripped[:3]  # ``` 或 ~~~
            fence_block = [line]
            i += 1
            # 收集直到匹配的结束围栏
            while i < n:
                fence_block.append(lines[i])
                close = lines[i].strip()
                # 结束条件：行以相同的3字符开头（允许后跟空格）
                if close.startswith(fence_marker) and close.strip(fence_marker[-1]).strip() == "":
                    i += 1
                    break
                i += 1
            blocks.append(("".join(fence_block), False))
        else:
            buf.append(line)
            i += 1

    flush_buf()
    return blocks


# ─────────────────────────────────────────────
# 深度翻译：链接替换
# ─────────────────────────────────────────────
def replace_links(content: str, lang: str, translation_plan: dict, input_dir: str) -> str:
    """
    替换 Markdown 中的本地文件链接为翻译后的路径。
    - 外部 URL (http/https) → 原样保留
    - 纯锚点 (#section) → 原样保留
    - 图片链接：只翻译 alt，不改路径
    - 本地文件且在 translation_plan 中 → 替换文件名加 _lang 后缀
    - 防双重后缀：已有 _lang 后缀则不再添加
    """
    # 已有语言后缀的正则（如 _zh, _es, _ja 等）
    lang_suffix_re = re.compile(r'_[a-z]{2,5}(\.[^)]+)?$')

    def _replace_path(path: str) -> str:
        # 外部链接或锚点不处理
        if path.startswith(("http://", "https://", "#")):
            return path
        # 防双重后缀
        base, ext = os.path.splitext(path)
        if base.endswith(f"_{lang}"):
            return path
        # 解析为绝对路径，检查是否在翻译计划中
        abs_path = os.path.normpath(os.path.join(input_dir, path))
        if abs_path in translation_plan:
            return f"{base}_{lang}{ext}"
        return path

    def _sub_link(m: re.Match) -> str:
        text = m.group(1)
        path = m.group(2)
        new_path = _replace_path(path)
        return f"[{text}]({new_path})"

    def _sub_image(m: re.Match) -> str:
        # 图片：路径不变，只保留 alt
        alt = m.group(1)
        path = m.group(2)
        return f"![{alt}]({path})"

    # 先处理图片（避免被 LINK_RE 误匹配）
    result = IMAGE_RE.sub(_sub_image, content)
    result = LINK_RE.sub(_sub_link, result)
    return result


# ─────────────────────────────────────────────
# 本地翻译引擎
# ─────────────────────────────────────────────
def translate_local(text: str, src_lang: str, tgt_lang: str) -> str:
    """使用 argos-translate 进行本地翻译"""
    if argostranslate is None:
        raise RuntimeError(
            "argos-translate 未安装。请运行: pip install argos-translate\n"
            f"然后安装语言包: argospm install translate-{src_lang}_{tgt_lang}"
        )
    installed = argostranslate.translate.get_installed_languages()
    src_obj = next((l for l in installed if l.code == src_lang), None)
    tgt_obj = next((l for l in installed if l.code == tgt_lang), None)
    if src_obj is None or tgt_obj is None:
        raise RuntimeError(
            f"语言包 {src_lang}->{tgt_lang} 未安装。\n"
            f"请运行: argospm install translate-{src_lang}_{tgt_lang}"
        )
    translation = src_obj.get_translation(tgt_obj)
    return translation.translate(text)


# ─────────────────────────────────────────────
# AI 翻译引擎
# ─────────────────────────────────────────────
DEFAULT_SYSTEM_PROMPT = (
    "你是一个技术文档翻译专家，将 Markdown 内容从 {source_lang} 翻译成 {target_lang}。\n"
    "保留所有链接 URL、代码块、YAML frontmatter 的键名不变，只翻译文本和链接的描述文字。\n"
    "禁止翻译代码块内的代码。不要添加额外注释。"
)
DEFAULT_USER_PROMPT = "请将以下内容从 {source_lang} 翻译为 {target_lang}：\n\n{content}"


def translate_ai(
    content: str,
    src_lang: str,
    tgt_lang: str,
    ai_config: dict,
    glossary: Optional[list] = None,
) -> str:
    """调用 OpenAI 风格 API 进行翻译，支持指数退避重试"""
    if requests is None:
        raise RuntimeError("requests 未安装。请运行: pip install requests")

    endpoint = ai_config["endpoint"]
    api_key = ai_config["api_key"]
    model = ai_config.get("model", "gpt-4")
    temperature = ai_config.get("temperature", 0.3)
    max_tokens = ai_config.get("max_tokens", 2000)
    retry_statuses = ai_config.get("retry_statuses", [429, 500, 502, 503, 504])
    retry_max = ai_config.get("retry_max", 3)
    backoff_factor = ai_config.get("retry_backoff_factor", 2)

    sys_tmpl = ai_config.get("system_prompt", DEFAULT_SYSTEM_PROMPT)
    usr_tmpl = ai_config.get("user_prompt_template", DEFAULT_USER_PROMPT)

    system_msg = sys_tmpl.format(source_lang=src_lang, target_lang=tgt_lang)
    if glossary:
        terms = "\n".join(f"- {row[0]} → {row[1]}" for row in glossary if len(row) >= 2)
        system_msg += f"\n\n术语表：\n{terms}"

    user_msg = usr_tmpl.format(
        source_lang=src_lang, target_lang=tgt_lang, content=content
    )

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
    }

    for attempt in range(retry_max + 1):
        resp = requests.post(endpoint, json=payload, headers=headers, timeout=60)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        if resp.status_code in retry_statuses and attempt < retry_max:
            wait = backoff_factor ** attempt
            logger.warning("API 返回 %s，%ss 后重试...", resp.status_code, wait)
            time.sleep(wait)
            continue
        resp.raise_for_status()

    raise RuntimeError("翻译 API 重试次数耗尽")


# ─────────────────────────────────────────────
# 文件扫描
# ─────────────────────────────────────────────
def scan_files(config: dict) -> dict:
    """
    返回 {abs_path: [target_langs]}
    递归遍历 input_dir，按 file_patterns 过滤
    """
    input_dir = os.path.abspath(config["input_dir"])
    languages = config["languages"]
    include_pat = config["file_patterns"]["include"]
    exclude_pat = config["file_patterns"].get("exclude", "")

    plan = {}
    for root, _dirs, files in os.walk(input_dir):
        for fname in files:
            if not re.search(include_pat, fname):
                continue
            if exclude_pat and re.search(exclude_pat, fname):
                continue
            abs_path = os.path.join(root, fname)
            plan[abs_path] = list(languages)
    return plan


# ─────────────────────────────────────────────
# 单文件翻译
# ─────────────────────────────────────────────
def translate_file(
    src_path: str,
    lang: str,
    config: dict,
    cache_manager: Optional["CacheManager"],
    translation_plan: dict,
    glossary: Optional[list],
    force: bool,
) -> str:
    """翻译单个文件，返回状态字符串"""
    output_dir = config.get("output_dir")
    input_dir = os.path.abspath(config["input_dir"])
    out_path = compute_output_path(
        src_path, lang,
        output_dir=os.path.abspath(output_dir) if output_dir else None,
        input_dir=input_dir,
    )

    # 缓存检查
    if cache_manager and not force:
        if cache_manager.check_cache(src_path, lang, out_path):
            logger.info("跳过（缓存命中）: %s -> %s", src_path, out_path)
            return "cached"

    with open(src_path, "r", encoding="utf-8") as f:
        source = f.read()

    translation_type = config.get("translation_type", "local")
    src_lang = config["source_lang"]

    if translation_type == "local":
        blocks = parse_md_blocks(source)
        translated_parts = []
        for text, translatable in blocks:
            if translatable and text.strip():
                translated_parts.append(translate_local(text, src_lang, lang))
            else:
                translated_parts.append(text)
        result = "".join(translated_parts)
    else:
        result = translate_ai(source, src_lang, lang, config["ai_config"], glossary)

    if config.get("deep_translation"):
        result = replace_links(result, lang, translation_plan, input_dir)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(result)

    if cache_manager:
        cache_manager.update(src_path, lang, out_path)

    logger.info("已翻译: %s -> %s", src_path, out_path)
    return "ok"


# ─────────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="自动翻译 Markdown 文档")
    parser.add_argument("--config", required=True, help="配置文件路径")
    parser.add_argument("--force", action="store_true", help="忽略缓存强制重新翻译")
    args = parser.parse_args()

    config = load_config(args.config)

    # 配置日志
    log_level = logging.ERROR if config.get("quiet") else logging.INFO
    logging.basicConfig(level=log_level, format="%(levelname)s %(message)s")

    # 加载术语表
    glossary = None
    glossary_path = config.get("glossary")
    if glossary_path and os.path.exists(glossary_path):
        with open(glossary_path, "r", encoding="utf-8") as f:
            glossary = list(csv.reader(f))

    # 扫描文件
    translation_plan = scan_files(config)

    # dry_run 模式
    if config.get("dry_run"):
        print(f"[dry_run] 共找到 {len(translation_plan)} 个文件待翻译：")
        for path, langs in translation_plan.items():
            print(f"  {path} -> {langs}")
        return

    # verify 模式
    if config.get("verify"):
        missing = []
        for src_path, langs in translation_plan.items():
            for lang in langs:
                out = compute_output_path(
                    src_path, lang,
                    output_dir=os.path.abspath(config["output_dir"]) if config.get("output_dir") else None,
                    input_dir=os.path.abspath(config["input_dir"]),
                )
                if not os.path.exists(out):
                    missing.append(out)
        if missing:
            print(f"[verify] 缺少 {len(missing)} 个翻译文件：")
            for p in missing:
                print(f"  {p}")
        else:
            print("[verify] 所有翻译文件均存在。")
        return

    # 缓存管理
    cache_manager = None
    if config.get("cache"):
        cache_dir = config.get("output_dir", config["input_dir"])
        cache_path = os.path.join(os.path.abspath(cache_dir), ".translate_cache.json")
        cache_manager = CacheManager(cache_path)
        cache_manager.load()

    # 并发翻译
    tasks = [
        (src_path, lang)
        for src_path, langs in translation_plan.items()
        for lang in langs
    ]

    stats = {"ok": 0, "cached": 0, "error": 0}
    max_workers = config.get("max_workers", 4)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                translate_file,
                src_path, lang, config, cache_manager,
                translation_plan, glossary, args.force,
            ): (src_path, lang)
            for src_path, lang in tasks
        }
        for future in as_completed(futures):
            src_path, lang = futures[future]
            try:
                status = future.result()
                stats[status] = stats.get(status, 0) + 1
            except Exception as e:
                logger.error("翻译失败 %s [%s]: %s", src_path, lang, e)
                stats["error"] += 1

    print(
        f"完成: {stats['ok']} 已翻译, {stats['cached']} 缓存跳过, {stats['error']} 失败"
    )


if __name__ == "__main__":
    main()
