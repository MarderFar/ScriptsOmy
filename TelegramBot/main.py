import threading

import telebot
from telebot import types
import random
import time
from threading import Thread, Lock
from queue import Queue
import json
import sys
import os
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials
from telebot.apihelper import ApiTelegramException



sys.path.append(r"C:\Users\MarderFar\PycharmProjects\SberCheck")
from AuthorizeCheck import check_login

# Добавляем путь к main.py (там должна быть функция run_sbercheck)
sys.path.append(r"C:\Users\MarderFar\PycharmProjects\SberCheck")
from sbercheck import run_sbercheck

# Инициализация бота с вашим токеном
bot = telebot.TeleBot('8213814908:AAFC7joj7aEnmWCFUGVwVMPe9UBCJbXyx70')

# Хранилище для состояний и платежей
user_states = {}
user_payments = {}
current_message = {}
user_in_process = {}
user_purchases = {}

positions_list = [
    "Начальник и диспетчер ОДГ",
    "Электромонтер ОВБ",
    "Электромонтер по обслуживанию подстанций",
    "Мастер по эксплуатации РС и КЛ",
    "Начальник, мастер и инженер УТЭЭТ",
    "Электромонтер РС",
    "Электромонтер по ремонту и монтажу КЛ",
    "Электромонтер по эксплуатации электросчетчиков",
    "Руководители РЭС",
    "Руководители службы ПС",
    "Инженерский и мастерский состав СПС",
    "Монтерский состав СПС",
    "Руководители службы РЗиА",
    "Инженерский и мастерский состав СРЗиА",
    "Монтерский состав СРЗиА",
    "Руководители службы ВЛ",
    "Инженерский и мастерский состав СВЛ",
    "Монтерский состав СВЛ",
    "Руководители службы ИЗПИ",
    "Инженерский и мастерский состав СИЗПИ",
    "Монтерский состав СИЗПИ",
    "Руководители службы СМУ",
    "Инженерский и мастерский состав СМУ",
    "Монтерский состав СМУ",
    "Руководители службы ДС, ОДС ЦУС",
    "Диспетчер ДС, ОДС ЦУС"
]

POSITIONS_PER_PAGE = 7

PURCHASES_FILE = "user_purchases.json"

#Google Tables
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
SERVICE_ACCOUNT_FILE = r"C:\Users\MarderFar\Desktop\Work\everydayscript-86548f80b016.json"  # путь к JSON

creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
gc = gspread.authorize(creds)

USERS_SHEET = gc.open("UsersEvery").sheet1  # таблица, куда сохраняем данные
# Загрузка данных при старте
if os.path.exists(PURCHASES_FILE):
    with open(PURCHASES_FILE, "r", encoding="utf-8") as f:
        raw_data = json.load(f)
        # преобразуем даты из строки в datetime
        user_purchases = {}
        for user_id, purchases in raw_data.items():
            user_purchases[int(user_id)] = []
            for p in purchases:
                start_date = datetime.strptime(p['start_date'], "%Y-%m-%d")
                end_date = datetime.strptime(p['end_date'], "%Y-%m-%d")
                user_purchases[int(user_id)].append({
                    "test_name": p['test_name'],
                    "position": p.get("position", "Не выбран"),
                    "start_date": start_date,
                    "end_date": end_date
                })
else:
    user_purchases = {}
# --- Очередь задач ---
MAX_PROFILES = 1
task_queue = Queue()
queue_lock = Lock()
current_tasks = 0
user_positions = {}  # chat_id -> объект сообщения для редактирования

# --- Генерация суммы ---
def generate_amount():
    return round(random.uniform(300, 301), 2)

def generate_unique_amount(user_id, months=1):
    base_amount = 300 * months
    while True:
        # Добавляем случайную копейку (0.01 - 0.99)
        amount = round(base_amount + random.uniform(0.01, 1.99), 2)
        # Проверяем, что такая сумма еще не используется другими пользователями
        if amount not in [p['amount'] for p in user_payments.values()]:
            break

    # Сохраняем для пользователя с отметкой времени
    user_payments[user_id] = {'amount': amount, 'timestamp': time.time()}
    return amount
@bot.message_handler(func=lambda message: message.text == "Начать")
def handle_nachat(message):
    send_welcome(message.chat.id)

def send_welcome_keyboard(chat_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("Начать"))
    bot.send_message(chat_id, "Привет! Нажмите кнопку, чтобы начать работу с ботом.", reply_markup=markup)
# --- Кнопки ---
def create_main_inline_buttons():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Выбор теста для прохождения", callback_data="test_choice"))
    markup.add(types.InlineKeyboardButton("Что умеет бот?", callback_data="bot_info"))
    markup.add(types.InlineKeyboardButton("Мои Подписки", callback_data="purchases"))
    return markup

