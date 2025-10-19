# sbercheck.py
import sys
import json
import os
import shutil
import time
import random
from pathlib import Path
from decimal import Decimal, InvalidOperation
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException, ElementClickInterceptedException, NoSuchElementException
import re

# ------------------ Настройки (подправь пути при необходимости) ------------------
SRC_USERDATA = Path(r"C:\Users\MarderFar\Desktop\chrome-win64")
SRC_PROFILES = [
    SRC_USERDATA / "Profile1",
    SRC_USERDATA / "Profile2",
    SRC_USERDATA / "Profile3",
    SRC_USERDATA / "Profile4",
    SRC_USERDATA / "Profile5",
]
# Папка, куда будут копироваться "работающие" профили (изолированные)
WORK_ROOT = Path(r"C:\Users\MarderFar\Desktop\chrome-profiles")
LOCK_DIR = WORK_ROOT / "locks"
CHROME_BINARY = r"C:\Users\MarderFar\Desktop\chrome-win64\chrome.exe"

# Создаём нужные каталоги
WORK_ROOT.mkdir(parents=True, exist_ok=True)
LOCK_DIR.mkdir(parents=True, exist_ok=True)

_amount_re = re.compile(
    r"([+\-−]?\s*\d{1,3}(?:[ \u00A0\u202F]\d{3})*(?:[.,]\d{1,2})?|\d+[.,]\d{1,2})",
    flags=re.IGNORECASE
)

_payment_keywords = ["перевод", "входящ", "зачисл", "пополн", "сбп", "по запросу", "перечислен", "приход"]


# ------------------ Утилиты для блокировки профиля ------------------
def try_acquire_lock(name: str):
    """
    Попытаться создать lock-файл atomically. Возвращает путь к lock-файлу, если удалось,
    иначе None.
    """
    lock_path = LOCK_DIR / f"{name}.lock"
    try:
        # режим 'x' — создаст файл, но упадёт, если уже существует
        with open(lock_path, "x"):
            pass
        return lock_path
    except FileExistsError:
        return None

def release_lock(lock_path: Path):
    try:
        lock_path.unlink()
    except Exception:
        pass

# ------------------ Подготовка рабочего профиля ------------------
def prepare_work_profile(src_profile: Path):
    """
    Возвращает tuple(work_profile_dir:Path, lock_path:Path)
    или (None, None) если занято / не удалось.
    """
    if not src_profile.exists():
        return None, None

    # имя профиля, без спецсимволов
    profile_name = src_profile.name.replace(" ", "_")
    work_profile = WORK_ROOT / profile_name

    # попробуем захватить lock (атоми́чно)
    lock = try_acquire_lock(profile_name)
    if lock is None:
        # профиль занят
        return None, None

    # Если рабочая папка не существует — копируем исходную
    try:
        if not work_profile.exists():
            # shutil.copytree может взять время и место на диске.
            print(f"Копируем профиль {src_profile} -> {work_profile} ...")
            shutil.copytree(src_profile, work_profile)
            print("Копирование завершено.")
        else:
            print(f"Рабочая папка {work_profile} уже существует — используем её.")
    except Exception as e:
        # при ошибке — освобождаем lock и возвращаем None
        print("Ошибка при копировании профиля:", e)
        release_lock(lock)
        return None, None

    return work_profile, lock

