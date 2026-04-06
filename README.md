# micro-local-claude-code

一个可本地运行的“简化版 Claude Code CLI”，目标是：

- 保留主流 Coding Agent CLI 的核心交互体验（REPL + 工具调用 + 安全确认）
- 使用本地小模型（MiniMind）完成端到端对话与工具协作
- 提供尽可能开箱即用的一键脚本与排错路径

---

## 1. 这个仓库是做什么的

`micro-local-claude-code` 是一个桥接层项目，连接了两类能力：

- `claude-code-from-scratch/python_version`：提供简化版 Agent Loop、工具协议、CLI 交互思路
- `minimind`：提供本地 64M 模型与 OpenAI 兼容服务（`scripts/serve_openai_api.py`）

最终效果：你可以在本地终端运行一个“类似 CC CLI”的小型编码助手，不依赖云端模型。

---

## 2. 与两个上游仓库的关系与区别

### 与 `claude-code-from-scratch` 的关系

- 关系：借鉴其 Python 版最小 Agent 架构（消息循环、工具调用、命令行 REPL）
- 区别：本仓库不再面向 Anthropic/OpenAI 云 API，而是默认面向本地 MiniMind 服务

### 与 `minimind` 的关系

- 关系：复用其模型与 OpenAI 兼容推理服务
- 区别：本仓库不做模型训练/评测，专注“CLI Agent 产品层”（交互、工具、稳定性、排错）

### 本仓库的定位

- 不是模型仓库（不训练）
- 不是教程仓库（不展开教学文档体系）
- 是“可跑的本地 Agent CLI 集成仓库”

---

## 3. 功能概览

- 本地 REPL（交互式）与 one-shot（单次提问）
- 6 个基础工具：
  - `read_file`
  - `write_file`
  - `edit_file`
  - `list_files`
  - `grep_search`
  - `run_shell`
- 危险操作确认（可 `--yolo` 跳过）
- 默认连接 `http://127.0.0.1:8998/v1`
- 默认尝试自动拉起 MiniMind 服务
- localhost 自动绕过代理（避免常见 `502`）
- 流式失败自动降级非流式（提升兼容性）
- 服务日志自动落盘（便于启动失败排查）
- 首次运行自动下载 `minimind-3`（后续复用本地缓存，不重复下载）

---

## 4. 如何使用这个仓库

### 4.1 一条命令直接开始对话（推荐）

```bash
cd micro-local-claude-code
./scripts/start_chat.sh
```

脚本行为：

- 校验本地模型目录（`models/minimind-3`）
- 首次缺失时自动下载 `minimind-3`
- 若 `.venv` 不存在则自动创建
- 若依赖缺失则自动安装
- 启动本地服务并进入 REPL

你也可以 one-shot：

```bash
./scripts/start_chat.sh "sigmoid函数公式"
```

### 4.2 手动初始化（可选）

```bash
./scripts/setup_local.sh
```

### 4.3 交互命令（REPL）

- `/help`：显示命令帮助
- `/clear`：清空当前会话
- `/status`：显示当前模型与消息数
- `/exit`：退出

### 4.4 手动启动服务（可选）

如果你想自行管理 MiniMind 服务：

```bash
cd ../minimind/scripts
python serve_openai_api.py --load_from ../../micro-local-claude-code/models/minimind-3 --device cpu
```

再在本仓库连接：

```bash
python -m micro_local_claude --no-auto-start-server --api-base http://127.0.0.1:8998/v1
```

---

## 5. 如何阅读这个仓库

建议按下面顺序阅读，最快建立完整心智模型：

1. `README.md`  
   先理解目标、启动方式、排错路径

2. `micro_local_claude/cli.py`  
   看 CLI 参数、自动拉服务、REPL 循环、代理处理

3. `micro_local_claude/agent.py`  
   看消息循环、工具调用、流式与非流式 fallback