def create_purchases_buttons():
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("🔄 Продлить на 1 месяц", callback_data="extend_1m"),
        types.InlineKeyboardButton("🔄 Продлить на 3 месяца", callback_data="extend_3m")
    )
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main"))
    return markup
def create_bot_info_inline_buttons():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Подробнее о прохождении ПЭП-теста", callback_data="pep_info"))
    markup.add(types.InlineKeyboardButton("Подробнее о ежедневном тестировании", callback_data="daily_test_info"))
    markup.add(types.InlineKeyboardButton("Назад", callback_data="back_from_bot_info"))
    return markup

def create_test_choice_inline_buttons():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("ПЭП-тест", callback_data="pep_test"))
    markup.add(types.InlineKeyboardButton("Ежедневное тестирование", callback_data="daily_test"))
    markup.add(types.InlineKeyboardButton("Назад", callback_data="back_from_test_choice"))
    return markup

def create_payment_inline_buttons():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Назад", callback_data="back_from_payment"))
    markup.add(types.InlineKeyboardButton("Оплатить", callback_data="pay"))
    markup.add(types.InlineKeyboardButton("Я оплатил", callback_data="pay_done"))
    return markup

def create_position_buttons():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Слесарь", callback_data="position_sl"))
    markup.add(types.InlineKeyboardButton("Монтажник", callback_data="position_mn"))
    markup.add(types.InlineKeyboardButton("Строитель", callback_data="position_st"))
    return markup

def create_time_buttons():
    markup = types.InlineKeyboardMarkup()
    times = ["6:00", "12:00", "18:00", "24:00"]
    buttons = [types.InlineKeyboardButton(t, callback_data=f"time_{t}") for t in times]
    markup.row(*buttons)
    return markup


# --- Очередь и управление проверками ---
def update_queue_positions():
    with queue_lock:
        queue_list = list(task_queue.queue)
        for pos, task in enumerate(queue_list, start=1):
            chat_id = task['user_id']
            if chat_id in user_positions:
                try:
                    bot.edit_message_text(f"⏳ Вы в очереди на проверку... Пожалуйста подождите, это займет не более 5 минут.\nВаше место: {pos}",
                                          chat_id=chat_id, message_id=user_positions[chat_id].message_id)
                except:
                    pass

def add_to_queue(user_id, amount, message):
    task = {'user_id': user_id, 'amount': amount, 'message': message}
    task_queue.put(task)
    user_positions[user_id] = message
    update_queue_positions()

def worker():
    global current_tasks
    while True:
        task = task_queue.get()
        with queue_lock:
            current_tasks += 1

        user_id = task['user_id']
        message = task['message']
        bot.edit_message_text("⏳ Идет проверка оплаты...", user_id, message.message_id,
                              reply_markup=create_payment_inline_buttons())

        try:
            status_bool = run_sbercheck(task['amount'])
            if status_bool:
                payment_type = user_states[user_id].get("payment_type", "new")
                today = datetime.today()

                if payment_type.startswith("extend"):
                    months = 1 if payment_type == "extend_1m" else 3
                    p = user_purchases[user_id][0]

                    today = datetime.today()
                    if p['end_date'] >= today:
                        p['end_date'] += timedelta(days=30 * months)
                    else:
                        p['start_date'] = today
                        p['end_date'] = today + timedelta(days=30 * months)

                    save_purchases()
                    save_user_to_gsheet(user_id, extend=True, new_end_date=p['end_date'])

                    bot.send_message(
                        user_id,
                        f"✅ Подписка продлена на {months} мес!\n"
                        f"Новая дата окончания: {p['end_date'].strftime('%d.%m.%Y')}",
                        reply_markup=create_main_inline_buttons()
                    )

                else:
                    # --- Первая подписка ---
                    if has_active_subscription(user_id):
                        # На всякий случай, если уже есть подписка
                        p = user_purchases[user_id][0]
                        p['end_date'] += timedelta(days=30)
                        save_purchases()
                        save_user_to_gsheet(user_id)
                        bot.send_message(
                            user_id,
                            f"✅ Подписка продлена на 1 мес!\nНовая дата окончания: {p['end_date'].strftime('%d.%m.%Y')}",
                            reply_markup=create_main_inline_buttons()
                        )
                    else:
                        # Первая покупка — запускаем ввод данных
                        user_states[user_id]['step'] = 'await_login'
                        bot.send_message(
                            user_id,
                            "💳 Оплата прошла успешно!\n\nПожалуйста, введите ваш логин для входа на сайт:"
                        )

                user_states[user_id]["in_process"] = False
            else:
                # Добавляем кнопку "Написать в поддержку" при неудачной оплате
                support_button = types.InlineKeyboardButton(
                    "Написать в поддержку",
                    url="https://t.me/face2ren"
                )
                back_button = types.InlineKeyboardButton(
                    "⬅️ Назад",
                    callback_data="back_from_payment"
                )
                support_markup = types.InlineKeyboardMarkup()
                support_markup.add(support_button)
                support_markup.add(back_button)  # <-- добавляем кнопку назад
                bot.edit_message_text(
                    "❌ *Оплата не найдена!*\n\n"
                    "💡 Похоже, что перевод ещё не поступил.\n\n"
                    "📌 Чтобы мы могли быстро помочь, напишите в поддержку и укажите:\n"
                    "▫️ *ФИО* отправителя перевода\n"
                    "▫️ *Точную сумму* перевода (например, 300.50 ₽)\n\n"
                    "🛠 Нажмите кнопку ниже, чтобы сразу связаться с менеджером.",
                    user_id,
                    message.message_id,
                    parse_mode="Markdown",
                    reply_markup=support_markup
                )
                user_states[user_id]["in_process"] = False

        except Exception as e:
            bot.edit_message_text(f"Произошла ошибка при проверке оплаты: {e}", user_id, message.message_id,
                                  reply_markup=create_payment_inline_buttons())
            user_states[user_id]["in_process"] = False
        finally:
            with queue_lock:
                current_tasks -= 1
            task_queue.task_done()
            update_queue_positions()

