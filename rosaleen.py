import os
import asyncio
import base64
import sqlite3
import logging
from io import BytesIO
from datetime import datetime
from zoneinfo import ZoneInfo

from openai import OpenAI
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# =========================================================
# SETTINGS
# =========================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing in Railway Variables")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is missing in Railway Variables")

OPENAI_MODEL = os.getenv(
    "OPENAI_MODEL",
    "gpt-5.6-luna"
).strip()

client = OpenAI(api_key=OPENAI_API_KEY)

TZ = ZoneInfo("Asia/Tashkent")


# =========================================================
# DATABASE
# =========================================================

if os.path.isdir("/data"):
    DB_PATH = "/data/safety_bot.db"
else:
    DB_PATH = "safety_bot.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            user_id INTEGER,
            user_name TEXT,
            task TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL,
            completed_at TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY,
            chat_name TEXT,
            last_seen TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_messages (
            chat_id INTEGER NOT NULL,
            message_type TEXT NOT NULL,
            sent_date TEXT NOT NULL,
            PRIMARY KEY (
                chat_id,
                message_type,
                sent_date
            )
        )
        """
    )

    conn.commit()
    conn.close()


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("RosaleenSafetyAI")


# =========================================================
# SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = """
You are Rosaleen Safety AI, an experienced US trucking
Safety and Compliance department assistant.

Your job is to help trucking Safety staff make fast,
practical and compliant decisions.

LANGUAGE:
- Reply in the same language the user uses.
- Understand English, Russian and Uzbek.
- Keep standard trucking terminology in English when useful.

RESPONSE LENGTH:
VERY IMPORTANT:
- Keep answers SHORT.
- Usually answer in 1 to 4 sentences.
- Give the direct answer first.
- Do not write long explanations unless the user specifically asks.
- Do not repeat the user's question.
- Avoid unnecessary introductions.
- Avoid large lists.
- For a simple question, give a simple answer.

STYLE:
- Sound like an experienced human Safety Manager.
- Be clear, practical, professional and confident.
- Explain only what matters.
- Give the next Safety action when useful.

CORE AREAS:

DRIVER QUALIFICATION
- CDL validity and expiration
- Medical Card validity and expiration
- self-certification
- restrictions and endorsements
- MVR
- PSP
- Driver Qualification Files
- previous employer verification
- Clearinghouse
- SAP / Return-to-Duty
- pre-employment drug testing
- random testing
- onboarding
- termination
- hiring eligibility

FMCSA / DOT
- FMCSA regulations
- DOT inspections
- roadside inspections
- violations
- Out-of-Service violations
- DataQs
- New Entrant Safety Audit
- compliance reviews
- HOS
- ELD
- Drug & Alcohol requirements
- accident register
- vehicle maintenance
- driver qualification requirements

CSA / SMS
- BASIC categories
- Unsafe Driving
- HOS Compliance
- Vehicle Maintenance
- Driver Fitness
- Controlled Substances / Alcohol
- Crash Indicator
- inspection violations
- corrective actions

AMAZON RELAY
- carrier verification
- account suspension
- reinstatement
- appeals
- compliance warnings
- RMIS
- COI
- insurance verification
- driver verification
- asset verification
- safety issues
- trip compliance
- lease/rental documents
- requested documents

INSURANCE
- Great West
- Progressive
- GEICO
- COI
- RMIS
- driver approval
- truck approval
- underwriting
- renewal
- cancellation
- claims
- loss runs
- deductibles

PERMITS / OPERATIONS
- IFTA
- IRP
- Form 2290
- UCR
- NY HUT
- Oregon permits
- New Mexico permits
- Kentucky permits
- PrePass
- apportioned registration

DOCUMENT ANALYSIS:

For a CDL check:
- name
- state
- class
- expiration
- endorsements
- restrictions
- visible problems
- next Safety action

For a Medical Card check:
- name
- examiner
- expiration
- restrictions
- visible validity
- next Safety action

