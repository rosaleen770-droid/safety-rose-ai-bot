import os
import base64
import sqlite3
import tempfile
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

client = OpenAI(api_key=OPENAI_API_KEY)

TZ = ZoneInfo("Asia/Tashkent")

# Railway Volume bo'lsa /data ichida saqlaydi.
# Bo'lmasa vaqtincha current folder ishlaydi.
if os.path.isdir("/data"):
    DB_PATH = "/data/safety_bot.db"
else:
    DB_PATH = "safety_bot.db"


SYSTEM_PROMPT = """
You are Rosaleen Safety AI, a professional assistant for a US trucking
Safety and Compliance department.

Your main areas:

DRIVER SAFETY
- CDL review and expiration dates
- Medical cards
- MVR review
- Driver Qualification Files
- Driver onboarding
- Drug & Alcohol testing
- Clearinghouse
- SAP / Return-to-Duty process

DOT / FMCSA
- FMCSA regulations
- DOT inspections
- violations
- out-of-service issues
- DataQs
- safety scores
- New Entrant audits
- HOS / ELD

INSURANCE
- COI
- RMIS
- driver approval
- Great West
- Progressive
- GEICO
- claims
- loss runs

OPERATIONS / COMPLIANCE
- IFTA
- IRP
- permits
- 2290
- PrePass
- Amazon Relay compliance
- safety audits

DOCUMENT REVIEW
When a CDL, MVR, inspection, citation, insurance document or other
trucking document is uploaded:
1. Identify the document.
2. Extract important dates.
3. Identify expiration dates.
4. Identify violations or restrictions.
5. Explain what Safety should do next.
6. Clearly flag urgent issues.

Never invent information.
If a document is unclear or unreadable, say that.
Do not claim a driver is legally eligible unless the available
information supports it.
Keep answers practical, concise and Safety-department focused.
"""


# =========================================================
# DATABASE
# =========================================================

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            user_id INTEGER,
            task TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL,
            completed_at TEXT
        )
    """)

    conn.commit()
    conn.close()


def add_task(chat_id, user_id, task):
    conn = db()

    cur = conn.execute("""
        INSERT INTO tasks
        (chat_id, user_id, task, status, created_at)
        VALUES (?, ?, ?, 'pending', ?)
    """, (
        chat_id,
        user_id,
        task,
        datetime.now(TZ).isoformat()
    ))

    conn.commit()
    task_id = cur.lastrowid
    conn.close()

    return task_id


def get_tasks(chat_id):
    conn = db()

    rows = conn.execute("""
        SELECT id, task, created_at
        FROM tasks
        WHERE chat_id = ?
        AND status = 'pending'
        ORDER BY id
    """, (chat_id,)).fetchall()

    conn.close()
    return rows


def complete_task(chat_id, task_id):
    conn = db()

    cur = conn.execute("""
        UPDATE tasks
        SET status = 'done',
            completed_at = ?
        WHERE chat_id = ?
        AND id = ?
        AND status = 'pending'
    """, (
        datetime.now(TZ).isoformat(),
        chat_id,
        task_id
    ))

    conn.commit()
    changed = cur.rowcount
    conn.close()

    return changed > 0


def delete_task(chat_id, task_id):
    conn = db()

    cur = conn.execute("""
        DELETE FROM tasks
        WHERE chat_id = ?
        AND id = ?
    """, (chat_id, task_id))

    conn.commit()
    changed = cur.rowcount
    conn.close()

    return changed > 0


# =========================================================
# TELEGRAM COMMANDS
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = """
🌹 Rosaleen Safety AI is online.

I can help with:

📸 CDL / MVR / inspection photos
📄 Safety documents
🚛 FMCSA / DOT questions
🧪 Clearinghouse / SAP
🛡 Insurance / RMIS / COI
📦 Amazon Relay
✅ Daily Safety tasks

TASK EXAMPLES:

add task: Great West approval for John

tasks

done 3

delete 3

today

You can also simply send me a Safety question.
"""

    await update.message.reply_text(text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = """
🌹 ROSALEEN SAFETY AI COMMANDS

/add TASK
Add a Safety task.

/tasks
Show pending tasks.

/done ID
Complete a task.

/delete ID
Delete a task.

/today
Show today's Safety list.

You can also write naturally:

add task: check John CDL

tasks

done 2

Or upload a CDL, MVR, inspection or other document.
"""

    await update.message.reply_text(text)


# =========================================================
# TASK COMMANDS
# =========================================================

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    task = " ".join(context.args).strip()

    if not task:
        await update.message.reply_text(
            "Write:\n/add Check Great West approval"
        )
        return

    task_id = add_task(
        update.effective_chat.id,
        update.effective_user.id,
        task
    )

    await update.message.reply_text(
        f"✅ Task #{task_id} added:\n{task}"
    )


async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    rows = get_tasks(update.effective_chat.id)

    if not rows:
        await update.message.reply_text(
            "✅ No pending Safety tasks."
        )
        return

    message = "📋 PENDING SAFETY TASKS\n\n"

    for row in rows:
        message += f"#{row['id']} ⏳ {row['task']}\n"

    await update.message.reply_text(message)


async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:
        await update.message.reply_text(
            "Example:\n/done 3"
        )
        return

    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "Please send the task number."
        )
        return

    if complete_task(update.effective_chat.id, task_id):

        await update.message.reply_text(
            f"✅ Task #{task_id} completed."
        )

    else:

        await update.message.reply_text(
            f"⚠️ I couldn't find pending task #{task_id}."
        )


async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:
        await update.message.reply_text(
            "Example:\n/delete 3"
        )
        return

    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "Please send the task number."
        )
        return

    if delete_task(update.effective_chat.id, task_id):

        await update.message.reply_text(
            f"🗑 Task #{task_id} deleted."
        )

    else:

        await update.message.reply_text(
            f"⚠️ Task #{task_id} not found."
        )


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    rows = get_tasks(update.effective_chat.id)

    date = datetime.now(TZ).strftime("%B %d, %Y")

    message = f"🌹 SAFETY DAILY — {date}\n\n"

    if not rows:

        message += "✅ No pending tasks."

    else:

        for row in rows:
            message += f"☐ #{row['id']} {row['task']}\n"

    await update.message.reply_text(message)


# =========================================================
# AI TEXT
# =========================================================

async def ask_ai(text):

    response = client.responses.create(
        model="gpt-4.1-mini",
        instructions=SYSTEM_PROMPT,
        input=text,
    )

    return response.output_text


async def text_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text.strip()

    lower = text.lower()

    # Natural task adding
    prefixes = [
        "add task:",
        "add task ",
        "task:",
        "task "
    ]

    for prefix in prefixes:

        if lower.startswith(prefix):

            task = text[len(prefix):].strip()

            if task:

                task_id = add_task(
                    update.effective_chat.id,
                    update.effective_user.id,
                    task
                )

                await update.message.reply_text(
                    f"✅ Task #{task_id} added:\n{task}"
                )

            return

    # Natural tasks command
    if lower in [
        "tasks",
        "task list",
        "show tasks",
        "pending tasks"
    ]:

        await tasks_command(update, context)
        return

    # Natural today
    if lower in [
        "today",
        "today tasks",
        "daily",
        "daily tasks"
    ]:

        await today_command(update, context)
        return

    # Natural done command
    if lower.startswith("done "):

        try:
            task_id = int(lower.split()[1])

            if complete_task(
                update.effective_chat.id,
                task_id
            ):

                await update.message.reply_text(
                    f"✅ Task #{task_id} completed."
                )

            else:

                await update.message.reply_text(
                    f"⚠️ Task #{task_id} not found."
                )

        except:
            await update.message.reply_text(
                "Example: done 3"
            )

        return

    # Natural delete
    if lower.startswith("delete "):

        try:
            task_id = int(lower.split()[1])

            if delete_task(
                update.effective_chat.id,
                task_id
            ):

                await update.message.reply_text(
                    f"🗑 Task #{task_id} deleted."
                )

            else:

                await update.message.reply_text(
                    f"⚠️ Task #{task_id} not found."
                )

        except:
            await update.message.reply_text(
                "Example: delete 3"
            )

        return

    # AI Safety question
    try:

        await update.message.chat.send_action("typing")

        answer = await ask_ai(text)

        await update.message.reply_text(answer)

    except Exception as e:

        print("TEXT AI ERROR:", repr(e))

        await update.message.reply_text(
            "⚠️ AI couldn't answer this request. Please try again."
        )


# =========================================================
# PHOTO ANALYSIS
# =========================================================

async def photo_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    try:

        await update.message.chat.send_action("typing")

        photo = update.message.photo[-1]

        tg_file = await photo.get_file()

        data = BytesIO()

        await tg_file.download_to_memory(out=data)

        image_b64 = base64.b64encode(
            data.getvalue()
        ).decode("utf-8")

        question = (
            update.message.caption
            or
            """
