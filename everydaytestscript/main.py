import openpyxl
from openpyxl import load_workbook, Workbook
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException, ElementClickInterceptedException, ElementNotInteractableException, WebDriverException, NoSuchElementException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from webdriver_manager.chrome import ChromeDriverManager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials
import threading
import csv
import time
import re
import sys

sys.path.append(r"C:\Users\MarderFar\PycharmProjects\notificationsTelegram")
from notification import send_telegram_report
# ---------- Настройки Chrome ----------
options = Options()
#options.add_argument("--headless=new")   # скрытый режим (важно: new для свежих версий Chrome)
#options.add_argument("--no-sandbox")
#options.add_argument("--disable-dev-shm-usage")
#options.add_argument("--disable-gpu")
#options.add_argument("--window-size=1920,1080")

options.binary_location = r"C:\Users\MarderFar\Desktop\chrome-win64\chrome.exe"
options.add_argument("--disable-backgrounding-occluded-windows")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
SERVICE_ACCOUNT_FILE = r"C:\Users\MarderFar\Desktop\Work\everydayscript-86548f80b016.json"  # путь к JSON

creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
gc = gspread.authorize(creds)


USERS_SHEET = gc.open("UsersEvery").sheet1
REPORTS_SHEET = gc.open("ReportsEvery").sheet1
ANSWERS_SHEET = gc.open("Answers").sheet1
# ---------- Загрузка пользователей ----------

def smart_split_tests(tests_raw: str):
    """Разбивает строку с тестами, игнорируя запятые внутри кавычек"""
    if not tests_raw:
        return []

    # Нормализуем кавычки
    s = tests_raw.replace("«", "\"").replace("»", "\"") \
        .replace("“", "\"").replace("”", "\"") \
        .replace("„", "\"").replace("‟", "\"")

    # Регулярка: делим по запятым, которые не внутри кавычек
    parts = re.split(r',(?=(?:[^"]*"[^"]*")*[^"]*$)', s)
    # Убираем кавычки и пробелы
    cleaned = [p.strip().strip('"').strip() for p in parts if p.strip()]
    return cleaned
def load_users_from_gsheet():
    users_data = USERS_SHEET.get_all_values()[1:]
    users = []
    now = datetime.now()
    time_window = timedelta(hours=2)

    print(f"🕛 Текущее время запуска: {now.strftime('%H:%M')} (окно ±2 часа)")

    for row in users_data:
        login = row[2] if len(row) > 2 else ""
        password = row[3] if len(row) > 3 else ""
        subscription_until = row[5] if len(row) > 5 else ""
        test_time = row[8].strip() if len(row) > 8 else ""
        tests_raw = row[7] if len(row) > 7 else ""
        telegram_id = row[10] if len(row) > 10 else ""

        # Проверка подписки
        active_subscription = False
        if subscription_until:
            for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
                try:
                    expiry = datetime.strptime(subscription_until.strip(), fmt)
                    if expiry >= now:
                        active_subscription = True
                    break
                except ValueError:
                    continue

        # Проверка времени
        correct_time = False
        if test_time:
            for fmt in ("%H:%M", "%H.%M"):
                try:
                    scheduled = datetime.strptime(test_time, fmt).replace(
                        year=now.year, month=now.month, day=now.day
                    )
                    if abs((scheduled - now)) <= time_window:
                        correct_time = True
                    break
                except ValueError:
                    continue

        # Форматирование списка тестов
        if login and password and tests_raw and active_subscription and correct_time:
            def smart_split_tests(tests_raw: str):
                """Разбивает строку с тестами, игнорируя запятые внутри кавычек"""
                if not tests_raw:
                    return []
                s = tests_raw.replace("«", "\"").replace("»", "\"") \
                    .replace("“", "\"").replace("”", "\"") \
                    .replace("„", "\"").replace("‟", "\"")
                parts = re.split(r',(?=(?:[^"]*"[^"]*")*[^"]*$)', s)
                cleaned = [p.strip().strip('"').strip() for p in parts if p.strip()]
                return cleaned

            tests = smart_split_tests(tests_raw)
            users.append((login, password, tests, telegram_id))

    print(f"✅ Пользователей с активной подпиской и временем в пределах 2 часов: {len(users)}")
    return users