For an MVR check:
- license status
- violations
- convictions
- suspensions
- accidents
- dates
- hiring concerns
- points only if supported by the document/state information

For an inspection check:
- date
- state
- driver
- unit
- violations
- OOS
- driver vs vehicle violation
- Safety impact
- corrective action

For insurance:
- carrier
- insured company
- policy dates
- expiration
- coverage
- missing information
- next action

For Amazon:
- identify the problem
- identify what Amazon requests
- explain missing documents
- give the next practical action

IMPORTANT:

If an image is partly unreadable,
analyze everything that is readable.
Do not reject the whole image.

When asked:
"Can we hire him?"
"Can he drive?"
"Can we dispatch him?"
"Is this valid?"
"How many points?"
"Is this violation serious?"

Answer directly based on the available information.

When appropriate use:
"Based on what I can see: YES."
"Based on what I can see: NO."
or
"Needs verification."

Then explain the most important reason briefly.

Never invent:
- violations
- points
- dates
- CDL status
- Medical Card status
- Clearinghouse results
- SAP completion
- insurance approval
- Amazon status
- FMCSA status
- safety scores
- accident facts

If live verification is required,
briefly say exactly what Safety must verify.

Do not unnecessarily refuse ordinary trucking Safety questions.
If some information is missing, analyze what is available
and tell the user what to check next.

Do not help falsify documents, hide violations,
fabricate accidents or evade lawful compliance requirements.

FINAL RULE:
Answer first.
Keep it short.
Explain only what matters.
"""


# =========================================================
# CHAT DATABASE
# =========================================================

def register_chat(update: Update):
    if not update.effective_chat:
        return

    chat = update.effective_chat

    chat_name = (
        chat.title
        or chat.username
        or str(chat.id)
    )

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO chats (
            chat_id,
            chat_name,
            last_seen
        )
        VALUES (?, ?, ?)
        ON CONFLICT(chat_id)
        DO UPDATE SET
            chat_name = excluded.chat_name,
            last_seen = excluded.last_seen
        """,
        (
            chat.id,
            chat_name,
            datetime.now(TZ).isoformat(),
        ),
    )

    conn.commit()
    conn.close()


# =========================================================
# GROUP RESPONSE CONTROL
# =========================================================

async def should_respond(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str = "",
):
    """
    PRIVATE CHAT:
    Always respond.

    GROUP:
    Respond ONLY when:
    1. Bot is @mentioned
    2. User replies directly to bot
    """

    chat = update.effective_chat

    if not chat:
        return False

    if chat.type == "private":
        return True

    if chat.type not in (
        "group",
        "supergroup",
    ):
        return False

    # -----------------------------------------------------
    # Check @mention
    # -----------------------------------------------------

    bot_username = context.bot.username

    if bot_username:
        mention = f"@{bot_username}"

        if mention.lower() in (text or "").lower():
            return True

    # -----------------------------------------------------
    # Check reply to bot
    # -----------------------------------------------------

    message = update.effective_message

    if (
        message
        and message.reply_to_message
        and message.reply_to_message.from_user
    ):
        bot_user = await context.bot.get_me()

        if (
            message.reply_to_message.from_user.id
            == bot_user.id
        ):
            return True

    return False


def remove_bot_mention(
    text: str,
    bot_username: str,
):
    if not text:
        return ""

    if not bot_username:
        return text.strip()

    mention = f"@{bot_username}"

    lower_text = text.lower()
    lower_mention = mention.lower()

    while lower_mention in lower_text:
        position = lower_text.find(lower_mention)

        text = (
            text[:position]
            + text[position + len(mention):]
        )

        lower_text = text.lower()

    return text.strip()


# =========================================================
# TASK DATABASE
# =========================================================

