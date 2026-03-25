# Claude Telegram Bot

通过 Telegram 与 Claude Code 对话，支持 SQLite 持久化上下文记忆。

## 功能

- 每条消息自动携带历史上下文（最近 20 轮）
- SQLite 本地存储对话记录，重启不丢失
- 支持白名单限制访问用户
- 长消息自动分段发送

## 命令

| 命令 | 说明 |
|------|------|
| `/start` | 查看当前上下文轮数 |
| `/clear` | 清除对话记忆，重新开始 |
| `/history` | 查看最近 5 轮对话摘要 |

## 安装

```bash
pip install python-telegram-bot
```

## 配置

设置以下环境变量：

| 变量 | 必填 | 说明 |
|------|------|------|
| `TELEGRAM_BOT_TOKEN` | 是 | 从 [@BotFather](https://t.me/BotFather) 获取 |
| `ALLOWED_USER_IDS` | 否 | 允许使用的用户 ID，逗号分隔，留空不限制 |
| `CLAUDE_BIN` | 否 | claude 可执行文件路径，默认 `claude` |

## 启动

```bash
TELEGRAM_BOT_TOKEN=your_token_here python bot.py
```

## 依赖

- Python 3.8+
- [Claude Code CLI](https://claude.ai/code)
- python-telegram-bot >= 20.0
