import os
import base64
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

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

SYSTEM_PROMPT = """
You are Rosaleen Safety AI, an assistant for a US trucking safety department.

Help with:
- CDL information and expiration dates
- MVRs
- DOT inspections and violations
- FMCSA safety questions
- driver qualification and onboarding
- Clearinghouse and SAP questions
- trucking compliance

Be concise and practical.
Never invent information from a document or image.
If something is unclear or unreadable, say so.
For legal or compliance questions, explain when official verification is needed.
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌹 Rosaleen Safety AI is online.\n\n"
        "Send me a safety question or upload a CDL/inspection photo."
    )

async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        response = client.responses.create(
            model="gpt-4.1-mini",
            instructions=SYSTEM_PROMPT,
            input=update.message.text,
        )
        await update.message.reply_text(response.output_text)
    except Exception as e:
        print(e)
        await update.message.reply_text("⚠️ AI error. Please try again.")

async def photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        photo = update.message.photo[-1]
        tg_file = await photo.get_file()

        data = BytesIO()
        await tg_file.download_to_memory(out=data)
        image_b64 = base64.b64encode(data.getvalue()).decode("utf-8")

        question = update.message.caption or (
            "Analyze this trucking safety document. "
            "If it is a CDL, identify the state, class and expiration date."
        )

        response = client.responses.create(
            model="gpt-4.1-mini",
            instructions=SYSTEM_PROMPT,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": question},
                        {
                            "type": "input_image",
                            "image_url": f"data:image/jpeg;base64,{image_b64}",
                        },
                    ],
                }
            ],
        )

        await update.message.reply_text(response.output_text)

    except Exception as e:
        print(e)
        await update.message.reply_text("⚠️ I couldn't analyze this image.")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, photo_message))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_message)
    )

    print("Rosaleen Safety AI is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
