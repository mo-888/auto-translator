# auto-translator

Python CLI 工具，递归翻译 Markdown 文档目录，支持本地引擎（argos-translate）和 AI API（OpenAI 风格）两种模式。

## 功能

- 递归扫描目录，按正则过滤文件
- **本地翻译**：argos-translate（离线，无需 API key）
- **AI 翻译**：OpenAI 风格 API（GPT-4 等）
- **深度翻译**：自动调整跨文件 Markdown 链接（`[text](file.md)` → `[text](file_zh.md)`）
- SHA256 缓存，跳过未修改文件（增量翻译）
- 并发翻译（ThreadPoolExecutor）
- `dry_run` 模式：预览待处理文件，不实际翻译
- `verify` 模式：检查翻译完整性，报告缺失文件
- 术语表支持（CSV，仅 AI 模式）

## 安装

```bash
pip install pyyaml requests
```

**本地模式额外安装语言包：**

```bash
pip install argos-translate

# 按需安装语言包（示例：英→中/西/日）
argospm install translate-en_zh
argospm install translate-en_es
argospm install translate-en_ja
```

## 快速开始

```bash
# 1. 复制并编辑配置文件
cp config.yaml my-config.yaml

# 2. 预览待翻译文件（dry_run）
python translate.py --config my-config.yaml

# 3. 执行翻译
python translate.py --config my-config.yaml

# 4. 强制重新翻译（忽略缓存）
python translate.py --config my-config.yaml --force
```

## 配置文件

```yaml
input_dir: './docs'           # 源文件根目录
output_dir: './translated'    # 输出目录（可选）
source_lang: 'en'             # 源语言
languages: ['zh', 'es', 'ja'] # 目标语言列表

file_patterns:
  include: '.*\.md$'
  exclude: '.*_zh\..*|.*_es\..*|.*_ja\..*'

translation_type: 'local'     # 'local' 或 'ai'
deep_translation: true
cache: true
max_workers: 4
dry_run: false
```

完整配置示例见 [config.yaml](config.yaml)。

## 输出文件命名

| 源文件 | 目标语言 | 输出文件 |
|--------|----------|----------|
| `docs/guide.md` | zh | `docs/guide_zh.md` |
| `v1.2.md` | es | `v1.2_es.md` |
| `README` | ja | `README_ja` |

若指定 `output_dir`，保持相对路径：`translated/docs/guide_zh.md`

## AI 模式配置

```yaml
translation_type: 'ai'
ai_config:
  endpoint: 'https://api.openai.com/v1/chat/completions'
  api_key: 'sk-xxx'          # 建议通过环境变量传入
  model: 'gpt-4'
  temperature: 0.3
  max_tokens: 2000
  retry_max: 3
  retry_backoff_factor: 2
```

**建议**：将含 API key 的配置保存为 `config.local.yaml`（已加入 `.gitignore`，不会提交）。

## 术语表（AI 模式）

CSV 格式，`source,target`：

```csv
Kubernetes,Kubernetes
API,API
open source,开源
```

配置：`glossary: './glossary.csv'`

## 运行测试

```bash
pip install pytest
python -m pytest tests/ -v
```

## 已知限制

- 本地模式：语言包需提前手动安装，工具不自动下载
- AI 模式：大文件不自动分块，受 `max_tokens` 限制
- 深度翻译：锚点链接（`#section`）不做翻译映射，可能失效
- Markdown 链接中含括号的路径（如 `file (copy).md`）暂不支持

## License

[MIT](LICENSE)
