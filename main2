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

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"].strip()
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"].strip()

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

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
            PRIMARY KEY (chat_id, message_type, sent_date)
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
You are Rosaleen Safety AI, a professional assistant for a US trucking
Safety and Compliance department.

Your role is to assist Safety Managers, dispatchers, owners and compliance
staff with practical trucking safety and compliance work.

CORE AREAS:

DRIVER QUALIFICATION
- CDL validity and expiration
- Medical Certificate / Med Card validity and expiration
- Self-certification
- CDL restrictions and endorsements
- MVR review
- PSP review
- Driver Qualification Files
- Previous employer verification
- Clearinghouse queries
- SAP / Return-to-Duty
- Pre-employment drug tests
- Random testing
- Driver onboarding and termination

FMCSA / DOT COMPLIANCE
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
- Drug & Alcohol regulations
- driver qualification requirements
- vehicle maintenance compliance
- accident register requirements

SAFETY SCORES
- CSA / SMS concepts
- BASIC categories
- Unsafe Driving
- HOS Compliance
- Vehicle Maintenance
- Driver Fitness
- Controlled Substances / Alcohol
- Crash Indicator
- inspection severity and safety impact
- explain what may affect a carrier safety profile
- never invent exact FMCSA points if official information is not available

AMAZON RELAY
- carrier verification
- compliance warnings
- insurance / COI
- RMIS
- asset verification
- driver verification
- safety score related issues
- account suspension
- reinstatement support
- document requests
- trip compliance
- lease / rental documentation
- general appeal drafting support

INSURANCE
- COI
- RMIS
- Great West
- Progressive
- GEICO
- driver approval
- truck approval
- loss runs
- claims
- accident documentation
- renewal documents
- cancellation notices
- deductible questions
- underwriting requests

PERMITS / TAX / OPERATIONS
- IFTA
- IRP
- Form 2290
- UCR
- state permits
- NY HUT
- Oregon permits
- New Mexico permits
- Kentucky permits
- PrePass
- apportioned registration basics


DOCUMENT ANALYSIS:

When reviewing a CDL:
- driver name
- state
- class
- CDL number if clearly readable
- issue date
- expiration date
- endorsements
- restrictions
- whether the document appears expired
- what Safety should verify next

When reviewing a Medical Card:
- driver name
- medical examiner
- issue date
- expiration date
- whether it appears expired
- restrictions if visible
- what Safety should verify next

When reviewing an MVR:
- license status
- violations
- convictions
- suspensions
- accidents
- important dates
- points only when supported by the state or document
- hiring or Safety concerns
- what should be verified next

When reviewing an inspection:
- inspection date
- state
- driver
- truck or unit
- violations
- OOS status
- driver vs vehicle violation
- likely Safety concern
- recommended corrective action

When reviewing insurance or FMCSA documents:
- document type
- company
- policy or filing dates
- expiration
- missing information
- compliance issues
- recommended next action

When reviewing Amazon Relay documents:
- identify the issue
- identify requested documents
- explain likely compliance concern
- recommend exact next steps
- help draft concise appeals when asked


DAILY SAFETY WORK:
- create practical checklists
- prioritize urgent expirations
- summarize pending Safety work
- identify missing documents
- suggest next actions
- keep answers concise and operational


RESPONSE BEHAVIOR:

Do not unnecessarily refuse normal trucking Safety and Compliance questions.

If information is incomplete:
- analyze everything available
- identify confirmed facts
- identify what is still unknown
- explain what must be checked
- give the exact next practical step

If an image is partly unreadable:
analyze the readable information instead of refusing the entire request.

If asked:
"Can we hire him?"
"Can he drive?"
"Is this CDL valid?"
"How many points?"
"Can we add this driver?"
"Is this violation serious?"
or similar questions:

1. Explain what the available information shows.
2. Identify Safety red flags.
3. Explain anything that still requires verification.
4. Give a practical Safety recommendation.

Never invent facts, dates, violations, points, legal status,
insurance approval, Clearinghouse status or FMCSA information.

