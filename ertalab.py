import os
import asyncio
import base64
import logging
from io import BytesIO

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

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is missing")

client = OpenAI(api_key=OPENAI_API_KEY)


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("RosaleenSafetyAI")


# =========================================================
# SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = """
You are Rosaleen Safety AI, an experienced US trucking
Safety and Compliance assistant.

You help with:
- CDL
- Medical Cards
- MVR
- PSP
- Driver Qualification Files
- Clearinghouse
- SAP / Return-to-Duty
- Drug and Alcohol testing
- FMCSA
- DOT inspections
- Out-of-Service violations
- DataQs
- HOS
- ELD
- CSA / SMS
- Amazon Relay
- RMIS
- COI
- insurance
- Great West
- Progressive
- GEICO
- claims
- IFTA
- IRP
- Form 2290
- UCR
- state permits
- Safety audits
- driver onboarding
- driver termination

RESPONSE STYLE:
- Keep answers short.
- Usually answer in 1 to 3 sentences.
- Give the direct answer first.
- Do not write long explanations unless specifically asked.
- Do not repeat the question.
- Be practical and professional.
- Reply in the same language the user uses.
- Understand English, Russian and Uzbek.

DOCUMENT ANALYSIS:
For CDL:
- name
- state
- class
- expiration
- endorsements
- restrictions
- visible concerns

For Medical Card:
- name
- expiration
- restrictions
- visible concerns

For MVR:
- license status
- violations
- suspensions
- accidents
- important dates
- hiring concerns
- points only when supported

For DOT inspections:
- date
- violations
- OOS
- driver vs vehicle
- Safety concern
- corrective action

IMPORTANT:
- Never invent facts.
- Never invent points.
- Never invent FMCSA status.
- Never invent insurance approval.
- Never invent Clearinghouse status.
- Never invent Amazon status.
- If information is missing, analyze what is available and say what Safety should verify next.
- If part of an image is unreadable, analyze the readable part.
- Do not unnecessarily refuse normal trucking Safety questions.
"""


# =========================================================
# OPENAI TEXT
# =========================================================

def ask_ai(text: str) -> str:
    response = client.responses.create(
        model=OPENAI_MODEL,
        instructions=SYSTEM_PROMPT,
        input=text,
        max_output_tokens=220,
    )

    return response.output_text.strip()


# =========================================================
# OPENAI IMAGE
# =========================================================

def analyze_image(image_bytes: bytes, question: str = "") -> str:
    encoded = base64.b64encode(
        image_bytes
    ).decode("utf-8")

    if not question:
        question = (
            "Analyze this image briefly as a trucking Safety Manager. "
            "Tell me the important information and what Safety should do next."
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
                        "image_url": (
                            "data:image/jpeg;base64,"
                            + encoded
                        ),
                    },
                ],
            }
        ],
        max_output_tokens=220,
    )

    return response.output_text.strip()


# =========================================================
# REMOVE @MENTION
# =========================================================

def remove_mention(text: str, username: str) -> str:
    if not text or not username:
        return text.strip()

    mention = f"@{username}"

    lower_text = text.casefold()
    lower_mention = mention.casefold()

    while lower_mention in lower_text:
        index = lower_text.find(lower_mention)

        text = (
            text[:index]
            + text[index + len(mention):]
        )

        lower_text = text.casefold()

    return text.strip()


# =========================================================
# /START
# =========================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.effective_message.reply_text(
        "🛡 Rosaleen Safety AI is online."
    )


# =========================================================
# TEXT HANDLER
# =========================================================

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message
    chat = update.effective_chat

    if not message or not message.text or not chat:
        return

    text = message.text.strip()

    # -----------------------------------------------------
    # PRIVATE CHAT
    # Always answer
    # -----------------------------------------------------

    if chat.type == "private":
        question = text

    # -----------------------------------------------------
    # GROUP CHAT
    # ONLY answer when @mentioned
    # -----------------------------------------------------

    elif chat.type in ("group", "supergroup"):
        me = await context.bot.get_me()

        if not me.username:
            return

        mention = f"@{me.username}"

        # HARD FILTER
        # No mention = no response
        if mention.casefold() not in text.casefold():
            logger.info("Ignored normal group message")
            return

        question = remove_mention(
            text,
            me.username,
        )

        if not question:
            await message.reply_text("Yes 🛡️")
            return

    else:
        return

    try:
        await context.bot.send_chat_action(
            chat_id=chat.id,
            action="typing",
        )

        answer = await asyncio.to_thread(
            ask_ai,
            question,
        )

        if answer:
            await message.reply_text(
                answer[:1200]
            )

    except Exception:
        logger.exception("Text AI error")

        await message.reply_text(
            "⚠️ Temporary error. Try again."
        )


# =========================================================
# PHOTO HANDLER
# =========================================================

async def photo_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message
    chat = update.effective_chat

    if not message or not message.photo or not chat:
        return

    caption = (
        message.caption or ""
    ).strip()

    # PRIVATE
    if chat.type == "private":
        question = caption

    # GROUP
    elif chat.type in ("group", "supergroup"):
        me = await context.bot.get_me()

        if not me.username:
            return

        mention = f"@{me.username}"

        # In group, photo must also contain @mention
        if mention.casefold() not in caption.casefold():
            logger.info("Ignored normal group photo")
            return

        question = remove_mention(
            caption,
            me.username,
        )

    else:
        return

    try:
        await context.bot.send_chat_action(
            chat_id=chat.id,
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
            question,
        )

        if answer:
            await message.reply_text(
                answer[:1200]
            )

    except Exception:
        logger.exception("Photo AI error")

        await message.reply_text(
            "⚠️ I couldn't analyze the image."
        )


# =========================================================
# DOCUMENT HANDLER
# =========================================================

async def document_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message
    chat = update.effective_chat

    if not message or not message.document or not chat:
        return

    document = message.document
    caption = (
        message.caption or ""
    ).strip()

    # PRIVATE
    if chat.type == "private":
        question = caption

    # GROUP
    elif chat.type in ("group", "supergroup"):
        me = await context.bot.get_me()

        if not me.username:
            return

        mention = f"@{me.username}"

        if mention.casefold() not in caption.casefold():
            return

        question = remove_mention(
            caption,
            me.username,
        )

    else:
        return

    mime_type = document.mime_type or ""

    # Only image files for now
    if not mime_type.startswith("image/"):
        await message.reply_text(
            "📄 Send the important PDF page as a screenshot."
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
            question,
        )

        if answer:
            await message.reply_text(
                answer[:1200]
            )

    except Exception:
        logger.exception("Document AI error")

        await message.reply_text(
            "⚠️ I couldn't analyze the file."
        )


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
# MAIN
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
            start_command,
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
        "Rosaleen Safety AI mention-only version started"
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