# ---------- Отчёты ----------
def write_report(username, password, test_name, score, status, telegram_id=None):
    """
      Записывает отчёт в Google Sheets.
      Отправляет уведомление только если:
        - оценка = 80 или 100,
        - статус не содержит "недостаточно ответов" или "пройден заранее".
      """
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # --- Запись в Google Sheets ---
    try:
        REPORTS_SHEET.append_row(["", "", username, password, date_str, test_name, score, status, telegram_id])
        print(f"📄 Отчёт записан: {username} - {test_name} - {status} ({score})")
    except Exception as e:
        print(f"❌ Ошибка при записи отчёта: {e}")

    # --- Проверка необходимости уведомления ---
    if not telegram_id:
        return

    try:
        # Извлекаем числовое значение оценки (например "80 / 100" -> 80)
        score_num = None
        if isinstance(score, str):
            match = re.search(r'(\d+)', score)
            if match:
                score_num = int(match.group(1))
        elif isinstance(score, (int, float)):
            score_num = int(score)

        # Приводим статус к нижнему регистру для надёжного сравнения
        status_lower = status.lower() if isinstance(status, str) else ""

        # Проверяем все условия
        if (
                score_num in (80, 100)
                and "недостаточно ответов" not in status_lower
                and "пройден заранее" not in status_lower
        ):
            # Отправляем уведомление в отдельном потоке
            def send_notification():
                try:
                    send_telegram_report(telegram_id, test_name, score, status)
                except Exception as e:
                    print(f"❌ Ошибка при отправке уведомления: {e}")

            threading.Thread(target=send_notification, daemon=True).start()
            print(f"📨 Уведомление отправлено ({score_num}%) пользователю {username}")

        else:
            print(f"🚫 Уведомление не отправлено: {username} ({score}, {status})")

    except Exception as e:
        print(f"⚠️ Ошибка при обработке уведомления: {e}")


# ---------- Получение правильных ответов ----------
def get_correct_answers_by_number(question_number):
    """
    Возвращает список правильных ответов для вопроса question_number из Google Sheets.
    Игнорирует строки с пустыми или нечисловыми номерами.
    """
    all_rows = ANSWERS_SHEET.get_all_values()[1:]  # пропускаем заголовок
    correct_answers = []

    for row in all_rows:
        try:
            # Проверяем, что первый столбец — число
            num_str = str(row[0]).strip()
            if not num_str.isdigit():
                continue  # пропускаем строки вроде 'б/н', пустые и т.д.
            excel_question_number = int(num_str)

            # Берём текст ответа и маркер
            answer_text = row[2].strip() if len(row) > 2 else ""
            correct_marker = row[3].strip() if len(row) > 3 else ""

            if excel_question_number == question_number and correct_marker == "1" and answer_text:
                correct_answers.append(answer_text)

        except Exception as e:
            print(f"[DEBUG] Ошибка при обработке строки: {row} -> {e}")
            continue

    return correct_answers



# ---------- Вспомогательные функции ----------
def _norm(s: str) -> str:
    s = (s or "").replace('\xa0', ' ')
    s = re.sub(r'\s+', ' ', s).strip()
    s = re.sub(r'^[A-Za-zА-Яа-я]\.\s*', '', s)
    return s.lower()

def click_element(driver, elem):
    try:
        if not elem.is_displayed():
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", elem)
            time.sleep(0.15)
    except Exception:
        pass
    try:
        elem.click()
        return True
    except (ElementClickInterceptedException, ElementNotInteractableException, StaleElementReferenceException):
        try:
            ActionChains(driver).move_to_element_with_offset(elem, 5, 5).click().perform()
            return True
        except Exception:
            try:
                driver.execute_script("arguments[0].click();", elem)
                return True
            except Exception:
                try:
                    driver.execute_script("arguments[0].form && arguments[0].form.submit();", elem)
                    return True
                except Exception:
                    return False

def _click_input_with_fallback(driver, input_elem, label_elem=None):
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", input_elem)
    time.sleep(0.15)
    try:
        if not input_elem.is_selected():
            input_elem.click()
    except Exception:
        try:
            driver.execute_script("arguments[0].click();", input_elem)
        except Exception:
            if label_elem:
                try:
                    driver.execute_script("arguments[0].click();", label_elem)
                except Exception:
                    pass
    return input_elem.is_selected()

def is_summary_page(driver):
    saved_answers = len(driver.find_elements(By.XPATH, "//td[contains(text(),'Ответ сохранен')]"))
    if saved_answers:
        try:
            WebDriverWait(driver, 2).until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.quizsummaryofattempt")))
            return True
        except TimeoutException:
            return False

def finalize_attempt(driver):
    try:
        submit_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[@type='submit' and contains(text(), 'Отправить всё и завершить тест')]"))
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", submit_button)
        time.sleep(0.3)
        submit_button.click()
    except TimeoutException:
        return False
    try:
        modal_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "div.modal-content button.btn.btn-primary[data-action='save']"))
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", modal_button)
        time.sleep(0.3)
        modal_button.click()
        return True
    except TimeoutException:
        return False