# ------------------ Класс автоматизации (твоя логика проверки) ------------------
class SberAutomation:
    def __init__(self, user_data_dir: str, chrome_binary: str):
        # user_data_dir здесь — полная отдельная папка для каждого окна
        self.user_data_dir = user_data_dir
        self.chrome_binary = chrome_binary

        self.options = Options()
        # обязательно использовать путь к отдельной папке
        self.options.add_argument(f"user-data-dir={str(self.user_data_dir)}")
        # уникальный порт для remote debugging (уменьшит конфликты)
        port = random.randint(10000, 20000)
        self.options.add_argument(f"--remote-debugging-port={port}")
        # дополнительные опции для стабильности
        self.options.add_argument("--no-sandbox")
        self.options.add_argument("--disable-dev-shm-usage")
        # если не хотите видеть окно — можно добавить "--headless=new" (но для авторизации визуально лучше не скрывать)
        # self.options.add_argument("--headless=new")

        # явно задаём бинарник Chrome
        self.options.binary_location = chrome_binary

        # создаём драйвер
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=self.options)


    def _parse_amount_from_text(self, s: str):
        if not s:
            return None
        s = s.replace("\u00A0", " ").replace("\xa0", " ").strip()
        m = _amount_re.search(s)
        if not m:
            return None
        num = m.group(1)
        num = num.replace(" ", "").replace(",", ".").replace("+", "").strip()
        try:
            return Decimal(num).quantize(Decimal("0.01"))
        except InvalidOperation:
            return None
    def close_browser(self):
        try:
            self.driver.quit()
        except Exception:
            pass

    def open_site(self, url):
        self.driver.get(url)

    def click_repeat_login(self):
        button = WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//span[text()='Повторить вход']/.."))
        )
        button.click()

    def enter_sequence(self, sequence, delay=0.3):
        for digit in sequence:
            button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, f"//span[text()='{digit}']/.."))
            )
            button.click()
            time.sleep(delay)

    @staticmethod
    def _normalize_number_text(s: str) -> str:
        """
        Статический нормализатор числовых строк — всегда доступен через self._normalize_number_text(...)
        """
        if not s:
            return s
        # заменяем разные пробельные символы на обычный пробел
        s2 = s.replace("\u00A0", " ").replace("\xa0", " ").replace("\u202F", " ")
        # unicode minus -> ascii minus
        s2 = s2.replace("\u2212", "-")
        s2 = s2.strip()
        # убрать явный +
        if s2.startswith("+"):
            s2 = s2[1:]
        # удалить пробелы тысяч
        s2 = s2.replace(" ", "")
        # заменить запятую на точку
        s2 = s2.replace(",", ".")
        return s2
    def go_to_operations(self):
        self.driver.get("https://web6.online.sberbank.ru/operations")

    def is_operations_page(self, timeout=2):
        """Признак, что мы уже на странице операций."""
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "section.Rd3aMg57"))
            )
            return True
        except TimeoutException:
            return False

    def is_keypad_present(self, timeout=2):
        """Есть ли на странице цифровая клавиатура (пример: кнопка с '0')."""
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.XPATH, "//span[normalize-space(text())='0']"))
            )
            return True
        except TimeoutException:
            return False
    def ensure_logged_in(self, pin_code, max_retries=5):
        """
        Надёжная авторизация: кликает любую ссылку 'Повторить вход' по тексту span,
        затем вводит PIN. Повторяет попытки до max_retries.
        """
        attempts = 0
        while attempts < max_retries:
            attempts += 1
            try:
                # ищем любую ссылку <a> с вложенным <span> 'Повторить вход'
                repeat_link = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//a[.//span[normalize-space(text())='Повторить вход']]")
                    )
                )
                print(f"[Попытка {attempts}] Найдена ссылка 'Повторить вход'.")

                # скроллим и кликаем через JS
                self.driver.execute_script("arguments[0].scrollIntoView(true);", repeat_link)
                time.sleep(0.3)
                try:
                    repeat_link.click()
                    print("Клик по ссылке выполнен обычным click().")
                except Exception:
                    self.driver.execute_script("arguments[0].click();", repeat_link)
                    print("Клик выполнен через JS.")

                # ждём клавиатуру и вводим PIN
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//span[normalize-space(text())='0']"))
                )
                print("Клавиатура появилась, ввожу PIN...")
                self.enter_sequence(pin_code)
                time.sleep(2)

                # после ввода PIN проверяем: если снова появилось окно, цикл повторится
                continue

            except Exception:
                # если ссылка не найдена — считаем, что авторизация пройдена
                print("Ссылка 'Повторить вход' не найдена, авторизация, возможно, успешна.")
                return True

        print("Не удалось пройти авторизацию за max_retries попыток.")
        return False


    def wait_for_number(self, number, interval=20, timeout=240):
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.check_number_transfer_in_today_yesterday(number):
                return True
            print(f"Число {number} не найдено. Жду {interval} сек...")
            time.sleep(interval)
            try:
                self.driver.refresh()
            except Exception:
                return False
            time.sleep(5)
        return False

    def check_number_transfer_in_today_yesterday(self, number):
        try:
            expected = Decimal(str(number).replace(",", ".")).quantize(Decimal("0.01"))
        except InvalidOperation:
            print(f"[check] Некорректное число (expected): {number}")
            return False

        print(f"[check] Ищем сумму: {expected}")
        print(f"[check] normalize func: {self._normalize_number_text!r}")

        # получить snapshot (как у тебя было)
        js = """
        return (function(){
            try {
                const ul = document.querySelector('ul[aria-label*="Операции"]')
                          || document.querySelector('ul[aria-label*="операции"]')
                          || Array.from(document.querySelectorAll('ul')).find(u => {
                              const a = u.getAttribute('aria-label');
                              return a && a.toLowerCase().includes('операц');
                          });
                if (ul) {
                    return {method:'ul', items: Array.from(ul.querySelectorAll('li')).map(li=>({text: li.innerText || '', href: (li.querySelector('a') ? li.querySelector('a').getAttribute('href') : '')}))};
                }
                const all = Array.from(document.querySelectorAll('li')).filter(li => /\\d/.test(li.innerText)).slice(0,200);
                if (all.length) {
                    return {method:'li_fallback', items: all.map(li=>({text: li.innerText || '', href: (li.querySelector('a') ? li.querySelector('a').getAttribute('href') : '')}))};
                }
                return {method:'body', items:[{text: document.body ? document.body.innerText : '', href:''}]};
            } catch(e) {
                return {method:'error', items:[] , err: String(e)};
            }
        })();
        """
        items = []
        try:
            res = None
            try:
                res = self.driver.execute_script(js)
            except Exception as e:
                print("[check] execute_script exception:", e)
                res = None

            if isinstance(res, dict) and res.get("items"):
                items = res.get("items", [])
                print(f"[check] snapshot method='{res.get('method')}', items={len(items)}")
            else:
                print("[check] snapshot пуст или ошибка; fallback через find_elements")
                try:
                    ul = None
                    try:
                        ul = self.driver.find_element(By.XPATH,
                                                      "//ul[contains(@aria-label,'Операции') or contains(@aria-label,'операции')]")
                    except Exception:
                        ul = None
                    if ul:
                        li_elems = ul.find_elements(By.TAG_NAME, "li")
                    else:
                        li_elems = self.driver.find_elements(By.XPATH, "//li[.//text()[normalize-space()]]")
                    print(f"[check] find_elements найдено li: {len(li_elems)}")
                    for li in li_elems:
                        try:
                            txt = li.text or ""
                            a = ""
                            try:
                                a_el = li.find_element(By.TAG_NAME, "a")
                                a = a_el.get_attribute("href") or ""
                            except Exception:
                                a = ""
                            if txt and re.search(r"\d", txt):
                                items.append({"text": txt, "href": a})
                        except Exception:
                            continue
                except Exception as e:
                    print("[check] find_elements failed:", e)
        except Exception as e:
            print("[check] unexpected error collecting items:", e)

        if not items:
            try:
                title = self.driver.title
                body_preview = self.driver.execute_script(
                    "return (document.body && document.body.innerText) ? document.body.innerText.slice(0,1000) : ''")
                print("[check] items пуст. title:", title)
                print("[check] body preview:", body_preview[:1000] or "(пусто)")
            except Exception as e:
                print("[check] не удалось получить body preview:", e)
            return False

        found_any_amount = False
        # сначала ищем числа прямо перед символом ₽ — это более устойчиво к верстке
        currency_re = re.compile(r"([+\-−]?\s*\d{1,3}(?:[ \u00A0\u202F]\d{3})*(?:[.,]\d{1,2})?)\s*₽")

        for idx, it in enumerate(items):
            try:
                text = (it.get("text") or "").strip()
                href = it.get("href") or ""
                if not text:
                    continue
                preview = text.replace("\n", " | ")
                print(f"[check] item#{idx} href='{href}' preview='{preview[:160]}'")

                # 1) попытка: искать "число + ₽" (самый надёжный)
                matched = False
                for m in currency_re.finditer(text):
                    raw = m.group(1)
                    matched = True
                    try:
                        norm = self._normalize_number_text(raw)
                    except Exception as ex:
                        print(f"[check] normalize failed for raw={repr(raw)}: {ex}")
                        continue
                    try:
                        amt = Decimal(norm).quantize(Decimal("0.01"))
                    except Exception:
                        print(f"[check] не удалось Decimal('{norm}') из raw={repr(raw)}")
                        continue

                    found_any_amount = True
                    ctx = text.lower()
                    is_transfer = any(k in ctx for k in _payment_keywords)
                    print(
                        f"[check] найдено (currency) raw={repr(raw)} -> norm={repr(norm)} -> amt={amt}; is_transfer={is_transfer}")

                    if amt == expected:
                        if is_transfer:
                            print(f"[check] УСПЕХ: по контексту (currency): {expected}")
                            return True
                        if href and any(x in href for x in ("/operations/", "/payments/", "details", "fps")):
                            print(f"[check] УСПЕХ: по href (currency) {href}: {expected}")
                            return True

                # 2) fallback: общий regex _amount_re
                if not matched:
                    for m in _amount_re.finditer(text):
                        raw = m.group(0)
                        try:
                            norm = self._normalize_number_text(raw)
                        except Exception as ex:
                            print(f"[check] normalize failed for raw={repr(raw)}: {ex}")
                            continue
                        try:
                            amt = Decimal(norm).quantize(Decimal("0.01"))
                        except Exception:
                            print(f"[check] не удалось Decimal('{norm}') из raw={repr(raw)}")
                            continue

                        found_any_amount = True
                        ctx = text.lower()
                        is_transfer = any(k in ctx for k in _payment_keywords)
                        print(
                            f"[check] найдено (fallback) raw={repr(raw)} -> norm={repr(norm)} -> amt={amt}; is_transfer={is_transfer}")

                        if amt == expected:
                            if is_transfer:
                                print(f"[check] УСПЕХ: по контексту (fallback): {expected}")
                                return True
                            if href and any(x in href for x in ("/operations/", "/payments/", "details", "fps")):
                                print(f"[check] УСПЕХ: по href (fallback) {href}: {expected}")
                                return True

                # конец обработки item
            except Exception as e:
                import traceback
                print("[check] исключение при обработке item:", repr(e))
                traceback.print_exc()
                continue

        if not found_any_amount:
            print("[check] На странице не обнаружено распознанных сумм (regex не нашёл).")
        else:
            print(
                f"[check] Сумма {expected} присутствует в тексте, но условия фильтров не дали положительного результата.")
        return False