# --- запуск worker ---
for _ in range(MAX_PROFILES):
    Thread(target=worker, daemon=True).start()

#Проверка наличия подписки
def has_active_subscription(user_id, test_type="Ежедневное тестирование"):
    if user_id not in user_purchases:
        return False
    today = datetime.today()
    for p in user_purchases[user_id]:
        if p.get('test_name') == test_type and p.get('end_date') >= today:
            return True
    return False
# --- Обработка оплаты ---

def pay_done(call):
    user_id = call.message.chat.id
    message = call.message

    # Защита: если вдруг подписка уже активна — отменяем


    # Проверяем состояние пользователя
    if user_id not in user_states:
        user_states[user_id] = {"in_process": False, "current_message": None}

    if user_states[user_id]["in_process"]:
        bot.answer_callback_query(call.id, "Пожалуйста, подождите, пока предыдущая проверка не завершится.")
        return

    # Ставим флаг, что проверка идёт
    user_states[user_id]["in_process"] = True

    # Берем текущую сумму для проверки
    amount = user_payments.get(user_id, {}).get('amount')
    if not amount:
        payment_type = user_states.get(user_id, {}).get("payment_type", "new")
        months = 1 if payment_type == "extend_1m" else 3 if payment_type == "extend_3m" else 1
        amount = generate_unique_amount(user_id, months)

    # Добавляем задачу в очередь проверки оплаты
    add_to_queue(user_id, amount, message)


# --- Оплата (информация для кнопки) ---

def pay(call):
    user_id = call.message.chat.id
    msg_id = call.message.message_id

    # Генерируем сумму
    if (user_id not in user_payments) or (time.time() - user_payments[user_id]['timestamp'] > 600):
        amount = generate_unique_amount(user_id)
    else:
        amount = user_payments[user_id]['amount']

    payment_message = (
        f"💳 Переведите на карту: *2202 2016 0199 5356* \n"
        f"💵 Указанную сумму - *{amount}* руб.\n\n"
        f"⚠️ *Важно:* переводите указанную сумму *вплоть до копейки*!\n\n"
        "После перевода нажмите кнопку *«Я оплатил»*, чтобы подтвердить оплату.\n"
        "⏳ Проверка оплаты займет до *5 минут*, дождитесь изменения статуса."
    )
    try:
        bot.edit_message_text(payment_message, user_id, msg_id,
                              reply_markup=create_payment_inline_buttons(),
                              parse_mode="Markdown")
    except ApiTelegramException:
        bot.send_message(user_id, payment_message,
                         reply_markup=create_payment_inline_buttons(),
                         parse_mode="Markdown")

def ensure_user_state(user_id):
    if user_id not in user_states:
        user_states[user_id] = {}

    # гарантируем поле для credentials
    if 'credentials' not in user_states[user_id]:
        user_states[user_id]['credentials'] = {'login': '', 'password': ''}

    # гарантируем поле для текущего шага
    if 'step' not in user_states[user_id]:
        user_states[user_id]['step'] = None

    # флаг обработки
    if 'in_process' not in user_states[user_id]:
        user_states[user_id]['in_process'] = False
#Cохранение покупки
def save_purchases():
    to_save = {}
    for user_id, purchases in user_purchases.items():
        to_save[user_id] = []
        for p in purchases:
            to_save[user_id].append({
                "test_name": p['test_name'],
                "start_date": p['start_date'].strftime("%Y-%m-%d"),
                "position": p['position'],
                "end_date": p['end_date'].strftime("%Y-%m-%d")
            })
    with open(PURCHASES_FILE, "w", encoding="utf-8") as f:
        json.dump(to_save, f, ensure_ascii=False, indent=4)
