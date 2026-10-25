# Brain × Pi 协作闭环

`brain-pi-loop` 是一个 provider-neutral 的 Agent Skill：让 Brain Agent 负责理解、规划和独立验收，让 Pi Agent 负责有边界的代码修改、命令执行与测试。

> Executor 的完成报告是交接材料，不是最终验收。

它不绑定 Kimi、Moonshot 或任何特定模型。当前可以用 Codex 作为 Brain、Kimi K3 作为 Pi 中的执行模型，也可以替换两端。

## 包含什么

- `SKILL.md`：Brain 到 Pi 的任务合同、权限边界、返工和验收协议。
- `scripts/pi_bridge.py`：在本地消费 Pi JSONL，丢弃 thinking、signature 和完整工具结果，只返回紧凑交接信息。
- `scripts/pi_loop.py`：Brain 侧的分离启动（stdin 置空、独立会话、结束时只打印紧凑交接）、交接回读和会话摘要，用于接力旧会话。
- `scripts/install.py`：安装 `pi` / `pi-compact` 用户级命令，并生成不含密钥的配置。
- `references/setup.md`：macOS、Linux 和 Windows 的安装与凭据管理说明。

## 安装 Skill

将整个仓库放入兼容 [Agent Skills](https://agentskills.io/specification) 的目录。

Codex：

```sh
git clone https://github.com/Sttrevens/brain-pi-loop.git ~/.codex/skills/brain-pi-loop
```

Claude Code：

```sh
git clone https://github.com/Sttrevens/brain-pi-loop.git ~/.claude/skills/brain-pi-loop
```

如果还要安装 `pi-compact`，请阅读 [references/setup.md](references/setup.md)。安装前先运行：

```sh
python3 -m unittest discover -s scripts -p 'test_*.py' -v
python3 scripts/install.py --help
```

## 安全

- 不要把 API Key 写入 Skill、JSON 配置、prompt、日志或 shell history。
- 优先使用 macOS Keychain、Linux Secret Service 或其他操作系统凭据存储。
- 不要让 Pi 自己证明任务完成；Brain 必须重新检查真实 workspace、diff 和测试证据。

## License

[MIT](LICENSE)