def ensure_logged_in_and_stable(self, pin_code, timeout=120):
    """
    Поддерживает сессию: если в любой момент появляется кнопка 'Повторить вход',
    кликнуть её, ввести PIN и вернуться на operations.
    Работает до timeout секунд.
    """
    start = time.time()
    while time.time() - start < timeout:
        try:
            # если кнопка есть — кликаем и вводим PIN
            repeat_link = self.driver.find_element(By.XPATH, "//a[.//span[text()='Повторить вход']]")
            print("Обнаружено окно 'Повторить вход', кликаю...")
            self.driver.execute_script("arguments[0].scrollIntoView(true); arguments[0].click();", repeat_link)
            time.sleep(1)
            self.enter_sequence(pin_code)
            time.sleep(2)
            print("PIN введён, повторяю переход на operations...")
            self.go_to_operations()
        except Exception:
            # кнопки нет — проверяем, загрузилась ли страница операций
            if self.is_operations_page(timeout=2):
                print("Страница операций загружена, сессия стабильна.")
                return True
        time.sleep(0.5)
    print("Не удалось стабилизировать сессию за timeout секунд.")
    return False

# ------------------ Точка входа ------------------
def run_sbercheck(amount):
    """
    amount: сумма для проверки (str или int)
    Возвращает True/False в зависимости от результата.
    """

    # --- Очищаем старые lock-файлы перед запуском ---
    for lock_file in LOCK_DIR.glob("*.lock"):
        try:
            lock_file.unlink()
            print(f"Удалён старый lock-файл: {lock_file.name}")
        except Exception:
            print(f"Не удалось удалить lock-файл: {lock_file.name}")

    # --- пробуем взять свободный профиль (последовательно) ---
    chosen_work_profile = None
    chosen_lock = None
    for src in SRC_PROFILES:
        work_profile, lock = prepare_work_profile(src)
        if work_profile is not None and lock is not None:
            chosen_work_profile = work_profile
            chosen_lock = lock
            break

    if chosen_work_profile is None:
        print("Нет свободных профилей.")
        return None  # профили заняты

    print("Использую рабочий профиль:", chosen_work_profile)

    bot = None
    status_bool = False

    try:
        bot = SberAutomation(chosen_work_profile, CHROME_BINARY)

        bot.open_site("https://web6.online.sberbank.ru/")
        bot.ensure_logged_in(["0", "8", "8", "0", "0"])  # ввод пин-кода с проверкой повторов
        bot.go_to_operations()
        time.sleep(5)

        status_bool = bot.wait_for_number(amount)

        print("Результат:", status_bool)
        return status_bool

    except Exception as e:
        print("Ошибка в процессе:", e)
        return False
    finally:
        if bot:
            bot.close_browser()
        if chosen_lock:
            release_lock(chosen_lock)
        print("Профиль освобождён.")