def add_task_db(
    chat_id,
    user_id,
    user_name,
    task,
):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO tasks (
            chat_id,
            user_id,
            user_name,
            task,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, 'pending', ?)
        """,
        (
            chat_id,
            user_id,
            user_name,
            task,
            datetime.now(TZ).isoformat(),
        ),
    )

    task_id = cur.lastrowid

    conn.commit()
    conn.close()

    return task_id


def get_pending_tasks(chat_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM tasks
        WHERE chat_id = ?
        AND status = 'pending'
        ORDER BY id ASC
        """,
        (chat_id,),
    )

    rows = cur.fetchall()

    conn.close()

    return rows


def complete_task_db(
    chat_id,
    task_id,
):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE tasks
        SET
            status = 'done',
            completed_at = ?
        WHERE chat_id = ?
        AND id = ?
        AND status = 'pending'
        """,
        (
            datetime.now(TZ).isoformat(),
            chat_id,
            task_id,
        ),
    )

    changed = cur.rowcount

    conn.commit()
    conn.close()

    return changed > 0


# =========================================================
# OPENAI
# =========================================================

def ask_openai_text(user_text):
    response = client.responses.create(
        model=OPENAI_MODEL,
        instructions=SYSTEM_PROMPT,
        input=user_text,
        max_output_tokens=350,
    )

    return response.output_text


def ask_openai_image(
    image_bytes,
    user_text="",
):
    encoded = base64.b64encode(
        image_bytes
    ).decode("utf-8")

    prompt = user_text.strip()

    if not prompt:
        prompt = (
            "Analyze this image as a trucking Safety Manager. "
            "Tell me briefly what it shows, any important issue, "
            "and what Safety should do next."
        )

    response = client.responses.create(
        model=OPENAI_MODEL,
        instructions=SYSTEM_PROMPT,
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": prompt,
                    },
                    {
                        "type": "input_image",
                        "image_url": (
                            "data:image/jpeg;base64,"
                            + encoded
                        ),
                    },
                ],
            }
        ],
        max_output_tokens=350,
    )

    return response.output_text


# =========================================================
# TELEGRAM MESSAGE SENDER
# =========================================================

async def send_long_message(
    update: Update,
    text: str,
):
    if not text:
        return

    max_length = 3900

    while len(text) > max_length:
        split_at = text.rfind(
            "\n",
            0,
            max_length,
        )

        if split_at <= 0:
            split_at = max_length

        part = text[:split_at]

        await update.effective_message.reply_text(
            part
        )

        text = text[split_at:].lstrip()

    if text:
        await update.effective_message.reply_text(
            text
        )


# =========================================================
# COMMANDS
# =========================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    register_chat(update)

    await update.effective_message.reply_text(
        "🛡 Rosaleen Safety AI is online.\n\n"
        "Send me a Safety question or document.\n\n"
        "/task Add a task\n"
        "/tasks View pending tasks\n"
        "/done 1 Complete a task"
    )


async def task_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    register_chat(update)

    if not context.args:
        await update.effective_message.reply_text(
            "Example:\n/task Check driver MVR"
        )
        return

    task_text = " ".join(
        context.args
    ).strip()

    user = update.effective_user

    task_id = add_task_db(
        update.effective_chat.id,
        user.id if user else None,
        user.full_name if user else "Unknown",
        task_text,
    )

    await update.effective_message.reply_text(
        f"✅ Task #{task_id} added:\n"
        f"{task_text}"
    )


async def tasks_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    register_chat(update)

    tasks = get_pending_tasks(
        update.effective_chat.id
    )

    if not tasks:
        await update.effective_message.reply_text(
            "✅ No pending Safety tasks."
        )
        return

    lines = [
        "📋 Pending Safety Tasks",
        "",
    ]

    for row in tasks[:20]:
        lines.append(
            f"#{row['id']} — {row['task']}"
        )

    await update.effective_message.reply_text(
        "\n".join(lines)
    )


async def done_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    register_chat(update)

    if not context.args:
        await update.effective_message.reply_text(
            "Example:\n/done 3"
        )
        return

    try:
        task_id = int(
            context.args[0]
        )
    except ValueError:
        await update.effective_message.reply_text(
            "Please send a task number."
        )
        return

    completed = complete_task_db(
        update.effective_chat.id,
        task_id,
    )

    if completed:
        await update.effective_message.reply_text(
            f"✅ Task #{task_id} completed."
        )
    else:
        await update.effective_message.reply_text(
            f"Task #{task_id} not found."
        )


# =========================================================
# TEXT HANDLER
# =========================================================

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message

    if not message or not message.text:
        return

    text = message.text.strip()

    respond = await should_respond(
        update,
        context,
        text,
    )

    # GROUP NORMAL MESSAGE -> SILENT
    if not respond:
        return

    register_chat(update)

    # Remove @SafetyRoseAIbot
    if context.bot.username:
        text = remove_bot_mention(
            text,
            context.bot.username,
        )

    if not text:
        await message.reply_text(
            "Yes 🛡️ What do you need?"
        )
        return

    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action="typing",
        )

        answer = await asyncio.to_thread(
            ask_openai_text,
            text,
        )

        if not answer:
            answer = (
                "I couldn't generate an answer. "
                "Please try again."
            )

        await send_long_message(
            update,
            answer,
        )

    except Exception as e:
        logger.exception(
            "Text handler error"
        )

        await message.reply_text(
            "⚠️ Temporary AI error. "
            "Please try again."
        )


# =========================================================
# PHOTO HANDLER
# =========================================================

async def photo_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message

    if not message or not message.photo:
        return

    caption = (
        message.caption or ""
    ).strip()

    respond = await should_respond(
        update,
        context,
        caption,
    )

    # In group ignore unmentioned photos
    if not respond:
        return

    register_chat(update)

    if context.bot.username:
        caption = remove_bot_mention(
            caption,
            context.bot.username,
        )

    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action="typing",
        )

        photo = message.photo[-1]

        tg_file = await photo.get_file()

        buffer = BytesIO()

        await tg_file.download_to_memory(
            out=buffer
        )

        image_bytes = buffer.getvalue()

        answer = await asyncio.to_thread(
            ask_openai_image,
            image_bytes,
            caption,
        )

        await send_long_message(
            update,
            answer,
        )

    except Exception:
        logger.exception(
            "Photo handler error"
        )

        await message.reply_text(
            "⚠️ I couldn't analyze this image. "
            "Please try again."
        )


# =========================================================
# IMAGE DOCUMENT HANDLER
# =========================================================

async def document_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message

    if not message or not message.document:
        return

    document = message.document
    caption = (
        message.caption or ""
    ).strip()

    respond = await should_respond(
        update,
        context,
        caption,
    )

    if not respond:
        return

    register_chat(update)

    if context.bot.username:
        caption = remove_bot_mention(
            caption,
            context.bot.username,
        )

    mime_type = (
        document.mime_type or ""
    )

    filename = (
        document.file_name
        or "document"
    )

    try:
        tg_file = await document.get_file()

        buffer = BytesIO()

        await tg_file.download_to_memory(
            out=buffer
        )

        data = buffer.getvalue()

        # IMAGE SENT AS FILE
        if mime_type.startswith("image/"):
            answer = await asyncio.to_thread(
                ask_openai_image,
                data,
                caption,
            )

            await send_long_message(
                update,
                answer,
            )

            return

        # TXT / CSV
        if (
            mime_type.startswith("text/")
            or filename.lower().endswith(
                (".txt", ".csv")
            )
        ):
            decoded = data.decode(
                "utf-8",
                errors="ignore",
            )

            prompt = (
                f"Analyze this trucking Safety document briefly.\n"
                f"Filename: {filename}\n\n"
                f"{caption}\n\n"
                f"{decoded[:40000]}"
            )

            answer = await asyncio.to_thread(
                ask_openai_text,
                prompt,
            )

            await send_long_message(
                update,
                answer,
            )

            return

        await message.reply_text(
            "📄 File received. For now, send the important "
            "PDF page as a screenshot and I can analyze it."
        )

    except Exception:
        logger.exception(
            "Document handler error"
        )

        await message.reply_text(
            "⚠️ I couldn't process this file. "
            "Please try again."
        )


# =========================================================
# DAILY REMINDERS
# =========================================================

def get_all_chats():
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT chat_id
        FROM chats
        """
    )

    rows = cur.fetchall()

    conn.close()

    return rows


