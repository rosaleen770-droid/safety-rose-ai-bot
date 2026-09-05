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

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini").strip()

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
You are Rosaleen Safety AI, an experienced US trucking Safety and Compliance assistant.

Your main areas:
- CDL
- Medical Card
- MVR
- PSP
- Clearinghouse
- SAP / Return-to-Duty
- Drug & Alcohol testing
- Driver Qualification Files
- FMCSA
- DOT inspections
- violations
- Out-of-Service
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
- 2290
- UCR
- NY HUT
- Oregon permits
- New Mexico permits
- Kentucky permits
- PrePass
- Safety audits
- driver onboarding
- driver termination

RESPONSE STYLE:
- Be short.
- Usually answer in 1 to 4 sentences.
- Give the direct answer first.
- Do not write long explanations unless asked.
- Do not repeat the question.
- Sound like an experienced trucking Safety Manager.
- Be practical and operational.
- Reply in the same language the user uses.
- Understand English, Russian and Uzbek.

DOCUMENT ANALYSIS:
For CDL, check:
- name
- state
- class
- issue date
- expiration date
- endorsements
- restrictions
- visible concerns

For Medical Card, check:
- name
- issue date
- expiration date
- restrictions
- visible concerns

For MVR, check:
- license status
- violations
- suspensions
- accidents
- important dates
- hiring concerns
- points only when supported

For DOT inspections, check:
- date
- state
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
- If an image is partly unreadable, analyze the readable part.
- Do not unnecessarily refuse normal trucking Safety questions.
- Keep answers concise.
"""


# =========================================================
# OPENAI TEXT
# =========================================================

def ask_openai_text(text: str) -> str:
    response = client.responses.create(
        model=OPENAI_MODEL,
        instructions=SYSTEM_PROMPT,
        input=text,
        max_output_tokens=300,
    )

    return response.output_text.strip()


# =========================================================
# OPENAI IMAGE
# =========================================================

def ask_openai_image(image_bytes: bytes, caption: str = "") -> str:
    encoded = base64.b64encode(image_bytes).decode("utf-8")

    prompt = caption.strip()

    if not prompt:
        prompt = (
            "Analyze this image briefly as a trucking Safety Manager. "
            "Tell me what it shows, important dates or issues, "
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
                        "image_url": f"data:image/jpeg;base64,{encoded}",
                    },
                ],
            }
        ],
        max_output_tokens=300,
    )

    return response.output_text.strip()


# =========================================================
# GROUP CONTROL
# =========================================================

async def should_answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str = "",
) -> bool:

    chat = update.effective_chat
    message = update.effective_message

    if not chat or not message:
        return False

    # PRIVATE CHAT -> ALWAYS ANSWER
    if chat.type == "private":
        return True

    # GROUPS
    if chat.type not in ("group", "supergroup"):
        return False

    # 1. CHECK @MENTION
    bot_username = context.bot.username or ""

    if bot_username:
        mention = f"@{bot_username}"

        if mention.lower() in text.lower():
            return True

    # 2. CHECK REPLY TO BOT
    if (
        message.reply_to_message
        and message.reply_to_message.from_user
    ):
        bot_info = await context.bot.get_me()

        if message.reply_to_message.from_user.id == bot_info.id:
            return True

    # NORMAL GROUP MESSAGE -> IGNORE
    return False


def remove_mention(text: str, username: str) -> str:
    if not text or not username:
        return text.strip()

    mention = f"@{username}"

    lower_text = text.lower()
    lower_mention = mention.lower()

    while lower_mention in lower_text:
        index = lower_text.find(lower_mention)

        text = text[:index] + text[index + len(mention):]

        lower_text = text.lower()

    return text.strip()


# =========================================================
# /START
# =========================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.effective_message.reply_text(
        "🛡 Rosaleen Safety AI is online.\n"
        "Send me a Safety question, CDL, MVR, inspection or document."
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

    answer_allowed = await should_answer(
        update,
        context,
        text,
    )

    if not answer_allowed:
        return

    if context.bot.username:
        text = remove_mention(
            text,
            context.bot.username,
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
            ask_openai_text,
            text,
        )

        if not answer:
            answer = "Please try again."

        await message.reply_text(answer)

    except Exception as e:
        logger.exception("Text handler error: %s", e)

        await message.reply_text(
            "⚠️ Temporary error. Please try again."
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

    caption = (message.caption or "").strip()

    answer_allowed = await should_answer(
        update,
        context,
        caption,
    )

    if not answer_allowed:
        return

    if context.bot.username:
        caption = remove_mention(
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

        if not answer:
            answer = "I couldn't analyze this image."

        await message.reply_text(answer)

    except Exception as e:
        logger.exception("Photo handler error: %s", e)

        await message.reply_text(
            "⚠️ I couldn't analyze this image. Please try again."
        )


# =========================================================
# IMAGE FILE HANDLER
# =========================================================

async def document_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message

    if not message or not message.document:
        return

    document = message.document
    caption = (message.caption or "").strip()

    answer_allowed = await should_answer(
        update,
        context,
        caption,
    )

    if not answer_allowed:
        return

    if context.bot.username:
        caption = remove_mention(
            caption,
            context.bot.username,
        )

    mime_type = document.mime_type or ""

    # IMAGE FILE
    if mime_type.startswith("image/"):
        try:
            tg_file = await document.get_file()

            buffer = BytesIO()

            await tg_file.download_to_memory(
                out=buffer
            )

            answer = await asyncio.to_thread(
                ask_openai_image,
                buffer.getvalue(),
                caption,
            )

            await message.reply_text(answer)

        except Exception as e:
            logger.exception("Document image error: %s", e)

            await message.reply_text(
                "⚠️ I couldn't analyze this image."
            )

        return

    await message.reply_text(
        "📄 Send the important PDF page as a screenshot "
        "and I can analyze it."
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

    logger.info("Rosaleen Safety AI started")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()
