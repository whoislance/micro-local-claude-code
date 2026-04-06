# micro-local-claude-code

一个本地可运行的「简化版 claude-code」，整合了：

- `claude-code-from-scratch/python_version` 的最小 Agent Loop + Tool Calling 架构
- `minimind` 的本地 OpenAI 兼容推理服务（`scripts/serve_openai_api.py`）

## 功能

- 本地 REPL（交互式）
- One-shot 模式（单次问答）
- 6 个基础工具：`read_file` / `write_file` / `edit_file` / `list_files` / `grep_search` / `run_shell`
- 危险操作确认（可用 `--yolo` 关闭）
- 默认连接 `http://127.0.0.1:8998/v1`
- 默认会尝试自动拉起 `../minimind/scripts/serve_openai_api.py`
- 对 localhost 自动绕过代理，避免常见 `502`
- 流式失败自动降级为非流式，提升兼容性
- 内置服务日志文件，启动失败可直接排查

## 目录结构

```text
micro-local-claude-code/
├── main.py
├── requirements.txt
└── micro_local_claude/
    ├── __init__.py
    ├── __main__.py
    ├── agent.py
    ├── cli.py
    ├── prompt.py
    └── tools.py
```

## 安装

```bash
cd /Users/yuledev/repo/micro-local-claude-code
./scripts/setup_local.sh
```

可选：指定模型目录（默认 `../minimind-3`）：

```bash
./scripts/setup_local.sh /path/to/minimind-3
```

> `setup_local.sh` 会自动：
> - 创建 `.venv`
> - 安装本仓库依赖与 `minimind` 依赖
> - 补装 `fastapi` / `uvicorn`
> - 若模型不存在则尝试下载 `minimind-3`

## 模型准备

需要先下载 MiniMind 的 transformers 格式模型目录（示例：`minimind-3`），然后把目录路径传给 `--model-path`。

官方参考：
- [MiniMind README_en](https://github.com/jingyaogong/minimind/blob/master/README_en.md)
- [MiniMind HuggingFace Collection](https://huggingface.co/collections/jingyaogong/minimind-66caf8d999f5c7fa64f399e5)

## 使用

### 1) 交互模式（默认自动拉起本地 MiniMind 服务）

```bash
python -m micro_local_claude --model minimind-local --model-path /path/to/minimind-3
```

交互命令（接近主流 CC CLI）：

- `/help`: 显示帮助
- `/clear`: 清空当前会话
- `/status`: 查看当前模型与消息数
- `/exit`: 退出

### 2) 单次模式

```bash
python -m micro_local_claude --model-path /path/to/minimind-3 "帮我看下当前目录的文件结构"
```

### 3) 手动启动服务后再连接

如果你已经在另一个终端启动了 MiniMind 服务：

```bash
cd /Users/yuledev/repo/minimind/scripts
python serve_openai_api.py --load_from /path/to/minimind-3 --device cpu
```

那么在本仓库可用：

```bash
python -m micro_local_claude --no-auto-start-server --api-base http://127.0.0.1:8998/v1
```

## 常用参数

- `--model`: 发送给 API 的模型名称（默认 `minimind-local`）
- `--api-base`: OpenAI 兼容 API 地址（默认 `http://127.0.0.1:8998/v1`）
- `--api-key`: API Key（本地可用默认 `sk-local`）
- `--server-script`: MiniMind 服务脚本路径（默认 `../minimind/scripts/serve_openai_api.py`）
- `--model-path`: MiniMind 模型目录（默认 `../minimind/model`，通常需要改成你下载后的目录）
- `--device`: `cpu` / `cuda` / `mps`
- `--no-auto-start-server`: 禁用自动启动本地服务
- `--yolo`: 跳过危险操作确认
- `--server-log-file`: 指定 MiniMind 服务日志文件路径

## 启动排错

若自动启动失败，CLI 会输出日志路径。可直接查看：

```bash
ls .micro-local-claude/logs
```

常见原因：

- 未安装 MiniMind 依赖（尤其 `torch` / `transformers` / `fastapi` / `uvicorn`）
- `--model-path` 未指向可用的 transformers 模型目录
- 本机 Python/torch 版本不兼容

## 来源说明

- 简化 claude-code 架构参考：`claude-code-from-scratch/python_version`
- 本地 64M 模型与服务参考：`minimind`
