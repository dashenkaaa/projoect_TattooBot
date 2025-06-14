import logging
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
)

BOT_TOKEN = 'token'
MASTER_CHAT_ID = id
STUDIO_ADDRESS = "г. Москва, ул. Столетова, 7к1"
MASTER_USERNAME = "@traditional_ink_direct"

# Состояния для ConversationHandler
CHOOSING, TYPING_TIME, CANCELING = range(3)

def generate_free_slots(days=7):
    slots = []
    start_time = datetime.now()
    for i in range(days):
        day = start_time + timedelta(days=i)
        for hour in [9, 10, 11]:
            slot = day.replace(hour=hour, minute=0)
            slots.append(slot.strftime("%d %B %H:%M"))
    return slots

FREE_SLOTS = generate_free_slots()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def init_db():
    conn = sqlite3.connect("appointments.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            datetime TEXT,
            service_type TEXT,
            status TEXT DEFAULT 'подтверждено',
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    return conn

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🗓 Очная консультация", callback_data="consultation")],
        [InlineKeyboardButton("📆 Свободное время", callback_data="free_time")],
        [InlineKeyboardButton("🖋 Тату-сеанс", callback_data="tattoo_session")],
        [InlineKeyboardButton("💬 Онлайн консультация", callback_data="online_consult")],
        [InlineKeyboardButton("❌ Отменить запись", callback_data="cancel_appointment")]
    ]
    text = "👋 Привет! Я бот-помощник Traditional Ink Moscow.\n\nВыберите действие:"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update, context)
    return CHOOSING

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data in ["consultation", "tattoo_session"]:
        context.user_data['service_type'] = "консультация" if data == "consultation" else "тату-сеанс"
        await query.edit_message_text(
            f"📍 {STUDIO_ADDRESS}\n\n"
            f"Свободное время для {context.user_data['service_type']}:\n- " + "\n- ".join(FREE_SLOTS) + "\n\n"
            "Пожалуйста, введите удобное время (например: 12 июня 14:00):"
        )
        return TYPING_TIME

    elif data == "free_time":
        await query.edit_message_text("📅 Свободные слоты:\n" + "\n".join(FREE_SLOTS))
        # После показа свободного времени вернемся в меню
        await show_main_menu(update, context)
        return CHOOSING

    elif data == "online_consult":
        await query.edit_message_text(f"🔗 Бесплатная онлайн-консультация: {MASTER_USERNAME}")
        # После показа информации вернемся в меню
        await show_main_menu(update, context)
        return CHOOSING

    elif data == "cancel_appointment":
        await query.edit_message_text("Введите дату и время записи, которую нужно отменить:")
        return CANCELING

    else:
        await query.edit_message_text("Неизвестная команда, попробуйте снова.")
        return CHOOSING

async def received_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    username = user.username or user.first_name
    text = update.message.text.strip()
    service_type = context.user_data.get('service_type')
    status = "ожидает оплаты" if service_type == "тату-сеанс" else "подтверждено"

    conn = sqlite3.connect("appointments.db")
    cursor = conn.cursor()

    # Проверка лимита записей на день
    date_part = text.split()[0]
    cursor.execute(
        "SELECT COUNT(*) FROM appointments WHERE username = ? AND datetime LIKE ?",
        (username, f"{date_part}%")
    )
    count = cursor.fetchone()[0]
    if count >= 2:
        await update.message.reply_text("⚠️ Вы уже записаны дважды на этот день.")
        conn.close()
        return await back_to_menu(update, context)

    cursor.execute(
        "INSERT INTO appointments (username, datetime, service_type, status) VALUES (?, ?, ?, ?)",
        (username, text, service_type, status)
    )
    conn.commit()
    conn.close()

    response = (
        f"✅ Вы записаны на {service_type} в {text}.\n"
        f"{'⚠️ Пожалуйста, внесите предоплату в течение 24 часов.' if service_type == 'тату-сеанс' else ''}"
    )
    await update.message.reply_text(response)

    # Уведомление мастеру
    await context.bot.send_message(
        chat_id=MASTER_CHAT_ID,
        text=(
            f"🔔 Новая запись\n"
            f"👤 @{username}\n"
            f"📅 {text}\n"
            f"💼 {service_type}\n"
            f"🔹 Статус: {status}"
        )
    )
    return await back_to_menu(update, context)

async def cancel_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    username = user.username or user.first_name
    text = update.message.text.strip()

    conn = sqlite3.connect("appointments.db")
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM appointments WHERE username = ? AND datetime LIKE ?",
        (username, f"%{text}%")
    )
    deleted_rows = cursor.rowcount
    conn.commit()
    conn.close()

    msg = "❌ Запись отменена." if deleted_rows > 0 else "⚠️ Запись не найдена."
    await update.message.reply_text(msg)
    return await back_to_menu(update, context)

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update, context)
    return CHOOSING

async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Пожалуйста, выберите действие из меню или отправьте /start для начала.")
    return CHOOSING

def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CHOOSING: [
                CallbackQueryHandler(button_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, fallback)
            ],
            TYPING_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_time)
            ],
            CANCELING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cancel_appointment)
            ],
        },
        fallbacks=[CommandHandler('start', start)],
        allow_reentry=True,
    )

    app.add_handler(conv_handler)

    # Ежедневное напоминание в 9:00
    app.job_queue.run_daily(
        lambda ctx: send_daily_reminders(ctx),
        time=datetime.strptime("09:00", "%H:%M").time()
    )

    logger.info("Бот запущен")
    app.run_polling()

async def send_daily_reminders(context: ContextTypes.DEFAULT_TYPE):
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%d %B')
    conn = sqlite3.connect("appointments.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT username, datetime, service_type FROM appointments WHERE datetime LIKE ? AND status != 'отменено'",
        (f"{tomorrow}%",)
    )
    appointments = cursor.fetchall()
    conn.close()

    for username, appt_time, service_type in appointments:
        try:
            await context.bot.send_message(
                chat_id=f"@{username}",
                text=f"🔔 Напоминаем: завтра у вас запись на {service_type} в {appt_time}!\n📍 Адрес: {STUDIO_ADDRESS}"
            )
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления @{username}: {e}")

if __name__ == '__main__':
    main()