4. `micro_local_claude/tools.py`  
   看 6 个工具定义与执行实现

5. `micro_local_claude/prompt.py`  
   看系统提示词构建逻辑

6. `scripts/start_chat.sh`  
   看“一键开聊”脚本如何做校验、装依赖、启动

7. `scripts/setup_local.sh`  
   看手动初始化脚本

---

## 6. 目录结构

```text
micro-local-claude-code/
├── .gitignore
├── main.py
├── requirements.txt
├── scripts/
│   ├── setup_local.sh
│   └── start_chat.sh
├── models/
│   └── minimind-3/
│       ├── config.json
│       ├── generation_config.json
│       ├── model.safetensors
│       ├── special_tokens_map.json
│       ├── tokenizer.json
│       ├── tokenizer_config.json
│       └── chat_template.jinja
└── micro_local_claude/
    ├── __init__.py
    ├── __main__.py
    ├── agent.py
    ├── cli.py
    ├── prompt.py
    └── tools.py
```

---

## 7. 常用参数

- `--model`：发送给 API 的模型名称（默认 `minimind-local`）
- `--api-base`：OpenAI 兼容 API 地址（默认 `http://127.0.0.1:8998/v1`）
- `--api-key`：API Key（本地默认 `sk-local`）
- `--server-script`：MiniMind 服务脚本路径
- `--model-path`：MiniMind 模型目录
- `--device`：`cpu` / `cuda` / `mps`
- `--no-auto-start-server`：禁用自动启动本地服务
- `--yolo`：跳过危险操作确认
- `--server-log-file`：指定 MiniMind 服务日志路径

---

## 8. 启动排错

自动启动失败时，CLI 会提示日志路径。默认日志目录：

```bash
ls .micro-local-claude/logs
```

常见原因：

- MiniMind 依赖未安装完整（尤其 `torch` / `transformers` / `fastapi` / `uvicorn`）
- `--model-path` 不正确，目录缺少 `config.json` 等模型文件
- 本机 Python 与 torch 组合不兼容
- 缺少同级 `../minimind` 仓库（本项目复用其 `scripts/serve_openai_api.py`）

---

## 9. 本次落地踩坑与解决汇总

### 坑 1：本地请求报 `502`

- 现象：OpenAI SDK 请求 `127.0.0.1:8998` 报 `502`
- 原因：系统代理变量导致 localhost 请求也被代理
- 解决：在 CLI 中对 localhost 自动清理 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY`，并补 `NO_PROXY`

### 坑 2：MiniMind 服务启动失败但看不到原因

- 现象：只看到“服务启动失败”，缺乏定位信息
- 原因：原先把服务输出丢弃到 `DEVNULL`
- 解决：服务 stdout/stderr 落盘到 `.micro-local-claude/logs/*.log`，并在报错里打印日志路径

### 坑 3：流式输出不稳定（空回答或异常）

- 现象：stream=True 时回答极短或失败
- 原因：部分本地 OpenAI 兼容实现对流式协议兼容不稳定
- 解决：保留流式优先，同时在失败或空响应时自动 fallback 到非流式

### 坑 4：依赖安装中出现 pycache/权限问题

- 现象：`pip` 在受限环境编译字节码时报权限错误
- 解决：安装 MiniMind 依赖时使用 `--no-compile`

### 坑 5：`.venv` 被误纳入 Git

- 现象：大量 `.venv` 文件进入暂存区
- 解决：新增标准 `.gitignore`，并执行 `git rm -r --cached -f .venv` 清理索引（不删本地）

---

## 10. 参考链接

- MiniMind：
  - [README_en](https://github.com/jingyaogong/minimind/blob/master/README_en.md)
  - [HuggingFace Collection](https://huggingface.co/collections/jingyaogong/minimind-66caf8d999f5c7fa64f399e5)
- Claude Code from Scratch：
  - [python_version](https://github.com/whoislance/claude-code-from-scratch/tree/main/python_version)
