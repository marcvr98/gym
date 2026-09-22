import os
import re
import time
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
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

# --- Configuración del aviso por email ----------------------------------
# Umbral: si quedan estas plazas o menos, se envía el correo
UMBRAL_PLAZAS_LIBRES = 2

SMTP_SERVER = "smtp.gmail.com"   # cambia esto si no usas Gmail
SMTP_PORT = 465                  # 465 = SSL directo

EMAIL_FROM = os.getenv('EMAIL_FROM')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
EMAIL_TO = os.getenv('EMAIL_TO')
DEBUG_SCRAPER = os.getenv('DEBUG_SCRAPER', '').lower() in {'1', 'true', 'yes', 'on'}


def enviar_correo(asunto: str, cuerpo: str) -> None:
    """Envía un correo simple en texto plano."""
    if not (EMAIL_FROM and EMAIL_PASSWORD and EMAIL_TO):
        print('Faltan variables de entorno EMAIL_FROM/EMAIL_PASSWORD/EMAIL_TO; no se envía correo.')
        return

    mensaje = MIMEMultipart()
    mensaje["From"] = EMAIL_FROM
    mensaje["To"] = EMAIL_TO
    mensaje["Subject"] = asunto
    mensaje.attach(MIMEText(cuerpo, "plain"))

    contexto = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=contexto) as servidor:
        servidor.login(EMAIL_FROM, EMAIL_PASSWORD)
        servidor.sendmail(EMAIL_FROM, EMAIL_TO, mensaje.as_string())
    print('Correo de aviso enviado.')


def calcular_plazas_libres(texto: str):
    """
    Interpreta el texto crudo devuelto por el sitio (variable 'res') como
    un número de plazas libres. Soporta dos formatos habituales:
      - "reservadas/totales", p.ej. "9/12"  -> libres = totales - reservadas
      - un único número que ya representa las plazas libres, p.ej. "4"
    Devuelve None si no se puede interpretar.
    """
    if not texto:
        return None
    texto = texto.strip()

    m = re.search(r'(\d+)\s*/\s*(\d+)', texto)
    if m:
        reservadas, totales = int(m.group(1)), int(m.group(2))
        return max(totales - reservadas, 0)

    m = re.search(r'(\d+)', texto)
    if m:
        return int(m.group(1))

    return None


def build_driver(headless=True):
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
    return driver


def login_and_fetch_schedule(keep_browser=False, headless=True):
    global DAY_CHECK_RESULT

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
        try:
            WebDriverWait(driver, 20).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
                and (d.find_elements(By.ID, "clasesDiaSel") or d.find_elements(By.XPATH, "//div[contains(@class,'weekNavigator')]"))
            )
        except Exception:
            pass
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
                        if DEBUG_SCRAPER:
                            print('[DEBUG] Esperando a que la agenda del miércoles cargue...')
                        time.sleep(3.5)
                        
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

    if DEBUG_SCRAPER:
        print(f"[DEBUG] HTML recibido para parseo: {len(html)} bytes")

    blocks = soup.select("div[id^='bloqueClass']")

    for i, bloque in enumerate(blocks):
        text = bloque.get_text(' ', strip=True)
        if i >= 20 and DEBUG_SCRAPER:
            print(f"[DEBUG] bloque[{i}] -> {text}")
        if not text:
            continue

        if '19:15' not in text or '20:15' not in text or 'ENDURANCE' not in text.upper():
            continue

        occupation = bloque.select_one('span.rvOcupacion')
        if occupation:
            return occupation.get_text(' ', strip=True).strip()

        match = re.search(r'Occupied places\s*(\d+\s*/\s*\d+)', text, flags=re.I)
        if match:
            return match.group(0).strip()

        match = re.search(r'(\d+\s*/\s*\d+)', text)
        if match:
            return match.group(0).strip()

        if DEBUG_SCRAPER:
            print(f"[DEBUG] Bloque encontrado pero sin ocupación clara: {text[:400]}")

    if DEBUG_SCRAPER:
        print("[DEBUG] No se encontró ningún bloque con 'ENDURANCE' y '19:15 - 20:15' en el documento.")
        print(f"[DEBUG] Primeros 3000 caracteres del HTML: {html[:3000]}")
    return None

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

            libres = calcular_plazas_libres(res)
            print(f'(texto crudo interpretado como {libres} plazas libres)')

            if libres is not None and libres <= UMBRAL_PLAZAS_LIBRES:
                enviar_correo(
                    asunto='🏋️ Quedan pocas plazas para ENDURANCE 19:15',
                    cuerpo=(
                        f'Quedan {libres} plazas libres para la clase ENDURANCE de las 19:15.\n'
                        f'Texto original del sitio: "{res}"'
                    )
                )