# --- Приветствие ---
def send_welcome(chat_id):
    user_states[chat_id] = {
        "in_process": False,
        "current_message": None,
        "credentials": {"login": "", "password": ""}  # ← добавил
    }
    bot.send_message(
        chat_id,
        "👋 *Добро пожаловать!*\n\n"
        "Этот бот поможет вам с прохождением тестов:\n"
        "🔹 *Предэкзаменационная подготовка (ПЭП-тест)*\n"
        "🔹 *Ежедневная проверка знаний (охрана труда)*\n\n"
        "📌 Выберите нужный раздел ниже, чтобы узнать подробнее или оформить услугу 👇",
        parse_mode="Markdown",
        reply_markup=create_main_inline_buttons()
    )
@bot.message_handler(commands=['start'])
def handle_start(message):
    send_welcome(message.chat.id)

@bot.callback_query_handler(func=lambda call: call.data in ["pay", "pay_done", "extend_1m", "extend_3m", "back_from_payment"])
def handle_payment(call):
    user_id = call.message.chat.id
    message = call.message

    # Обработка возврата в меню
    if call.data == "back_from_payment":
        bot.edit_message_text(
            "📌Выберите тип теста для прохождения:\n\n"
            "👉Рекомендую сначала ознакомиться с каждым из типов тестов во вкладке *Что умеет бот*\n\n",
            user_id, message.message_id, parse_mode="Markdown", reply_markup=create_test_choice_inline_buttons()
        )
        return

    # Обработка продления
    if call.data.startswith("extend_"):
        months = 1 if call.data == "extend_1m" else 3
        amount = generate_unique_amount(user_id, months)
        user_states[user_id] = {"in_process": False, "payment_type": call.data}
        payment_message = (
            f"💳 Для продления подписки на *{months} мес.* "
            f"Вам нужно будет перевести деньги на карту на указанную сумму\n\n"
            "⚠️ Важно: сумма должна совпадать *вплоть до копейки*!\n\n"
            "Для оплаты нажмите «Оплатить»."
        )
        bot.edit_message_text(payment_message, user_id, message.message_id, parse_mode="Markdown",
                              reply_markup=create_payment_inline_buttons())
        return

    # Новая подписка
    if call.data == "pay":
        pay(call)  # вызываем твою функцию

    # Подтверждение оплаты
    if call.data == "pay_done":
        # Создаём словарь состояния пользователя, если его ещё нет
        if user_id not in user_states:
            user_states[user_id] = {}

        # Гарантируем наличие ключей
        if "in_process" not in user_states[user_id]:
            user_states[user_id]["in_process"] = False
        if "payment_type" not in user_states[user_id]:
            user_states[user_id]["payment_type"] = "new"

        payment_type = user_states[user_id]["payment_type"]

        # Блокируем только покупку новой подписки при активной
        if payment_type == "new" and has_active_subscription(user_id):
            bot.answer_callback_query(call.id,
                                      "У вас уже есть активная подписка. Используйте продление во вкладке 'Мои Подписки'.")
            return

        if user_states[user_id]["in_process"]:
            bot.answer_callback_query(call.id, "Пожалуйста, подождите, пока предыдущая проверка не завершится.")
            return

        user_states[user_id]["in_process"] = True

        # Берём сумму для текущего платежа
        amount = user_payments.get(user_id, {}).get('amount')
        if not amount:
            months = 1 if payment_type == "extend_1m" else 3 if payment_type == "extend_3m" else 1
            amount = generate_unique_amount(user_id, months)

        add_to_queue(user_id, amount, message)

def check_login_with_retry(user_id, login, password, max_retries=5, delay=3):
    """
    Проверка логина с повторной попыткой при ошибке.
    max_retries - количество попыток
    delay - задержка между попытками в секундах
    """
    attempt = 0
    while attempt < max_retries:
        attempt += 1
        try:
            bot.send_message(user_id, "⏳ Идет проверка корректности логина и пароля...")
            if check_login(login, password):
                user_states[user_id]['step'] = 'await_name'
                bot.send_message(
                    user_id,
                    "✅ *Логин и пароль подтверждены!*\n\nТеперь введите ваше имя:",
                    parse_mode="Markdown"
                )
                return True
            else:
                user_states[user_id]['step'] = 'await_login'
                bot.send_message(
                    user_id,
                    "❌ *Логин или пароль неверны!*\nПопробуйте ещё раз.\nВведите логин:",
                    parse_mode="Markdown"
                )
                return False
        except Exception as e:
            bot.send_message(user_id, f"❌ Произошла ошибка при проверке логина:\nПовтор через {delay} секунд...")
            time.sleep(delay)
    bot.send_message(user_id, "⚠️ Проверка логина не удалась после нескольких попыток. Напишите в поддержку.")
    return False