def daily_already_sent(
    chat_id,
    message_type,
    date,
):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT 1
        FROM daily_messages
        WHERE chat_id = ?
        AND message_type = ?
        AND sent_date = ?
        """,
        (
            chat_id,
            message_type,
            date,
        ),
    )

    exists = (
        cur.fetchone() is not None
    )

    conn.close()

    return exists


def mark_daily_sent(
    chat_id,
    message_type,
    date,
):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT OR IGNORE INTO daily_messages (
            chat_id,
            message_type,
            sent_date
        )
        VALUES (?, ?, ?)
        """,
        (
            chat_id,
            message_type,
            date,
        ),
    )

    conn.commit()
    conn.close()


async def send_daily_reminder(
    application,
    chat_id,
):
    tasks = get_pending_tasks(
        chat_id
    )

    if tasks:
        lines = [
            "⏰ Safety Reminder",
            "",
        ]

        for row in tasks[:10]:
            lines.append(
                f"• #{row['id']} {row['task']}"
            )

        text = "\n".join(lines)

    else:
        text = (
            "⏰ Safety Reminder\n"
            "No pending tasks. Check today's driver, "
            "insurance, permit and compliance items."
        )

    await application.bot.send_message(
        chat_id=chat_id,
        text=text,
    )


async def send_daily_conclusion(
    application,
    chat_id,
):
    tasks = get_pending_tasks(
        chat_id
    )

    if tasks:
        text = (
            "🌙 Safety Conclusion\n"
            f"{len(tasks)} task(s) still pending. "
            "Review them for the next shift."
        )
    else:
        text = (
            "🌙 Safety Conclusion\n"
            "✅ No pending Safety tasks."
        )

    await application.bot.send_message(
        chat_id=chat_id,
        text=text,
    )