def process_results_page(driver, username):
    try:
        test_title = driver.find_element(By.CSS_SELECTOR, "div.page-header-headings h1").text.strip()
    except Exception:
        test_title = "Неизвестный тест"
    saved_answers = len(driver.find_elements(By.XPATH, "//td[contains(text(),'Ответ сохранен')]"))
    no_answers = len(driver.find_elements(By.XPATH, "//td[contains(text(),'Пока нет ответа')]"))
    print(f"📘 Тест: {test_title}\nКоличество 'Ответ сохранен': {saved_answers}\nКоличество 'Пока нет ответа': {no_answers}")

def analyze_global_results(driver, username):
    try:
        score_td = WebDriverWait(driver, 15).until(
            EC.visibility_of_element_located((By.XPATH, "//tr[th[contains(text(),'Оценка')]]/td"))
        )
        score = score_td.text.strip()
    except TimeoutException:
        score = "Нет данных"
    print(f"Оценка: {score}")
    return score

def watchdog(driver, stop_event, username):
    while not stop_event.is_set():
        try:
            driver.title
        except WebDriverException:
            print(f"[WATCHDOG] {username}: браузер завис или закрылся! Перезапуск...")
            stop_event.set()
            break
        time.sleep(5)

def session_watchdog(driver, username, password, max_attempts=5):
    attempt = 0
    while attempt < max_attempts:
        try:
            username_field = WebDriverWait(driver, 2).until(EC.presence_of_element_located((By.ID, "username")))
            password_field = driver.find_element(By.ID, "password")
            login_button = driver.find_element(By.ID, "loginbtn")
            username_field.clear()
            username_field.send_keys(username)
            password_field.clear()
            password_field.send_keys(password)
            for _ in range(3):
                try:
                    login_button.click()
                    break
                except StaleElementReferenceException:
                    login_button = driver.find_element(By.ID, "loginbtn")
                    time.sleep(0.2)
            print(f"[INFO] Повторная авторизация выполнена (попытка {attempt+1})")
            time.sleep(2)
        except TimeoutException:
            print("[INFO] Авторизация успешна, продолжаем тест")
            return True
        except Exception as e:
            print(f"[WATCHDOG ERROR] {e}")
        attempt += 1
        time.sleep(2)
    print("[ERROR] Не удалось авторизоваться после нескольких попыток")
    return False

