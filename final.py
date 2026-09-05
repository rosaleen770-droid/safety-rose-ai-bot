import os
import asyncio
import base64
import logging
from io import BytesIO

from openai import OpenAI
from telegram import Update
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# =========================================================
# CONFIG
# =========================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing in Railway Variables")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is missing in Railway Variables")

client = OpenAI(api_key=OPENAI_API_KEY)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("RosaleenSafetyAI")


# =========================================================
# AI INSTRUCTIONS
# =========================================================

SYSTEM_PROMPT = """
You are Rosaleen Safety AI, an experienced US trucking
Safety and Compliance assistant.

You help with:
- CDL and Medical Cards
- MVR and PSP
- Driver Qualification Files
- Clearinghouse
- SAP / Return-to-Duty
- Drug and Alcohol testing
- FMCSA and DOT compliance
- inspections and violations
- OOS violations
- DataQs
- HOS and ELD
- CSA / SMS
- Amazon Relay
- RMIS and COI
- Great West, Progressive and GEICO
- insurance approvals and renewals
- claims
- IFTA, IRP, 2290 and UCR
- state permits
- Safety audits
- driver onboarding and termination

RESPONSE RULES:

Keep answers SHORT and direct.

Normally answer in 1-3 sentences.
Do not give long explanations unless specifically requested.
Give the answer first.
Then give the most important next Safety action if necessary.

Respond in the same language as the user.
Understand English, Russian and Uzbek.

For documents and images:
Analyze all clearly visible information.
If part is unreadable, analyze the readable part instead of rejecting
the whole document.

Never invent:
- dates
- violations
- points
- CDL status
- Medical Card status
- Clearinghouse status
- SAP completion
- insurance approval
- FMCSA status
- Amazon status
- accident facts

If live verification is required, briefly state exactly what must
be verified.

For questions such as:
"Can we hire him?"
"Can he drive?"
"Is this valid?"
"How many points?"
"Is this violation serious?"

Give the direct answer based on the available evidence, then briefly
state anything Safety still needs to verify.

Do not unnecessarily refuse normal trucking Safety questions.
"""


# =========================================================
# OPENAI
# =========================================================

def ask_ai(text):
    response = client.responses.create(
        model=OPENAI_MODEL,
        instructions=SYSTEM_PROMPT,
        input=text,
        max_output_tokens=250,
    )

    return response.output_text.strip()


def analyze_image(image_bytes, question):
    encoded = base64.b64encode(image_bytes).decode("utf-8")

    if not question:
        question = (
            "Analyze this image as a trucking Safety Manager. "
            "Give me the important information and next Safety action. "
            "Keep the answer short."
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
                        "text": question,
                    },
                    {
                        "type": "input_image",
                        "image_url": f"data:image/jpeg;base64,{encoded}",
                    },
                ],
            }
        ],
        max_output_tokens=250,
    )

    return response.output_text.strip()


# =========================================================
# GROUP CONTROL
# =========================================================

async def group_message_is_for_bot(update, context, text=""):
    chat = update.effective_chat
    message = update.effective_message

    if not chat or not message:
        return False

    # PRIVATE CHAT:
    # Bot answers everything.
    if chat.type == ChatType.PRIVATE:
        return True

    # Only support groups/supergroups here.
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return False

    bot = await context.bot.get_me()
    username = bot.username or ""

    # -----------------------------------------
    # 1. Explicit @SafetyRoseAIbot mention
    # -----------------------------------------

    if username and text:
        mention = f"@{username}"

        if mention.casefold() in text.casefold():
            return True

    # -----------------------------------------
    # 2. Reply directly to a message from bot
    # -----------------------------------------

    replied = message.reply_to_message

    if (
        replied
        and replied.from_user
        and replied.from_user.id == bot.id
    ):
        return True

    # -----------------------------------------
    # Everything else in group = SILENT
    # -----------------------------------------

    return False


def clean_mention(text, username):
    if not text:
        return ""

    if not username:
        return text.strip()

    mention = f"@{username}"

    # Case-insensitive removal
    lower = text.casefold()
    target = mention.casefold()

    while target in lower:
        start = lower.find(target)

        text = text[:start] + text[start + len(mention):]
        lower = text.casefold()

    return text.strip()


# =========================================================
# START COMMAND
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "🛡 Rosaleen Safety AI is online."
    )


# =========================================================
# TEXT
# =========================================================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message

    if not message or not message.text:
        return

    original_text = message.text.strip()

    # CRITICAL:
    # Ignore normal group conversations.
    allowed = await group_message_is_for_bot(
        update,
        context,
        original_text,
    )

    if not allowed:
        logger.info("Ignored normal group message")
        return

    bot = await context.bot.get_me()

    text = clean_mention(
        original_text,
        bot.username or "",
    )

    if not text:
        await message.reply_text("Yes 🛡️")
        return

    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action="typing",
        )

        answer = await asyncio.to_thread(
            ask_ai,
            text,
        )

        if not answer:
            return

        await message.reply_text(answer)

    except Exception:
        logger.exception("AI text error")

        await message.reply_text(
            "⚠️ Temporary error. Try again."
        )


# =========================================================
# PHOTOS
# =========================================================

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message

    if not message or not message.photo:
        return

    caption = (message.caption or "").strip()

    # Same group rule for photos:
    # in group, tag bot in caption or reply to bot.
    allowed = await group_message_is_for_bot(
        update,
        context,
        caption,
    )

    if not allowed:
        logger.info("Ignored normal group photo")
        return

    bot = await context.bot.get_me()

    caption = clean_mention(
        caption,
        bot.username or "",
    )

    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action="typing",
        )

        photo = message.photo[-1]
        telegram_file = await photo.get_file()

        buffer = BytesIO()

        await telegram_file.download_to_memory(
            out=buffer
        )

        answer = await asyncio.to_thread(
            analyze_image,
            buffer.getvalue(),
            caption,
        )

        if answer:
            await message.reply_text(answer)

    except Exception:
        logger.exception("Image analysis error")

        await message.reply_text(
            "⚠️ I couldn't analyze the image. Try again."
        )


# =========================================================
# IMAGES SENT AS FILES
# =========================================================

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message

    if not message or not message.document:
        return

    caption = (message.caption or "").strip()

    allowed = await group_message_is_for_bot(
        update,
        context,
        caption,
    )

    if not allowed:
        return

    document = message.document
    mime_type = document.mime_type or ""

    bot = await context.bot.get_me()

    caption = clean_mention(
        caption,
        bot.username or "",
    )

    if not mime_type.startswith("image/"):
        await message.reply_text(
            "Send the important PDF page as a screenshot 🛡️"
        )
        return

    try:
        telegram_file = await document.get_file()

        buffer = BytesIO()

        await telegram_file.download_to_memory(
            out=buffer
        )

        answer = await asyncio.to_thread(
            analyze_image,
            buffer.getvalue(),
            caption,
        )

        if answer:
            await message.reply_text(answer)

    except Exception:
        logger.exception("Document analysis error")

        await message.reply_text(
            "⚠️ I couldn't analyze the file."
        )


# =========================================================
# ERRORS
# =========================================================

async def error_handler(update, context):
    logger.error(
        "Telegram error: %s",
        context.error,
    )


# =========================================================
# RUN
# =========================================================

def main():
    application = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Document.ALL,
            handle_document,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text,
        )
    )

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "ROSaleen mention-only version started"
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