async def daily_scheduler(
    application,
):
    logger.info(
        "Daily scheduler started"
    )

    while True:
        try:
            now = datetime.now(TZ)

            today = (
                now.date().isoformat()
            )

            chats = get_all_chats()

            # 5:00 PM TASHKENT
            if (
                now.hour == 17
                and 0 <= now.minute <= 4
            ):
                for row in chats:
                    chat_id = row["chat_id"]

                    if not daily_already_sent(
                        chat_id,
                        "reminder",
                        today,
                    ):
                        try:
                            await send_daily_reminder(
                                application,
                                chat_id,
                            )

                            mark_daily_sent(
                                chat_id,
                                "reminder",
                                today,
                            )

                        except Exception:
                            logger.exception(
                                "Reminder failed"
                            )

            # 2:00 AM TASHKENT
            if (
                now.hour == 2
                and 0 <= now.minute <= 4
            ):
                for row in chats:
                    chat_id = row["chat_id"]

                    if not daily_already_sent(
                        chat_id,
                        "conclusion",
                        today,
                    ):
                        try:
                            await send_daily_conclusion(
                                application,
                                chat_id,
                            )

                            mark_daily_sent(
                                chat_id,
                                "conclusion",
                                today,
                            )

                        except Exception:
                            logger.exception(
                                "Conclusion failed"
                            )

        except Exception:
            logger.exception(
                "Scheduler error"
            )

        await asyncio.sleep(60)


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    logger.error(
        "Telegram error: %s",
        context.error,
    )


# =========================================================
# STARTUP
# =========================================================

async def post_init(
    application,
):
    asyncio.create_task(
        daily_scheduler(
            application
        )
    )

    logger.info(
        "Rosaleen Safety AI started successfully"
    )


def main():
    init_db()

    application = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "task",
            task_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "tasks",
            tasks_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "done",
            done_command,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            photo_handler,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Document.ALL,
            document_handler,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            text_handler,
        )
    )

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "Starting Telegram polling..."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()
