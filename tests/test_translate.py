"""
TDD 测试文件 - RED 阶段
测试 translate.py 中尚未实现的函数
"""
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from translate import (
    compute_output_path,
    parse_md_blocks,
    replace_links,
    load_config,
    CacheManager,
)


# ─────────────────────────────────────────────
# compute_output_path
# ─────────────────────────────────────────────
class TestComputeOutputPath:
    def test_basic_md(self):
        assert compute_output_path("docs/test.md", "zh") == "docs/test_zh.md"

    def test_versioned_filename(self):
        assert compute_output_path("v1.2.md", "zh") == "v1.2_zh.md"

    def test_no_extension(self):
        assert compute_output_path("README", "zh") == "README_zh"

    def test_with_output_dir(self):
        result = compute_output_path(
            "/src/docs/guide.md", "ja",
            output_dir="/out", input_dir="/src"
        )
        assert result == "/out/docs/guide_ja.md"

    def test_lang_suffix(self):
        assert compute_output_path("file.md", "es") == "file_es.md"


# ─────────────────────────────────────────────
# parse_md_blocks
# ─────────────────────────────────────────────
class TestParseMdBlocks:
    def test_plain_text(self):
        blocks = parse_md_blocks("Hello world\n")
        assert len(blocks) >= 1
        texts = [t for t, tr in blocks if tr]
        assert any("Hello world" in t for t in texts)

    def test_frontmatter_not_translatable(self):
        content = "---\ntitle: Test\nauthor: foo\n---\n\nHello world\n"
        blocks = parse_md_blocks(content)
        fm_blocks = [(t, tr) for t, tr in blocks if "title: Test" in t]
        assert fm_blocks, "frontmatter block should exist"
        assert not fm_blocks[0][1], "frontmatter should not be translatable"

    def test_code_fence_not_translatable(self):
        content = "Some text\n\n```python\nprint('hello')\n```\n\nMore text\n"
        blocks = parse_md_blocks(content)
        code_blocks = [(t, tr) for t, tr in blocks if "print('hello')" in t]
        assert code_blocks, "code block should exist"
        assert not code_blocks[0][1], "code block should not be translatable"

    def test_tilde_fence_not_translatable(self):
        content = "~~~bash\necho hi\n~~~\n"
        blocks = parse_md_blocks(content)
        code_blocks = [(t, tr) for t, tr in blocks if "echo hi" in t]
        assert code_blocks
        assert not code_blocks[0][1]

    def test_mixed_content(self):
        content = "---\ntitle: T\n---\n\nText\n\n```\ncode\n```\n\nMore\n"
        blocks = parse_md_blocks(content)
        translatable = [t for t, tr in blocks if tr]
        non_translatable = [t for t, tr in blocks if not tr]
        assert any("Text" in t for t in translatable)
        assert any("title: T" in t for t in non_translatable)
        assert any("code" in t for t in non_translatable)


# ─────────────────────────────────────────────
# replace_links
# ─────────────────────────────────────────────
class TestReplaceLinks:
    def setup_method(self):
        self.input_dir = "/abs/docs"
        self.plan = {"/abs/docs/other.md": ["zh"]}

    def test_local_link_replaced(self):
        result = replace_links("[link](other.md)", "zh", self.plan, self.input_dir)
        assert "other_zh.md" in result

    def test_no_double_suffix(self):
        result = replace_links("[link](other_zh.md)", "zh", self.plan, self.input_dir)
        assert result == "[link](other_zh.md)"

    def test_external_link_unchanged(self):
        result = replace_links(
            "[link](https://example.com)", "zh", self.plan, self.input_dir
        )
        assert "https://example.com" in result

    def test_anchor_link_unchanged(self):
        result = replace_links("[sec](#section)", "zh", self.plan, self.input_dir)
        assert result == "[sec](#section)"

    def test_image_path_unchanged(self):
        result = replace_links("![alt](img.png)", "zh", self.plan, self.input_dir)
        assert "img.png" in result

    def test_link_not_in_plan_unchanged(self):
        result = replace_links("[x](unknown.md)", "zh", self.plan, self.input_dir)
        assert result == "[x](unknown.md)"


# ─────────────────────────────────────────────
# load_config
# ─────────────────────────────────────────────
class TestLoadConfig:
    def test_defaults_filled(self, tmp_path):
        cfg_file = tmp_path / "cfg.yaml"
        cfg_file.write_text(
            "input_dir: ./docs\nsource_lang: en\nlanguages: [zh]\n"
            "translation_type: local\n"
        )
        cfg = load_config(str(cfg_file))
        assert cfg["max_workers"] == 4
        assert cfg["dry_run"] is False
        assert cfg["quiet"] is False
        assert cfg["cache"] is True
        assert cfg["verify"] is False
        assert cfg["deep_translation"] is False

    def test_file_patterns_defaults(self, tmp_path):
        cfg_file = tmp_path / "cfg.yaml"
        cfg_file.write_text(
            "input_dir: ./docs\nsource_lang: en\nlanguages: [zh]\n"
            "translation_type: local\n"
        )
        cfg = load_config(str(cfg_file))
        assert "file_patterns" in cfg
        assert cfg["file_patterns"]["include"] == r".*\.md$"
        assert cfg["file_patterns"]["exclude"] == ""

    def test_user_values_not_overridden(self, tmp_path):
        cfg_file = tmp_path / "cfg.yaml"
        cfg_file.write_text(
            "input_dir: ./docs\nsource_lang: en\nlanguages: [zh]\n"
            "translation_type: local\nmax_workers: 8\ndry_run: true\n"
        )
        cfg = load_config(str(cfg_file))
        assert cfg["max_workers"] == 8
        assert cfg["dry_run"] is True


# ─────────────────────────────────────────────
# CacheManager
# ─────────────────────────────────────────────
class TestCacheManager:
    def test_check_cache_miss_no_output(self, tmp_path):
        cache_path = str(tmp_path / "cache.json")
        cm = CacheManager(cache_path)
        cm.load()
        result = cm.check_cache("docs/test.md", "zh", str(tmp_path / "test_zh.md"))
        assert result is False

    def test_check_cache_hit(self, tmp_path):
        src = tmp_path / "test.md"
        src.write_text("hello")
        out = tmp_path / "test_zh.md"
        out.write_text("你好")
        cache_path = str(tmp_path / "cache.json")
        cm = CacheManager(cache_path)
        cm.load()
        cm.update("docs/test.md", "zh", str(out))
        # 重新加载，模拟下次运行
        cm2 = CacheManager(cache_path)
        cm2.load()
        result = cm2.check_cache("docs/test.md", "zh", str(out))
        assert result is True

    def test_check_cache_miss_output_deleted(self, tmp_path):
        out = tmp_path / "test_zh.md"
        out.write_text("你好")
        cache_path = str(tmp_path / "cache.json")
        cm = CacheManager(cache_path)
        cm.load()
        cm.update("docs/test.md", "zh", str(out))
        out.unlink()
        cm2 = CacheManager(cache_path)
        cm2.load()
        result = cm2.check_cache("docs/test.md", "zh", str(out))
        assert result is False