For live information such as:
- current FMCSA status
- current CSA/SMS information
- Clearinghouse status
- Amazon Relay account status
- current insurance approval

state when live verification is required.

Do not guarantee that a driver is legally eligible to operate solely
from one document.

For compliance-critical decisions, recommend verifying through the
appropriate official source when necessary.

Do not assist with falsifying records, hiding violations,
fraudulent documents or intentionally avoiding lawful compliance.

Respond like an experienced US trucking Safety Manager.

Keep answers:
- clear
- practical
- concise
- confident
- operational
- easy for Safety staff to understand

When useful, end with:
Safety recommendation: ...
"""


# =========================================================
# CHAT REGISTRATION
# =========================================================

def register_chat(update: Update):
    if not update.effective_chat:
        return

    chat = update.effective_chat

    name = (
        chat.title
        or chat.full_name
        or chat.username
        or str(chat.id)
    )

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO chats (chat_id, chat_name, last_seen)
        VALUES (?, ?, ?)
        ON CONFLICT(chat_id)
        DO UPDATE SET
            chat_name = excluded.chat_name,
            last_seen = excluded.last_seen
        """,
        (
            chat.id,
            name,
            datetime.now(TZ).isoformat(),
        ),
    )

    conn.commit()
    conn.close()


# =========================================================
# TASK FUNCTIONS
# =========================================================

def add_task_db(chat_id, user_id, user_name, task):
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


def complete_task_db(chat_id, task_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE tasks
        SET status = 'done',
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
# OPENAI TEXT
# =========================================================

def ask_openai_text(user_text):
    response = client.responses.create(
        model=OPENAI_MODEL,
        instructions=SYSTEM_PROMPT,
        input=user_text,
    )

    return response.output_text


# =========================================================
# OPENAI IMAGE
# =========================================================

def ask_openai_image(image_bytes, user_text):
    encoded = base64.b64encode(image_bytes).decode("utf-8")

    prompt = user_text.strip() if user_text else (
        "Analyze this document/image as a trucking Safety Manager. "
        "Tell me what it is, important dates, violations or compliance "
        "issues, and what Safety should do next."
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
                        "image_url": f"data:image/jpeg;base64,{encoded}",
                    },
                ],
            }
        ],
    )

    return response.output_text


# =========================================================
# TELEGRAM COMMANDS
# =========================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    register_chat(update)

    text = (
        "🛡 Rosaleen Safety AI is online.\n\n"
        "Send me a Safety question, CDL, MVR, inspection, "
        "Medical Card, insurance document or screenshot.\n\n"
        "Tasks:\n"
        "/task Driver MVR needed\n"
        "/tasks\n"
        "/done 1\n\n"
        "Daily Safety Reminder: 5:00 PM\n"
        "Daily Conclusion: 2:00 AM\n"
        "Timezone: Asia/Tashkent"
    )

    await update.message.reply_text(text)


async def task_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    register_chat(update)

    if not context.args:
        await update.message.reply_text(
            "Send task like:\n/task Check driver MVR"
        )
        return

    task_text = " ".join(context.args).strip()

    user = update.effective_user

    task_id = add_task_db(
        update.effective_chat.id,
        user.id if user else None,
        user.full_name if user else "Unknown",
        task_text,
    )

    await update.message.reply_text(
        f"✅ Task #{task_id} added:\n{task_text}"
    )


async def tasks_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    register_chat(update)

    rows = get_pending_tasks(update.effective_chat.id)

    if not rows:
        await update.message.reply_text(
            "✅ No pending Safety tasks."
        )
        return

    lines = ["📋 PENDING SAFETY TASKS\n"]

    for row in rows:
        lines.append(
            f"#{row['id']} — {row['task']}"
        )

    await update.message.reply_text(
        "\n".join(lines)
    )


