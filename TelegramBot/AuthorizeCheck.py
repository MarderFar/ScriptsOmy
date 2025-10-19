from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    ElementNotInteractableException,
    StaleElementReferenceException,
    NoSuchElementException,
)
from webdriver_manager.chrome import ChromeDriverManager
import time

def check_login(username: str, password: str, max_attempts=3):
    options = Options()
    options.binary_location = r"C:\Users\MarderFar\Desktop\chrome-win64\chrome.exe"
    # options.add_argument("--headless=new")  # если нужен скрытый режим

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.get("https://learn.rosseti-sib.ru/login/index.php")

    attempt = 0
    login_successful = False

    while attempt < max_attempts and not login_successful:
        attempt += 1
        try:
            # --- Ждём поля ввода ---
            username_field = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, "username"))
            )
            password_field = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, "password"))
            )
            login_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, "loginbtn"))
            )

            # --- Вводим логин и пароль ---
            for _ in range(3):  # retry на случай ElementNotInteractableException
                try:
                    username_field.clear()
                    username_field.send_keys(username)
                    password_field.clear()
                    password_field.send_keys(password)
                    break
                except ElementNotInteractableException:
                    time.sleep(0.3)

            # --- Кликаем кнопку ---
            try:
                login_button.click()
            except (ElementNotInteractableException, StaleElementReferenceException):
                driver.execute_script("arguments[0].click();", login_button)

            time.sleep(2)  # ждём загрузки

            # --- Проверка ошибки ---
            try:
                error_elem = driver.find_element(By.CSS_SELECTOR, "div.alert.alert-danger")
                if "Неверный логин или пароль" in error_elem.text:
                    print(f"[Попытка {attempt}] Неверный логин или пароль, пробуем снова...")
                    continue
            except NoSuchElementException:
                # Ошибка не найдена, значит вход успешен
                login_successful = True
                print(f"Авторизация успешна на попытке {attempt}")

        except TimeoutException:
            print(f"[Попытка {attempt}] Не удалось найти поля или кнопку, повторяем...")
            driver.refresh()
            time.sleep(2)
        except Exception as e:
            print(f"[Попытка {attempt}] Произошла ошибка: {e}")
            driver.refresh()
            time.sleep(2)

    driver.quit()
    return login_successful

# --- Пример использования ---
if __name__ == "__main__":
    result = check_login("your_login", "your_password")
    print("Авторизация успешна:", result)
