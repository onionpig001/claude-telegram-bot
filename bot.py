#!/usr/bin/env python3
"""
Claude Code Telegram Bot
Telegram 消息 → claude -p → 回复（带上下文记忆）
"""

import os
import sqlite3
import asyncio
import logging
from pathlib import Path
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters
from telegram.constants import ChatAction

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('/root/claude-telegram-bot/bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
ALLOWED_USER_IDS = [int(x) for x in os.environ.get('ALLOWED_USER_IDS', '5230755090').split(',') if x]
CLAUDE_BIN = os.environ.get('CLAUDE_BIN', 'claude')

DB_PATH = Path('/root/claude-telegram-bot/bot.db')
MAX_HISTORY_MESSAGES = 40  # 最多保留20轮对话（40条消息）


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON chat_history(user_id, created_at)")


def is_allowed(user_id: int) -> bool:
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS


def load_history(user_id: int) -> list:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """SELECT role, content FROM chat_history
               WHERE user_id = ? ORDER BY created_at DESC LIMIT ?""",
            (user_id, MAX_HISTORY_MESSAGES)
        ).fetchall()
    return [{"role": r, "content": c} for r, c in reversed(rows)]


def append_history(user_id: int, role: str, content: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content)
        )


def build_prompt(user_id: int, new_message: str) -> str:
    """把历史上下文拼入 prompt"""
    history = load_history(user_id)
    if not history:
        return new_message

    lines = [
        "以下是我们之前的对话记录，请基于此上下文继续回答：",
        "---"
    ]
    for msg in history:
        prefix = "用户" if msg['role'] == 'user' else "Claude"
        lines.append(f"{prefix}: {msg['content']}")
    lines.append("---")
    lines.append(f"用户: {new_message}")
    lines.append("（请继续对话，只需回复最后这条消息）")
    return "\n".join(lines)


async def run_claude(user_id: int, message: str) -> str:
    """调用 claude -p 并返回结果（带上下文）"""
    prompt = build_prompt(user_id, message)
    try:
        result = await asyncio.create_subprocess_exec(
            CLAUDE_BIN, '-p', prompt, '--output-format', 'text',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(result.communicate(), timeout=120)
        output = stdout.decode('utf-8').strip()
        if not output and stderr:
            output = f"⚠️ 错误: {stderr.decode('utf-8').strip()[:200]}"
        return output or '（无响应）'
    except asyncio.TimeoutError:
        return '⏱️ 超时了（超过2分钟），请换个简短的问题试试'
    except Exception as e:
        return f'❌ 调用失败: {e}'


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_allowed(user.id):
        await update.message.reply_text('❌ 无权限')
        return

    text = update.message.text or update.message.caption or ''
    if not text:
        return

    logger.info(f"[{user.id}] {user.first_name}: {text[:80]}")

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING
    )

    reply = await run_claude(user.id, text)

    # 记录本轮对话到历史
    append_history(user.id, 'user', text)
    append_history(user.id, 'assistant', reply)

    # Telegram 消息限制 4096 字符，分段发送
    max_len = 4000
    if len(reply) <= max_len:
        await update.message.reply_text(reply)
    else:
        for i in range(0, len(reply), max_len):
            await update.message.reply_text(reply[i:i+max_len])


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_allowed(user.id):
        await update.message.reply_text('❌ 无权限')
        return
    history = load_history(user.id)
    rounds = len(history) // 2
    await update.message.reply_text(
        f'👋 我是 Claude，直接发消息给我就行。\n'
        f'📝 当前已记录 {rounds} 轮对话上下文。\n\n'
        f'命令：\n'
        f'/clear — 清除对话记忆，重新开始\n'
        f'/history — 查看当前上下文摘要'
    )


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_allowed(user.id):
        await update.message.reply_text('❌ 无权限')
        return
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM chat_history WHERE user_id = ?", (user.id,))
    await update.message.reply_text('🗑️ 对话记忆已清除，重新开始。')
    logger.info(f"[{user.id}] {user.first_name}: cleared history")


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_allowed(user.id):
        await update.message.reply_text('❌ 无权限')
        return
    history = load_history(user.id)
    if not history:
        await update.message.reply_text('📭 当前没有对话记录。')
        return

    rounds = len(history) // 2
    lines = [f'📝 当前上下文：{rounds} 轮对话\n']
    for msg in history[-10:]:  # 只显示最近5轮
        prefix = '🧑' if msg['role'] == 'user' else '🤖'
        content = msg['content'][:100] + ('...' if len(msg['content']) > 100 else '')
        lines.append(f"{prefix} {content}")

    if len(history) > 10:
        lines.insert(1, f'（显示最近 5 轮，共 {rounds} 轮）\n')

    await update.message.reply_text('\n'.join(lines))


def main():
    if not BOT_TOKEN:
        raise ValueError('请设置环境变量 TELEGRAM_BOT_TOKEN')

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler('start', start_command))
    app.add_handler(CommandHandler('clear', clear_command))
    app.add_handler(CommandHandler('history', history_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    init_db()
    logger.info('Claude Telegram Bot 启动（带上下文记忆）...')
    app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
