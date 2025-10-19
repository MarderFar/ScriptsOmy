import threading
import telebot
from telebot import types

bot = telebot.TeleBot('8213814908:AAFC7joj7aEnmWCFUGVwVMPe9UBCJbXyx70')

def create_main_inline_buttons():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Выбор теста для прохождения", callback_data="test_choice"))
    markup.add(types.InlineKeyboardButton("Что умеет бот?", callback_data="bot_info"))
    markup.add(types.InlineKeyboardButton("Мои Подписки", callback_data="purchases"))
    return markup

def send_telegram_report(telegram_id, test_name, score, status, image_path=None):
    if not telegram_id or not str(telegram_id).isdigit():
        print(f"⚠️ Telegram ID некорректен ({telegram_id}) — уведомление пропущено.")
        return

    msg = (
        f"📘 *Уведомление о прохождении теста!*\n\n"
        f"🧪 *Название:* {test_name}\n"
        f"⭐ *Оценка:* {score}\n"
        f"📊 *Статус:* {status}"
    )

    def send():
        try:
            markup = create_main_inline_buttons()
            if image_path:
                with open(image_path, "rb") as photo:
                    bot.send_photo(int(telegram_id), photo, caption=msg, parse_mode="Markdown", reply_markup=markup)
            else:
                bot.send_message(int(telegram_id), msg, parse_mode="Markdown", reply_markup=markup)
            print(f"✅ Уведомление отправлено пользователю {telegram_id}")
        except Exception as e:
            print(f"❌ Ошибка при отправке уведомления: {e}")

    threading.Thread(target=send, daemon=True).start()