# --- Обработка ввода данных ---
@bot.message_handler(func=lambda message: True)
def handle_credentials(message):
    user_id = message.chat.id
    if user_id not in user_states or 'step' not in user_states[user_id]:
        return

    step = user_states[user_id]['step']

    if step == 'await_login':
        ensure_user_state(user_id)
        user_states[user_id]['credentials']['login'] = message.text
        user_states[user_id]['step'] = 'await_password'
        bot.send_message(
            user_id,
            "🔑 *Логин сохранён!*\n\nТеперь введите, пожалуйста, свой *пароль* для входа на сайт:",
            parse_mode="Markdown"
        )

    elif step == 'await_password':
        ensure_user_state(user_id)
        user_states[user_id]['credentials']['password'] = message.text
        login = user_states[user_id]['credentials']['login']
        password = user_states[user_id]['credentials']['password']

        # Проверяем логин сразу
        if check_login(login, password):
            user_states[user_id]['step'] = 'await_name'
            bot.send_message(
                user_id,
                "✅ *Логин и пароль подтверждены!*\n\nТеперь введите ваше имя:",
                parse_mode="Markdown"
            )
        else:
            user_states[user_id]['step'] = 'await_login'
            bot.send_message(
                user_id,
                "❌ *Логин или пароль неверны!*\nПопробуйте ещё раз.\nВведите логин:",
                parse_mode="Markdown"
            )

    elif step == 'await_name':
        user_states[user_id]['name'] = message.text.strip()
        user_states[user_id]['step'] = 'await_city'
        bot.send_message(
            user_id,
            "✨ Отлично!\nТеперь введите *ваш город*:",
            parse_mode="Markdown"
        )

    elif step == 'await_city':
        user_states[user_id]['city'] = message.text.strip()
        user_states[user_id]['step'] = 'await_time'
        bot.send_message(
            user_id,
            "🕒 Выберите *время по МСК*, когда будет выполняться тест:",
            parse_mode="Markdown",
            reply_markup=create_time_buttons()
        )

    elif step == 'await_time':
        user_states[user_id]['time'] = message.text.strip()
        user_states[user_id]['step'] = 'await_position'
        user_states[user_id]['position_page'] = 0  # первая страница
        bot.send_message(
            user_id,
            "📋 Выберите *ваш должностной тест*, который нужно проходить ежедневно:",
            parse_mode="Markdown",
            reply_markup=create_position_buttons_page(0)
        )

# --- Обработка кнопок для времени ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("time_"))
def handle_time_selection(call):
    user_id = call.message.chat.id
    time_selected = call.data.split("_")[1]
    user_states[user_id]['time'] = time_selected
    user_states[user_id]['step'] = 'await_position'
    user_states[user_id]['position_page'] = 0  # первая страница
    bot.edit_message_text(
        f"🕒 Вы выбрали время: {time_selected}\n📋 Выберите *ваш должностной тест*, который нужно проходить ежедневно:",
        call.message.chat.id,
        call.message.message_id,
        parse_mode="Markdown",
        reply_markup=create_position_buttons_page(0)
    )
# --- Обработка кнопок для должностей ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("position_"))
def handle_position(call):
    user_id = call.message.chat.id
    data = call.data

    if data.startswith("position_page_"):  # листание страниц
        page = int(data.split("_")[-1])
        user_states[user_id]['position_page'] = page
        bot.edit_message_text(
            "📋 Выберите вашу должность:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=create_position_buttons_page(page)
        )
        return

    elif data == "back_from_positions":  # отмена выбора
        user_states[user_id]['step'] = 'await_time'
        bot.edit_message_text(
            "🕒 Выберите *время по МСК*, когда будет выполняться тест:",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=create_time_buttons()  # <-- показываем кнопки выбора времени
        )
        return

    # выбор должности
    idx = int(data.split("_")[-1])
    position = positions_list[idx]
    user_states[user_id]['position'] = position
    user_states[user_id]['step'] = None

    # Сохраняем покупку с должностным тестом
    test_type = user_states[user_id].get('current_test', 'Ежедневное тестирование')
    start_date = datetime.today()
    end_date = start_date + timedelta(days=30)
    purchase = {
        "test_name": test_type,
        "position": position,  # <-- сохраняем должность
        "start_date": start_date,
        "end_date": end_date
    }
    if user_id not in user_purchases:
        user_purchases[user_id] = []
    user_purchases[user_id].append(purchase)
    save_purchases()
    save_user_to_gsheet(user_id)

    # Сразу редактируем сообщение — кнопки исчезают, добавляем главное меню
    bot.edit_message_text(
        f"✅ *Данные успешно сохранены!*\n\n"
        f"👤 *Имя:* {user_states[user_id]['name']}\n"
        f"🏙 *Город:* {user_states[user_id]['city']}\n"
        f"🕒 *Время теста:* {user_states[user_id]['time']}\n"
        f"💼 *Должность:* {position}\n\n"
        f"📌 С завтрашнего дня начнется ежедневное тестирование!",
        chat_id=user_id,
        message_id=call.message.message_id,
        parse_mode="Markdown",
        reply_markup=create_main_inline_buttons()
    )