# ---------- Запуск теста ----------
def run_test(username, password, tests, telegram_id):
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    stop_event = threading.Event()
    threading.Thread(target=watchdog, args=(driver, stop_event, username), daemon=True).start()
    threading.Thread(target=session_watchdog, args=(driver, username, password), daemon=True).start()

    try:
        driver.get("https://learn.rosseti-sib.ru/login/index.php")
        username_field = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "username")))
        password_field = driver.find_element(By.ID, "password")
        login_button = driver.find_element(By.ID, "loginbtn")
        username_field.send_keys(username)
        password_field.send_keys(password)
        login_button.click()
        print(f"Logged in as: {username}")

        daily_check_button = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.LINK_TEXT, "Ежедневная проверка знаний."))
        )
        daily_check_button.click()

        for test_name in tests:
            try:
                test_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, f"//div[@data-activityname='{test_name}']//a[contains(@class, 'aalink')]"))
                )
                test_button.click()
            except TimeoutException:
                print(f"Не найден тест '{test_name}'")
                continue

            # --- START TEST LOGIC ---
            start_candidates = [
                "//form[contains(@action,'/mod/quiz/startattempt.php')]//button[@type='submit' and contains(@class,'btn-primary')]",
                "//button[contains(@class,'btn-primary') and (contains(.,'Продолжить текущую попытку') or contains(.,'Продолжить попытку') or contains(.,'Продолжить тест') or contains(.,'Пройти тест') or contains(.,'Попытка теста') or contains(.,'Начать попытку') or contains(.,'Начать'))]",
                "//a[contains(@class,'btn btn-primary') and (contains(.,'Продолжить') or contains(.,'Пройти') or contains(.,'Начать'))]"
            ]
            clicked_start = False
            for xp in start_candidates:
                try:
                    elems = WebDriverWait(driver, 2).until(EC.presence_of_all_elements_located((By.XPATH, xp)))
                except TimeoutException:
                    elems = []
                for el in elems:
                    try:
                        if el.is_displayed() and click_element(driver, el):
                            clicked_start = True
                            break
                    except Exception:
                        continue
                if clicked_start:
                    break

            if not clicked_start:
                try:
                    return_btn = WebDriverWait(driver, 3).until(
                        EC.element_to_be_clickable((By.XPATH, "//div[contains(@class,'continuebutton')]//button"))
                    )
                    print(f"📘 Тест '{test_name}' уже пройден. Создаём отчёт.")
                    try:
                        test_title = driver.find_element(By.CSS_SELECTOR, "div.page-header-headings h1").text.strip()
                    except Exception:
                        test_title = test_name
                    write_report(username, password, test_title, "---", "Пройден заранее", telegram_id)
                    click_element(driver, return_btn)
                    time.sleep(1.5)
                    continue
                except TimeoutException:
                    print(f"❌ Не найдена кнопка старта или 'Вернуться к курсу'.")
                    driver.get("https://learn.rosseti-sib.ru/course/view.php?id=55")
                    time.sleep(1.5)
                    continue

            # --- QUESTION LOGIC ---
            try:
                while True:
                    try:
                        WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.ID, "responseform")))
                    except TimeoutException:
                        print("Форма ответа не найдена. Прерываем тест.")
                        break

                    question_elements = driver.find_elements(By.CSS_SELECTOR, "div.que")
                    if not question_elements:
                        break

                    for idx in range(len(question_elements)):
                        for attempt in range(3):
                            try:
                                question_element = driver.find_elements(By.CSS_SELECTOR, "div.que")[idx]
                                question_text = question_element.find_element(By.CSS_SELECTOR, "div.qtext").text
                                m = re.match(r"\s*(\d+)\.", question_text)
                                if not m:
                                    raise ValueError(f"Не удалось распарсить номер из: {question_text}")
                                question_number = int(m.group(1))
                                correct_answers = get_correct_answers_by_number(question_number)
                                if not correct_answers:
                                    print(f"Вопрос {question_number} отсутствует в Excel")
                                    break

                                labels = question_element.find_elements(By.XPATH, ".//div[@data-region='answer-label']")
                                label_to_input = {}
                                for lbl in labels:
                                    try:
                                        lid = lbl.get_attribute("id") or ""
                                        if lid:
                                            iid = lid.replace("_label", "")
                                            inp = question_element.find_element(By.ID, iid)
                                        else:
                                            parent = lbl.find_element(By.XPATH,
                                                                      "./ancestor::div[contains(@class,'r0') or contains(@class,'r1')]")
                                            inp = parent.find_element(By.TAG_NAME, "input")
                                        label_to_input[lbl] = inp
                                    except Exception:
                                        pass

                                for correct_answer in correct_answers:
                                    target = _norm(correct_answer)
                                    found = False
                                    for lbl, inp in label_to_input.items():
                                        text = _norm(lbl.text)
                                        if text == target:
                                            _click_input_with_fallback(driver, inp, lbl)
                                            found = True
                                            print(f"✅ Выбран ответ: {correct_answer} (Вопрос {question_number})")
                                            break
                                    if not found:
                                        print(f"❌ Не найден ответ '{correct_answer}' в вопросе {question_number}")
                                break
                            except StaleElementReferenceException:
                                time.sleep(0.3)
                                continue
                            except Exception as e:
                                print(f"Ошибка при обработке вопроса: {e}")
                                break

                    try:
                        next_button = WebDriverWait(driver, 5).until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, "input.mod_quiz-next-nav.btn.btn-primary"))
                        )
                        click_element(driver, next_button)
                        time.sleep(0.5)
                    except TimeoutException:
                        print("Кнопка 'Далее' не найдена. Тест, возможно, завершён.")
                        break

                    if is_summary_page(driver):
                        break

                # --- RESULTS PROCESSING ---
                saved_answers = len(driver.find_elements(By.XPATH, "//td[contains(text(),'Ответ сохранен')]"))
                try:
                    test_title = driver.find_element(By.CSS_SELECTOR, "div.page-header-headings h1").text.strip()
                except Exception:
                    test_title = test_name

                if saved_answers >= 5:
                    if finalize_attempt(driver):
                        score = analyze_global_results(driver, username)
                        status = "Успешно" if score != "Нет данных" else "Неудачно"
                        write_report(username, password, test_title, score, status, telegram_id)
                    else:
                        write_report(username, password, test_title, "---", "Не удалось отправить", telegram_id)
                else:
                    write_report(username, password, test_title, "---", "Недостаточно ответов", telegram_id)

            except Exception as e:
                print(f"[ERROR] Ошибка во время теста: {e}")
                write_report(username, password, test_name, "---", "Ошибка во время теста", telegram_id)
            time.sleep(5)
            driver.get("https://learn.rosseti-sib.ru/course/view.php?id=55")

    finally:
        stop_event.set()
        driver.quit()

# ---------- Главная функция ----------
def main():
    users = load_users_from_gsheet()
    if not users:
        print("⚠️ Нет пользователей для запуска: никто не соответствует условиям (время, подписка).")
        return

    with ThreadPoolExecutor(max_workers=min(5, len(users))) as executor:
        futures = [executor.submit(run_test, login, password, tests, telegram_id)
                   for login, password, tests, telegram_id in users]
        for future in futures:
            future.result()

if __name__ == "__main__":
    main()
