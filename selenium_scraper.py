import os
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

LOGIN_URL = "https://login.aimharder.com"
BASE = "https://wodboxtraining.aimharder.com"

load_dotenv()
# Fecha actual en formato YYYYMMDD
TODAY = datetime.now().strftime('%Y%m%d')
USER = os.getenv('USUARIO')
PASS = os.getenv('CONTRASENA')
# Resultado del chequeo del selector de día: 'passed_wednesday', 'clicked_to_wednesday' o None
DAY_CHECK_RESULT = None

# Selector config (may need adjustments if the site changes)
USERNAME_SELECTOR = 'input[name="username"]'
PASSWORD_SELECTOR = 'input[name="password"]'
SUBMIT_SELECTOR = 'button[type="submit"]'


def build_driver(headless=True):
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
    return driver


def login_and_fetch_schedule(keep_browser=False, headless=True):
    if not USER or not PASS:
        raise SystemExit('Las variables de entorno USUARIO/CONTRASENA no están definidas')

    driver = build_driver(headless=headless)
    try:
        driver.get(LOGIN_URL)
        time.sleep(1.5)

        # accept cookies if any (best-effort)
        try:
            #div con id=eucookielaw
            btn = driver.find_element(By.XPATH, "//body//div[contains(@id, 'eucookielaw')]//a[contains(text(), 'Aceptar')]")
            if btn.is_displayed():
                print("Aceptando cookies...")
            btn.click()
            time.sleep(0.5)
        except Exception:
            pass

        # Attempt to find username/password inputs
        try:
            user_el = driver.find_element(By.CSS_SELECTOR, USERNAME_SELECTOR)
            pass_el = driver.find_element(By.CSS_SELECTOR, PASSWORD_SELECTOR)
        except Exception:
            # fallback: try common ids
            try:
                user_el = driver.find_element(By.ID, 'username')
                pass_el = driver.find_element(By.ID, 'password')
            except Exception:
                if not keep_browser:
                    driver.quit()
                raise SystemExit('No se encontraron campos de login en la página de login. Verifica selectores')

        user_el.clear(); user_el.send_keys(USER)
        pass_el.clear(); pass_el.send_keys(PASS)
        # submit
        try:
            submit = driver.find_element(By.CSS_SELECTOR, SUBMIT_SELECTOR)
            submit.click()
        except Exception:
            pass
        time.sleep(3)

        # after login, go to schedule
        driver.get(BASE + '/schedule')
        time.sleep(3)
        #cerrar display si aparece
        try:
            close_btn = driver.find_element(By.XPATH, "//body//div[contains(@class, 'ahPromoNewMenu')]/button")
            if close_btn.is_displayed():
                print("Cerrando display...")
            close_btn.click()
        except Exception:
            pass
        time.sleep(1)
        #aceptar mismas cookies si aparecen
        try:
            btn = driver.find_element(By.XPATH, "//body//div[contains(@id, 'eucookielaw')]//a[contains(text(), 'Accept all')]")
            if btn.is_displayed():
                print("Aceptando cookies en schedule...")
            btn.click()
            time.sleep(0.5)
        except Exception:
            pass
        # Buscar selector de semana y comprobar día activo
        try:
            wk = driver.find_element(By.XPATH, "//body//div[contains(@class,'weekNavigator')]//div[@id='weekDays']")
            anchors = wk.find_elements(By.TAG_NAME, 'a')
            active_index = None
            import re
            for i,a in enumerate(anchors):
                cls = a.get_attribute('class') or ''
                if 'active' in cls:
                    active_index = i  # 0-based
                    onclick = a.get_attribute('onclick') or ''
                    # extraer fecha de onclick weekSelDay("YYYYMMDD")
                    m = re.search(r"weekSelDay\([\"'](\d{8})[\"']\)", onclick)
                    break

            if active_index is not None:
                # si el activo es la posición 4 (índice 3) o más
                if active_index >= 3:
                    print('El día activo es posterior al miércoles; no se consultarán más clases.')
                    DAY_CHECK_RESULT = 'passed_wednesday'
                    html = driver.page_source
                    if keep_browser:
                        return driver, html
                    return html

                # si activo es la posición 2 (índice 1), hacer click en el siguiente (miércoles)
                if active_index == 1 and len(anchors) > active_index+1:
                    print('El día activo parece ser martes; selecciono el siguiente día (miércoles).')
                    try:
                        anchors[active_index+1].click()
                        time.sleep(1.2)
                    except Exception:
                        pass
        except Exception:
            pass
        html = driver.page_source
        if keep_browser:
            return driver, html
        return html
    finally:
        if not keep_browser:
            driver.quit()


def find_next_endurance_occupation(html):
    soup = BeautifulSoup(html, 'lxml')
    # find all blocks that contain 'endurance' and a time
    
    bloque_principal = soup.find('div', id='clasesDiaSel')
    clases = bloque_principal.find_all('div') if bloque_principal else []
    if clases:
        for clase in clases:
            hora = clase.find('span', class_='rvHora')
            #la hora viene así: 07:00 - 08:00
            if hora and '19:15' in hora.get_text() and '20:15' in hora.get_text():
                text = clase.find('span', class_='rvNombreCl')
                if "ENDURANCE" in text.get_text().upper():
                    # check if reserved and capacity are present
                    margen = clase.find('div', class_='rvMarginDesc')
                    occupation = margen.find('span', class_='rvOcupacion') if margen else None
                    texto = occupation.get_text() if occupation else ''
                    plazas = texto.split('places ')[1] if 'places ' in texto else texto
                    return plazas.strip()  # e.g., "3/20" or "un número desconocido de personas"
                
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--visible', action='store_true', help='Abrir navegador visible para depuración')
    args = parser.parse_args()
    headless = not args.visible
    keep_browser = args.visible
    result = login_and_fetch_schedule(keep_browser=keep_browser, headless=headless)

    if keep_browser:
        driver, html = result
    else:
        html = result

    if DAY_CHECK_RESULT == 'passed_wednesday':
        print('El día activo es posterior al miércoles; no se consultarán más clases.')
    else:
        res = find_next_endurance_occupation(html)


    if not res:
        print('No se encontró un evento "endurance" a las 19:15 en el DOM cargado')
    else:
        print(f'Hay {res} plazas disponibles para el próximo endurance a las 19:15')