def save_user_to_gsheet(user_id, extend=False, new_end_date=None):
    """
    Сохраняет или обновляет данные пользователя в Google Sheets
    extend=True → продление подписки
    """
    if user_id not in user_states:
        return

    user = user_states[user_id]
    creds_data = user.get('credentials', {})
    name = user.get('name', '')
    login = creds_data.get('login', '')
    password = creds_data.get('password', '')
    city = user.get('city', '')
    position = user.get('position', '')
    test_time = user.get('time', '')

    if extend and new_end_date:
        # --- ищем пользователя в таблице по TG_ID (колонка K) ---
        tg_id_list = USERS_SHEET.col_values(11)  # колонка K = 11
        if str(user_id) in tg_id_list:
            row_index = tg_id_list.index(str(user_id)) + 1  # номер строки
            USERS_SHEET.update_cell(row_index, 6, new_end_date.strftime("%d.%m.%Y"))  # колонка F
            USERS_SHEET.update_cell(row_index, 7, "Активный")  # колонка G
            return
        else:
            # если вдруг не нашли — создаём новую строку
            pass

    # --- новая подписка ---
    start_date = datetime.today()
    end_date = start_date + timedelta(days=30)
    status = "Активный"

    USERS_SHEET.append_row([
        name,                # A - Имя
        "",                  # B - пусто
        login,               # C - Логин
        password,            # D - Пароль
        start_date.strftime("%d.%m.%Y"),  # E - Дата приобретения
        end_date.strftime("%d.%m.%Y"),    # F - Дата окончания
        status,              # G - Статус подписки
        position,            # H - Должность теста
        test_time,           # I - Во сколько проходить
        city,                # J - Город
        str(user_id)         # K - TG_ID
    ])
def create_position_buttons_page(page=0):
    markup = types.InlineKeyboardMarkup()
    start = page * POSITIONS_PER_PAGE
    end = start + POSITIONS_PER_PAGE
    for idx, position in enumerate(positions_list[start:end], start=start):
        markup.add(types.InlineKeyboardButton(position, callback_data=f"position_{idx}"))

    nav_buttons = []
    if page > 0:  # есть предыдущая страница
        nav_buttons.append(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"position_page_{page-1}"))
    if end < len(positions_list):  # есть следующая страница
        nav_buttons.append(types.InlineKeyboardButton("Далее ➡️", callback_data=f"position_page_{page+1}"))

    if nav_buttons:
        markup.row(*nav_buttons)


    return markup