async def done_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    register_chat(update)

    if not context.args:
        await update.message.reply_text(
            "Example:\n/done 3"
        )
        return

    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "Task number must be a number."
        )
        return

    completed = complete_task_db(
        update.effective_chat.id,
        task_id,
    )

    if completed:
        await update.message.reply_text(
            f"✅ Task #{task_id} completed."
        )
    else:
        await update.message.reply_text(
            f"Task #{task_id} not found or already completed."
        )


# =========================================================
# NATURAL TASK DETECTION
# =========================================================

def detect_add_task(text):
    if not text:
        return None

    lower = text.lower().strip()

    prefixes = [
        "add task ",
        "add a task ",
        "task: ",
        "new task ",
        "задача ",
        "задача: ",
    ]

    for prefix in prefixes:
        if lower.startswith(prefix):
            return text[len(prefix):].strip()

    return None


# =========================================================
# TEXT MESSAGE HANDLER
# =========================================================

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message:
        return

    if not update.message.text:
        return

    register_chat(update)

    text = update.message.text.strip()

    detected_task = detect_add_task(text)

    if detected_task:
        user = update.effective_user

        task_id = add_task_db(
            update.effective_chat.id,
            user.id if user else None,
            user.full_name if user else "Unknown",
            detected_task,
        )

        await update.message.reply_text(
            f"✅ Task #{task_id} added:\n{detected_task}"
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
                "I couldn't generate a response. "
                "Please send the question again."
            )

        await send_long_message(
            update,
            answer,
        )

    except Exception as e:
        logger.exception("Text handler error")

        await update.message.reply_text(
            "⚠️ Rosaleen Safety AI had a temporary error.\n"
            f"{type(e).__name__}: {str(e)[:300]}"
        )


# =========================================================
# PHOTO HANDLER
# =========================================================

async def photo_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message:
        return

    register_chat(update)

    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action="typing",
        )

        photo = update.message.photo[-1]

        tg_file = await photo.get_file()

        buffer = BytesIO()

        await tg_file.download_to_memory(
            out=buffer
        )

        image_bytes = buffer.getvalue()

        caption = update.message.caption or ""

        answer = await asyncio.to_thread(
            ask_openai_image,
            image_bytes,
            caption,
        )

        await send_long_message(
            update,
            answer,
        )

    except Exception as e:
        logger.exception("Photo handler error")

        await update.message.reply_text(
            "⚠️ I couldn't analyze this image.\n"
            f"{type(e).__name__}: {str(e)[:300]}"
        )


# =========================================================
# DOCUMENT HANDLER
# =========================================================

async def document_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message or not update.message.document:
        return

    register_chat(update)

    document = update.message.document

    mime = document.mime_type or ""
    filename = document.file_name or "document"

    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action="typing",
        )

        tg_file = await document.get_file()

        buffer = BytesIO()

        await tg_file.download_to_memory(
            out=buffer
        )

        data = buffer.getvalue()

        caption = update.message.caption or ""

        # Images sent as files
        if mime.startswith("image/"):
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

        # Text files
        if mime.startswith("text/") or filename.lower().endswith(
            (".txt", ".csv")
        ):
            text_data = data.decode(
                "utf-8",
                errors="ignore",
            )

            prompt = (
                f"Analyze this trucking Safety document.\n\n"
                f"Filename: {filename}\n\n"
                f"{caption}\n\n"
                f"DOCUMENT:\n{text_data[:50000]}"
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

        # PDF / other file
        await update.message.reply_text(
            "📄 File received: "
            f"{filename}\n\n"
            "For the most reliable analysis right now, "
            "send screenshots of the important PDF pages "
            "or send the document pages as images."
        )

    except Exception as e:
        logger.exception("Document handler error")

        await update.message.reply_text(
            "⚠️ I couldn't process this document.\n"
            f"{type(e).__name__}: {str(e)[:300]}"
        )


# =========================================================
# LONG TELEGRAM MESSAGES
# =========================================================

async def send_long_message(update, text):
    if not text:
        return

    max_length = 3900

    while len(text) > max_length:
        split_at = text.rfind(
            "\n",
            0,
            max_length,
        )

        if split_at == -1:
            split_at = max_length

        part = text[:split_at]

        await update.message.reply_text(part)

        text = text[split_at:].lstrip()

    if text:
        await update.message.reply_text(text)


# =========================================================
# DAILY REMINDER / CONCLUSION
# =========================================================

def daily_message_already_sent(
    chat_id,
    message_type,
    sent_date,
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
            sent_date,
        ),
    )

    exists = cur.fetchone() is not None

    conn.close()

    return exists


