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

# ------------------ Утилиты для блокировки профиля ------------------
def try_acquire_lock(name: str):
    lock_path = LOCK_DIR / f"{name}.lock"
    try:
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
    if not src_profile.exists():
        return None, None

    profile_name = src_profile.name.replace(" ", "_")
    work_profile = WORK_ROOT / profile_name

    lock = try_acquire_lock(profile_name)
    if lock is None:
        return None, None

    try:
        if not work_profile.exists():
            print(f"Копируем профиль {src_profile} -> {work_profile} ...")
            shutil.copytree(src_profile, work_profile)
            print("Копирование завершено.")
        else:
            print(f"Рабочая папка {work_profile} уже существует — используем её.")
    except Exception as e:
        print("Ошибка при копировании профиля:", e)
        release_lock(lock)
        return None, None

    return work_profile, lock

# ------------------ Класс автоматизации (твоя логика проверки) ------------------
class SberAutomation:
    def __init__(self, user_data_dir: str, chrome_binary: str):
        self.user_data_dir = user_data_dir
        self.chrome_binary = chrome_binary

        self.options = Options()
        self.options.add_argument(f"user-data-dir={str(self.user_data_dir)}")
        port = random.randint(10000, 20000)
        self.options.add_argument(f"--remote-debugging-port={port}")
        self.options.add_argument("--no-sandbox")
        self.options.add_argument("--disable-dev-shm-usage")
        # self.options.add_argument("--headless=new")  # не включаем по умолчанию

        self.options.binary_location = chrome_binary
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=self.options)

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

    def go_to_operations(self):
        self.driver.get("https://web6.online.sberbank.ru/operations")

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
            sections = WebDriverWait(self.driver, 10).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "section.Rd3aMg57"))
            )
        except Exception:
            return False

        # нормализуем ожидаемое число в Decimal с двумя знаками
        try:
            number_str = str(number).replace(",", ".")
            expected = Decimal(number_str).quantize(Decimal("0.01"))
        except InvalidOperation:
            print(f"Некорректное число для проверки: {number}")
            return False

        for section in sections:
            try:
                header = section.find_element(By.CSS_SELECTOR, "p[data-unit='Date']").text
                if header in ["Сегодня", "Вчера"]:
                    payments = section.find_elements(By.CSS_SELECTOR, "li.H_H0S1Xc")
                    for payment in payments:
                        try:
                            # тип платежа
                            type_elem = payment.find_element(By.CSS_SELECTOR, "p.JGQNsH85")
                            if "перевод" in type_elem.text.lower():
                                # сначала пробуем найти сумму по специфическому селектору (как в старой версии)
                                text_amount = None
                                try:
                                    amount_elem = payment.find_element(By.CSS_SELECTOR, "p.IAXNmUo7")
                                    text_amount = amount_elem.text
                                except Exception:
                                    # fallback: любой <p> содержащий ₽ внутри
                                    try:
                                        amount_elem = payment.find_element(By.XPATH, ".//p[contains(text(), '₽')]")
                                        text_amount = amount_elem.text
                                    except Exception:
                                        text_amount = None

                                if not text_amount:
                                    continue

                                # очистка и нормализация
                                text_amount = text_amount.replace(" ", "").replace("₽", "").replace("+", "").replace(",", ".")
                                try:
                                    actual = Decimal(text_amount).quantize(Decimal("0.01"))
                                except InvalidOperation:
                                    continue

                                # отладочный вывод (можно комментировать)
                                print(f"Найденная сумма на странице: {actual}; ожидаем: {expected}")

                                if actual == expected:
                                    print(f"Найден платёж {expected}")
                                    return True
                        except Exception:
                            continue
            except Exception:
                continue
        return False

# ------------------ Точка входа ------------------
def run_sbercheck(amount):
    """
    amount: сумма для проверки (строка/число)
    Возвращает True/False/None (None — если нет свободных профилей)
    """
    # пробуем взять свободный профиль (последовательно)
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

    driver_instance = None
    status_bool = False

    try:
        driver_instance = SberAutomation(chosen_work_profile, CHROME_BINARY)

        driver_instance.open_site("https://web6.online.sberbank.ru/")
        driver_instance.click_repeat_login()
        time.sleep(2)
        driver_instance.enter_sequence(["0", "8", "8", "0", "0"])
        time.sleep(2)
        driver_instance.go_to_operations()
        time.sleep(5)

        status_bool = driver_instance.wait_for_number(amount)

        print("Результат:", status_bool)
        return status_bool

    except Exception as e:
        print("Ошибка в процессе:", e)
        return False
    finally:
        if driver_instance:
            driver_instance.close_browser()
        if chosen_lock:
            release_lock(chosen_lock)
        print("Профиль освобождён.")