Analyze this trucking Safety document.

If CDL:
- State
- Class
- Name
- CDL expiration
- Restrictions
- Endorsements
- validity concerns

If inspection/MVR:
- violations
- dates
- severity
- Safety action needed

Be concise.
"""
        )

        response = client.responses.create(
            model="gpt-4.1-mini",
            instructions=SYSTEM_PROMPT,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": question
                        },
                        {
                            "type": "input_image",
                            "image_url":
                            f"data:image/jpeg;base64,{image_b64}"
                        }
                    ]
                }
            ]
        )

        await update.message.reply_text(
            response.output_text
        )

    except Exception as e:

        print("PHOTO ERROR:", repr(e))

        await update.message.reply_text(
            "⚠️ I couldn't analyze this image."
        )


# =========================================================
# FILE / PDF ANALYSIS
# =========================================================

async def document_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    try:

        await update.message.chat.send_action("typing")

        document = update.message.document

        file_name = document.file_name or "document"

        tg_file = await document.get_file()

        suffix = os.path.splitext(file_name)[1]

        with tempfile.NamedTemporaryFile(
            suffix=suffix,
            delete=False
        ) as temp:

            temp_path = temp.name

        await tg_file.download_to_drive(temp_path)

        question = (
            update.message.caption
            or
            """
Analyze this trucking Safety document.

Identify:
- document type
- driver/company
- important dates
- expiration dates
- violations
- insurance/compliance issues
- what Safety should do next
"""
        )

        # Upload document to OpenAI
        with open(temp_path, "rb") as f:

            uploaded = client.files.create(
                file=f,
                purpose="user_data"
            )

        response = client.responses.create(
            model="gpt-4.1-mini",
            instructions=SYSTEM_PROMPT,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": question
                        },
                        {
                            "type": "input_file",
                            "file_id": uploaded.id
                        }
                    ]
                }
            ]
        )

        await update.message.reply_text(
            response.output_text
        )

        try:
            client.files.delete(uploaded.id)
        except:
            pass

        try:
            os.remove(temp_path)
        except:
            pass

    except Exception as e:

        print("DOCUMENT ERROR:", repr(e))

        await update.message.reply_text(
            "⚠️ I couldn't analyze this document."
        )


# =========================================================
# MAIN
# =========================================================

def main():

    init_db()

    app = (
        Application
        .builder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("help", help_command)
    )

    app.add_handler(
        CommandHandler("add", add_command)
    )

    app.add_handler(
        CommandHandler("tasks", tasks_command)
    )

    app.add_handler(
        CommandHandler("done", done_command)
    )

    app.add_handler(
        CommandHandler("delete", delete_command)
    )

    app.add_handler(
        CommandHandler("today", today_command)
    )

    app.add_handler(
        MessageHandler(
            filters.PHOTO,
            photo_message
        )
    )

    app.add_handler(
        MessageHandler(
            filters.Document.ALL,
            document_message
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_message
        )
    )

    print("🌹 Rosaleen Safety AI V2 is running...")

    app.run_polling()


if __name__ == "__main__":
    main()