def mark_daily_message_sent(
    chat_id,
    message_type,
    sent_date,
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
            sent_date,
        ),
    )

    conn.commit()
    conn.close()


def get_all_chats():
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT chat_id, chat_name
        FROM chats
        """
    )

    rows = cur.fetchall()

    conn.close()

    return rows


async def send_reminder(application, chat_id):
    tasks = get_pending_tasks(chat_id)

    if tasks:
        lines = [
            "⏰ DAILY SAFETY REMINDER",
            "",
            f"Pending tasks: {len(tasks)}",
            "",
        ]

        for row in tasks[:20]:
            lines.append(
                f"▫️ #{row['id']} — {row['task']}"
            )

        lines.extend(
            [
                "",
                "Please review today's Safety priorities.",
            ]
        )

        text = "\n".join(lines)

    else:
        text = (
            "⏰ DAILY SAFETY REMINDER\n\n"
            "✅ No pending Safety tasks in the system.\n"
            "Please review driver, insurance, permit and "
            "compliance expirations for today."
        )

    await application.bot.send_message(
        chat_id=chat_id,
        text=text,
    )


async def send_conclusion(application, chat_id):
    tasks = get_pending_tasks(chat_id)

    if tasks:
        lines = [
            "🌙 DAILY SAFETY CONCLUSION",
            "",
            f"Pending tasks remaining: {len(tasks)}",
            "",
        ]

        for row in tasks[:20]:
            lines.append(
                f"▫️ #{row['id']} — {row['task']}"
            )

        lines.extend(
            [
                "",
                "Review unresolved items for the next shift.",
            ]
        )

        text = "\n".join(lines)

    else:
        text = (
            "🌙 DAILY SAFETY CONCLUSION\n\n"
            "✅ No pending tasks remaining.\n"
            "Safety task list is clear."
        )

    await application.bot.send_message(
        chat_id=chat_id,
        text=text,
    )


async def daily_scheduler(application):
    logger.info("Daily scheduler started")

    while True:
        try:
            now = datetime.now(TZ)

            current_date = now.date().isoformat()

            chats = get_all_chats()

            # 5:00 PM Tashkent Reminder
            if now.hour == 17 and now.minute < 5:
                for chat in chats:
                    chat_id = chat["chat_id"]

                    if not daily_message_already_sent(
                        chat_id,
                        "reminder",
                        current_date,
                    ):
                        try:
                            await send_reminder(
                                application,
                                chat_id,
                            )

                            mark_daily_message_sent(
                                chat_id,
                                "reminder",
                                current_date,
                            )

                        except Exception:
                            logger.exception(
                                "Reminder failed for %s",
                                chat_id,
                            )

            # 2:00 AM Tashkent Conclusion
            if now.hour == 2 and now.minute < 5:
                for chat in chats:
                    chat_id = chat["chat_id"]

                    if not daily_message_already_sent(
                        chat_id,
                        "conclusion",
                        current_date,
                    ):
                        try:
                            await send_conclusion(
                                application,
                                chat_id,
                            )

                            mark_daily_message_sent(
                                chat_id,
                                "conclusion",
                                current_date,
                            )

                        except Exception:
                            logger.exception(
                                "Conclusion failed for %s",
                                chat_id,
                            )

        except Exception:
            logger.exception(
                "Daily scheduler error"
            )

        await asyncio.sleep(60)


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    logger.exception(
        "Telegram update caused error",
        exc_info=context.error,
    )


# =========================================================
# STARTUP
# =========================================================

async def post_init(application):
    asyncio.create_task(
        daily_scheduler(application)
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
            filters.TEXT & ~filters.COMMAND,
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