# --- Callback-обработчик для всех кнопок ---
@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    # --- фильтр, чтобы этот хендлер не трогал оплату и прочие спец.кнопки ---
    if call.data in ["pay", "pay_done", "extend_1m", "extend_3m", "back_from_payment"]:
        return
    if call.data.startswith("time_") or call.data.startswith("position_"):
        return

    chat_id = call.message.chat.id
    message_id = call.message.message_id


    if call.data == "test_choice":
        user_states[chat_id] = {"in_process": False, "current_message": "test_choice"}
        bot.edit_message_text(
            "📌Выберите тип теста для прохождения:\n\n"
            "👉Рекомендую сначала ознакомится с каждым из типов тестов во вкладке *Что умеет бот*\n\n",

            chat_id, message_id, parse_mode="Markdown", reply_markup=create_test_choice_inline_buttons())
    elif call.data == "bot_info":
        user_states[chat_id] = "bot_info"
        bot.edit_message_text(
            "📌 *Что умеет бот?*\n\n"
            "🤖 Бот предоставляет услуги по прохождению тестирования:\n\n"
            "🔹 *Предэкзаменационная подготовка (ПЭП-тест)*  \n"
            "🌐 Сайт: edu.sibkeu\n\n"
            "🔹 *Ежедневная проверка знаний (охрана труда)*  \n"
            "🌐 Сайт: learn.rosseti\n\n"
            "💳 *Как происходит покупка услуги?*\n"
            "▫️ Выбираете тип теста (например, ПЭП-тест или ежедневное тестирование).\n"
            "▫️ Следуете инструкциям. \n"
            "▫️ Передаёте необходимые данные (логин, пароль и т.п.).\n"
            "▫️ После оплаты вас добавляют в списки, и вы получаете уведомление о статусе.\n\n"
            "✅ Когда тестирование будет выполнено, вам придёт уведомление, и вы сможете проверить результат на сайте.\n\n"
            "ℹ️ *Дополнительно:* Чтобы узнать подробности, выберите интересующий вас тип теста ниже 👇",
            chat_id, message_id,
            parse_mode="Markdown",
            reply_markup=create_bot_info_inline_buttons()
        )
    elif call.data == "back_to_tests":
        bot.edit_message_text(
            "📌Выберите тип теста для прохождения:\n\n"
            "👉Рекомендую сначала ознакомиться с каждым из типов тестов во вкладке *Что умеет бот*\n\n",
            chat_id, message_id,
            parse_mode="Markdown",
            reply_markup=create_test_choice_inline_buttons()
        )
    elif call.data == "purchases":
        if chat_id not in user_purchases or not user_purchases[chat_id]:
            bot.edit_message_text(
                "📭 *У вас пока нет активных подписок.*",
                chat_id, message_id,
                parse_mode="Markdown",
                reply_markup=create_main_inline_buttons()
            )
            return

        p = user_purchases[chat_id][0]  # берем единственную подписку
        test_name = p['test_name']
        position = p.get('position', 'Не выбран')
        start = p['start_date'].strftime("%d.%m.%Y")
        end = p['end_date'].strftime("%d.%m.%Y")
        status = "✅ Активная" if datetime.today() <= p['end_date'] else "⛔ Просрочена"

        text = (
            "🛒 *Ваша подписка:*\n\n"
            f"*Тест:* {test_name}\n"
            f"📌 *Должность:* `{position}`\n"
            f"⏳ *Период:* {start} – {end}\n"
            f"📊 *Статус:* {status}\n\n"
            "Хотите продлить подписку? 🔄"
        )

        bot.edit_message_text(
            text,
            chat_id, message_id,
            parse_mode="Markdown",
            reply_markup=create_purchases_buttons()
        )


    elif call.data.startswith("extend_"):
        months = 1 if call.data == "extend_1m" else 3
        amount = generate_unique_amount(chat_id, months)
        # сохраняем тип операции
        user_states[chat_id] = {"in_process": False, "payment_type": call.data}
        payment_message = (
            f"💳 Для продления подписки на *{months} мес.* "
            f"переведите *{amount}₽* на карту: `2202 2016 0199 5356`\n\n"
            "⚠️ Важно: сумма должна совпадать *вплоть до копейки*!\n\n"
            "После оплаты нажмите «Я оплатил»."
        )

        bot.edit_message_text(
            payment_message,
            chat_id, message_id,
            parse_mode="Markdown",
            reply_markup=create_payment_inline_buttons()

        )


    elif call.data == "back_to_main":
        bot.edit_message_text(
            "👋 *Добро пожаловать!*\n\n"
            "Этот бот поможет вам с прохождением тестов:\n"
            "🔹 *Предэкзаменационная подготовка (ПЭП-тест)*\n"
            "🔹 *Ежедневная проверка знаний (охрана труда)*\n\n"
            "📌 Выберите нужный раздел ниже, чтобы узнать подробнее или оформить услугу 👇",
            chat_id, message_id,
            parse_mode="Markdown",
            reply_markup=create_main_inline_buttons()
        )

    elif call.data == "pep_info":
        bot.edit_message_text(
            "📌 *Подробная информация о прохождении ПЭП-теста*\n\n"
            "❓ *Каким образом происходит выполнение и оплата услуги?*\n"
            "👉 Покупка услуги происходит напрямую. При выборе теста *«ПЭП-тест»* вас переведет на диалог с менеджером.\n\n"
            "💰 Цена услуги зависит от должности (*от 1000 до 2000₽*). В самом низу приведён список должностей и их цена. "
            "Если вашей должности нет — цена будет назначена после осмотра вашего аккаунта.\n\n"
            "📋 В диалоге вы должны указать:\n"
            "▫️ Свою должность\n"
            "▫️ Имя\n"
            "▫️ Город\n\n"
            "⏳ В течение часа вам ответят и назначат цену. Если вас всё устраивает, вы присылаете свой *логин и пароль*, "
            "после чего начнется выполнение.\n\n"
            "💳 Оплата производится *только после полного прохождения ПЭП-теста*, когда вы убедитесь в результате.\n\n"
            "⏱ *В течение какого времени будет выполнен ПЭП-тест?*\n"
            "▫️ Обычно: от *1 до 3 дней* (по очереди)\n"
            "▫️ Срочно: в течение *одного дня* и *вне очереди*\n\n"
            "📊 *На какую оценку будут пройдены тесты?*\n"
            "▫️ Входной и итоговый контроль: от *4.00 до 5.00*\n"
            "▫️ Обычные тесты: всегда на *5*\n"
            "▫️ Индивидуальные должностные тесты (наряд-допуск, СИП, ЛЭП и т.д.): от *4 до 5* "
            "(в редких случаях — минимальный проходной балл)\n\n"
            "❓ *Почему у разных должностей разная цена?*\n"
            "Цена зависит от:\n"
            "▫️ Количества вопросов на курсе (от *1000 до 2500*)\n"
            "▫️ Сложности входного и итогового контроля\n"
            "▫️ Сложности индивидуальных тестов\n\n"
            "💵 *Стоимость услуг:*\n"
            "🔹 1000₽ — Электромонтёры (все разряды), Электромонтажники (все разряды), Операторы\n"
            "🔹 1500₽ — Мастера, Диспетчеры\n"
            "🔹 Для остальных должностей — цена определяется индивидуально (*1000–2000₽*).",
            chat_id, message_id,
            parse_mode="Markdown",
            reply_markup=create_bot_info_inline_buttons()
        )
    elif call.data == "daily_test_info":
        bot.edit_message_text(
            "📌 *Ежедневное тестирование* выполняется в формате _подписки_.\n\n"
            "💳 Стоимость: *300₽ / месяц*.\n\n"
            "🗓 В течение этого времени:\n"
            "▫️ Каждый день за вас будет проходиться тестирование по охране труда.\n"
            "▫️ Это происходит *ежедневно*, независимо от дня недели.\n"
            "▫️ Вы можете указать удобное время выполнения теста (по МСК).\n\n"
            "📊 *Результаты тестов*: от *80* до *100 баллов*.\n\n"
            "🔔 После каждого выполнения теста на сайте вы будете получать уведомление прямо в Telegram.\n\n"
            "📂 Во вкладке *«Мои услуги»* можно будет посмотреть, сколько еще длится подписка.",
            chat_id, message_id,
            parse_mode="Markdown",
            reply_markup=create_bot_info_inline_buttons()
        )
    elif call.data == "back_from_bot_info":
        bot.edit_message_text(
            "👋 *Добро пожаловать!*\n\n"
            "Этот бот поможет вам с прохождением тестов:\n"
            "🔹 *Предэкзаменационная подготовка (ПЭП-тест)*\n"
            "🔹 *Ежедневная проверка знаний (охрана труда)*\n\n"
            "📌 Выберите нужный раздел ниже, чтобы узнать подробнее или оформить услугу 👇",
            chat_id, message_id,
            parse_mode="Markdown",
            reply_markup=create_main_inline_buttons()
        )

    elif call.data == "back_from_test_choice":
        bot.edit_message_text(
            "👋 *Добро пожаловать!*\n\n"
            "Этот бот поможет вам с прохождением тестов:\n"
            "🔹 *Предэкзаменационная подготовка (ПЭП-тест)*\n"
            "🔹 *Ежедневная проверка знаний (охрана труда)*\n\n"
            "📌 Выберите нужный раздел ниже, чтобы узнать подробнее или оформить услугу 👇",
            chat_id, message_id,
            parse_mode="Markdown",
            reply_markup=create_main_inline_buttons()
        )
    elif call.data == "pep_test":
        markup = types.InlineKeyboardMarkup(row_width=1)
        support_button = types.InlineKeyboardButton(
            "Связаться с менеджером", url="https://t.me/face2ren"
        )
        back_button = types.InlineKeyboardButton(
            "⬅️ Назад", callback_data="back_to_tests"
        )
        markup.add(support_button, back_button)

        bot.edit_message_text(
            "📋 *В диалоге вы должны указать:*\n"
            "▫️ Имя\n"
            "▫️ Свою должность\n"
            "▫️ Город\n\n"
            "💬 Нажмите кнопку ниже, чтобы перейти в чат с менеджером.",
            chat_id, message_id, parse_mode="Markdown", reply_markup=markup
    )
    elif call.data.startswith("extend_"):
        if call.data == "extend_1m":
            user_states[chat_id]['payment_type'] = 'extend_1m'
        else:
            user_states[chat_id]['payment_type'] = 'extend_3m'

    elif call.data == "daily_test":
        if chat_id not in user_states:
            user_states[chat_id] = {}
        user_states[chat_id]['payment_type'] = 'new'

        # Проверяем, есть ли уже активная подписка
        if has_active_subscription(chat_id, test_type="Ежедневное тестирование"):
            # Кнопка заблокирована
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("Оплата недоступна — активная подписка", callback_data="pay_disabled"))
            markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back_from_payment"))
            bot.edit_message_text(
                "💳 У вас уже активна подписка на ежедневное тестирование.\n"
                "Используйте продление во вкладке 'Мои Подписки'.",
                chat_id, message_id,
                parse_mode="Markdown",
                reply_markup=markup
            )
        else:
            # Если подписки нет — обычная кнопка Оплатить
            bot.edit_message_text(
                "💳 Ежедневное тестирование оплачивается в формате подписки.\n💵 Стоимость: *300₽ / месяц*.\n\n🗓 Нажмите 'Оплатить', чтобы продолжить.",
                chat_id, message_id, parse_mode="Markdown", reply_markup=create_payment_inline_buttons()
            )


    elif call.data == "back_from_payment":
        bot.edit_message_text(
            "📌Выберите тип теста для прохождения:\n\n"
            "👉Рекомендую сначала ознакомится с каждым из типов тестов во вкладке *Что умеет бот*\n\n",
            chat_id, message_id, parse_mode="Markdown", reply_markup=create_test_choice_inline_buttons())

# --- Запуск бота ---
bot.polling(none_stop=True)
