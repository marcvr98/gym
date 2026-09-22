import os
import re
import time
import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager


LOGIN_URL = "https://login.aimharder.com"
BASE_URL = "https://wodboxtraining.aimharder.com"
SCHEDULE_URL = f"{BASE_URL}/schedule"

USERNAME_SELECTOR = 'input[name="username"]'
PASSWORD_SELECTOR = 'input[name="password"]'
SUBMIT_SELECTOR = 'button[type="submit"]'

CLASE_BUSCADA = "ENDURANCE"
HORA_INICIO = "19:15"
HORA_FIN = "20:15"

UMBRAL_PLAZAS_LIBRES = 2

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465

TIMEOUT = 25
ZONA_HORARIA = ZoneInfo("Europe/Madrid")

load_dotenv()

USER = os.getenv("USUARIO")
PASSWORD = os.getenv("CONTRASENA")

EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_TO = os.getenv("EMAIL_TO")

DEBUG_SCRAPER = os.getenv(
    "DEBUG_SCRAPER", "false"
).lower() in {"1", "true", "yes", "on"}

DAY_CHECK_RESULT = None


def debug(mensaje):
    if DEBUG_SCRAPER:
        print(f"[DEBUG] {mensaje}")


def build_driver(headless=True):
    options = webdriver.ChromeOptions()

    if headless:
        options.add_argument("--headless=new")

    # Opciones recomendadas para GitHub Actions
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-networking")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=es-ES")
    options.add_argument("--force-device-scale-factor=1")

    options.add_experimental_option(
        "prefs",
        {
            "intl.accept_languages": "es-ES,es,en",
        },
    )

    driver = webdriver.Chrome(
        service=ChromeService(ChromeDriverManager().install()),
        options=options,
    )

    driver.set_window_size(1920, 1080)
    driver.set_page_load_timeout(60)

    return driver


def aceptar_cookies(driver):
    selectores = [
        (
            By.XPATH,
            "//div[contains(@id,'eucookielaw')]"
            "//a[contains(normalize-space(), 'Aceptar')]",
        ),
        (
            By.XPATH,
            "//div[contains(@id,'eucookielaw')]"
            "//a[contains(normalize-space(), 'Accept all')]",
        ),
        (
            By.XPATH,
            "//button[contains(normalize-space(), 'Aceptar')]",
        ),
        (
            By.XPATH,
            "//button[contains(normalize-space(), 'Accept all')]",
        ),
    ]

    for by, selector in selectores:
        try:
            botones = driver.find_elements(by, selector)

            for boton in botones:
                if boton.is_displayed() and boton.is_enabled():
                    print("Aceptando cookies...")
                    driver.execute_script(
                        "arguments[0].click();",
                        boton,
                    )
                    time.sleep(0.5)
                    return True
        except Exception as exc:
            debug(f"No se pudo comprobar un selector de cookies: {exc!r}")

    return False


def cerrar_promocion(driver):
    try:
        botones = driver.find_elements(
            By.CSS_SELECTOR,
            "div.ahPromoNewMenu button",
        )

        for boton in botones:
            if boton.is_displayed() and boton.is_enabled():
                print("Cerrando display promocional...")
                driver.execute_script(
                    "arguments[0].click();",
                    boton,
                )
                time.sleep(0.5)
                return True
    except Exception as exc:
        debug(f"No se pudo cerrar la promoción: {exc!r}")

    return False


def realizar_login(driver):
    driver.get(LOGIN_URL)

    WebDriverWait(driver, TIMEOUT).until(
        lambda d: d.execute_script(
            "return document.readyState"
        ) == "complete"
    )

    aceptar_cookies(driver)

    try:
        usuario = WebDriverWait(driver, TIMEOUT).until(
            lambda d: d.find_element(
                By.CSS_SELECTOR,
                USERNAME_SELECTOR,
            )
        )

        contrasena = driver.find_element(
            By.CSS_SELECTOR,
            PASSWORD_SELECTOR,
        )
    except Exception:
        try:
            usuario = driver.find_element(By.ID, "username")
            contrasena = driver.find_element(By.ID, "password")
        except Exception as exc:
            raise RuntimeError(
                "No se encontraron los campos de inicio de sesión."
            ) from exc

    usuario.clear()
    usuario.send_keys(USER)

    contrasena.clear()
    contrasena.send_keys(PASSWORD)

    boton = driver.find_element(
        By.CSS_SELECTOR,
        SUBMIT_SELECTOR,
    )
    boton.click()

    WebDriverWait(driver, TIMEOUT).until(
        lambda d: d.current_url != LOGIN_URL
    )

    debug(f"URL después del login: {driver.current_url}")


def esperar_agenda(driver):
    WebDriverWait(driver, TIMEOUT).until(
        lambda d: (
            d.execute_script("return document.readyState") == "complete"
            and (
                d.find_elements(By.ID, "clasesDiaSel")
                or d.find_elements(By.CSS_SELECTOR, ".weekNavigator")
                or d.find_elements(
                    By.CSS_SELECTOR,
                    "div[id^='bloqueClass']",
                )
            )
        )
    )


def obtener_fecha_anchor(anchor):
    onclick = anchor.get_attribute("onclick") or ""

    match = re.search(
        r"weekSelDay\([\"'](\d{8})[\"']\)",
        onclick,
    )

    if match:
        return match.group(1)

    return None


def seleccionar_miercoles(driver):
    global DAY_CHECK_RESULT

    navegador = WebDriverWait(driver, TIMEOUT).until(
        lambda d: d.find_element(
            By.XPATH,
            "//div[contains(@class,'weekNavigator')]"
            "//div[@id='weekDays']",
        )
    )

    anchors = navegador.find_elements(By.TAG_NAME, "a")

    if not anchors:
        raise RuntimeError(
            "No se encontraron días en el navegador semanal."
        )

    active_index = None
    fecha_activa = None

    for indice, anchor in enumerate(anchors):
        clases = anchor.get_attribute("class") or ""

        if "active" in clases.split():
            active_index = indice
            fecha_activa = obtener_fecha_anchor(anchor)
            break

    if active_index is None:
        raise RuntimeError(
            "No se pudo identificar el día activo."
        )

    debug(
        f"Día activo: índice={active_index}, "
        f"fecha={fecha_activa}, "
        f"texto={anchors[active_index].text!r}"
    )

    # Posiciones esperadas:
    # 0 = lunes, 1 = martes, 2 = miércoles
    if active_index >= 3:
        DAY_CHECK_RESULT = "passed_wednesday"
        print(
            "El día activo es posterior al miércoles; "
            "no se consultarán más clases."
        )
        return False

    if active_index == 2:
        DAY_CHECK_RESULT = "already_wednesday"
        print("El día activo ya es miércoles.")
        return True

    if active_index != 1:
        DAY_CHECK_RESULT = "not_tuesday"
        print(
            "El día activo no es martes. "
            "No se seleccionará otro día automáticamente."
        )
        return False

    if len(anchors) <= active_index + 1:
        raise RuntimeError(
            "No existe un enlace para el miércoles."
        )

    target = anchors[active_index + 1]
    fecha_miercoles = obtener_fecha_anchor(target)

    print(
        "El día activo parece ser martes; "
        "selecciono el siguiente día (miércoles)."
    )

    debug(
        f"Fecha objetivo del miércoles: {fecha_miercoles}, "
        f"texto={target.text!r}"
    )

    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center'});",
        target,
    )
    driver.execute_script("arguments[0].click();", target)

    debug("Esperando a que la agenda del miércoles cargue...")

    def miercoles_activo(d):
        elementos = d.find_elements(
            By.CSS_SELECTOR,
            "#weekDays a",
        )

        for elemento in elementos:
            clases = elemento.get_attribute("class") or ""
            fecha = obtener_fecha_anchor(elemento)

            if (
                "active" in clases.split()
                and fecha_miercoles
                and fecha == fecha_miercoles
            ):
                return True

        return False

    WebDriverWait(driver, TIMEOUT).until(miercoles_activo)

    # Esperar a que existan bloques de clases.
    WebDriverWait(driver, TIMEOUT).until(
        lambda d: len(
            d.find_elements(
                By.CSS_SELECTOR,
                "div[id^='bloqueClass']",
            )
        ) > 0
    )

    # Esperar específicamente a ENDURANCE 19:15.
    WebDriverWait(driver, TIMEOUT).until(
        lambda d: any(
            HORA_INICIO in elemento.text
            and CLASE_BUSCADA in elemento.text.upper()
            for elemento in d.find_elements(
                By.CSS_SELECTOR,
                "div[id^='bloqueClass']",
            )
        )
    )

    # Margen para contenido cargado mediante JavaScript/AJAX.
    time.sleep(2)

    DAY_CHECK_RESULT = "clicked_to_wednesday"
    return True


def buscar_endurance(driver):
    bloques = driver.find_elements(
        By.CSS_SELECTOR,
        "div[id^='bloqueClass']",
    )

    debug(f"Número de bloques encontrados: {len(bloques)}")

    for indice, bloque in enumerate(bloques):
        texto = " ".join(bloque.text.split())

        if DEBUG_SCRAPER:
            debug(f"bloque[{indice}] -> {texto}")

        if not texto:
            continue

        coincide = (
            HORA_INICIO in texto
            and HORA_FIN in texto
            and CLASE_BUSCADA in texto.upper()
        )

        if not coincide:
            continue

        debug(f"ENDURANCE encontrado en bloque {indice}")
        debug(f"HTML del bloque: {bloque.get_attribute('outerHTML')}")

        return {
            "elemento": bloque,
            "texto": texto,
            "html": bloque.get_attribute("outerHTML"),
        }

    return None


def extraer_ocupacion(texto, html=""):
    contenido = f"{texto} {BeautifulSoup(html, 'lxml').get_text(' ', strip=True)}"

    patrones = [
        r"Occupied\s+places?\s*:?\s*(\d+\s*/\s*\d+)",
        r"Booked\s*:?\s*(\d+\s*/\s*\d+)",
        r"Reservadas?\s*:?\s*(\d+\s*/\s*\d+)",
        r"Ocupadas?\s*:?\s*(\d+\s*/\s*\d+)",
        r"Plazas?\s*:?\s*(\d+\s*/\s*\d+)",
        r"\b(\d+\s*/\s*\d+)\b",
    ]

    for patron in patrones:
        match = re.search(
            patron,
            contenido,
            flags=re.IGNORECASE,
        )

        if match:
            return match.group(1).strip()

    return None


def esperar_ocupacion(driver, evento):
    elemento = evento["elemento"]

    def contiene_ocupacion(_):
        try:
            texto = " ".join(elemento.text.split())
            html = elemento.get_attribute("outerHTML")
            return extraer_ocupacion(texto, html)
        except Exception:
            return False

    try:
        ocupacion = WebDriverWait(driver, 10).until(
            contiene_ocupacion
        )
        return ocupacion
    except TimeoutException:
        return None


def calcular_plazas_libres(texto):
    if not texto:
        return None

    texto = texto.strip()

    match = re.search(
        r"(\d+)\s*/\s*(\d+)",
        texto,
    )

    if match:
        reservadas = int(match.group(1))
        totales = int(match.group(2))
        return max(totales - reservadas, 0)

    match = re.search(r"\d+", texto)

    if match:
        return int(match.group(0))

    return None


def enviar_correo(asunto, cuerpo):
    if not (
        EMAIL_FROM
        and EMAIL_PASSWORD
        and EMAIL_TO
    ):
        print(
            "Faltan EMAIL_FROM, EMAIL_PASSWORD o EMAIL_TO; "
            "no se envía correo."
        )
        return

    mensaje = MIMEMultipart()
    mensaje["From"] = EMAIL_FROM
    mensaje["To"] = EMAIL_TO
    mensaje["Subject"] = asunto
    mensaje.attach(MIMEText(cuerpo, "plain"))

    contexto = ssl.create_default_context()

    with smtplib.SMTP_SSL(
        SMTP_SERVER,
        SMTP_PORT,
        context=contexto,
    ) as servidor:
        servidor.login(
            EMAIL_FROM,
            EMAIL_PASSWORD,
        )
        servidor.sendmail(
            EMAIL_FROM,
            EMAIL_TO,
            mensaje.as_string(),
        )

    print("Correo de aviso enviado.")


def guardar_diagnostico(driver):
    if not DEBUG_SCRAPER:
        return

    try:
        with open(
            "schedule_debug.html",
            "w",
            encoding="utf-8",
        ) as archivo:
            archivo.write(driver.page_source)

        driver.save_screenshot("schedule_debug.png")

        debug("Guardado schedule_debug.html")
        debug("Guardado schedule_debug.png")
    except Exception as exc:
        debug(
            f"No se pudo guardar el diagnóstico: {exc!r}"
        )


def ejecutar(headless=True, keep_browser=False):
    if not USER or not PASSWORD:
        raise RuntimeError(
            "Las variables USUARIO y CONTRASENA "
            "no están definidas."
        )

    ahora = datetime.now(ZONA_HORARIA)

    print(
        "Inicio:",
        ahora.strftime("%Y-%m-%d %H:%M:%S %Z"),
    )

    driver = build_driver(headless=headless)

    try:
        realizar_login(driver)

        driver.get(SCHEDULE_URL)
        esperar_agenda(driver)

        cerrar_promocion(driver)
        aceptar_cookies(driver)

        debug(f"URL de la agenda: {driver.current_url}")
        debug(f"Título: {driver.title}")
        debug(f"Ventana: {driver.get_window_size()}")
        debug(
            "User-Agent: "
            + driver.execute_script(
                "return navigator.userAgent"
            )
        )

        if not seleccionar_miercoles(driver):
            guardar_diagnostico(driver)
            return

        evento = buscar_endurance(driver)

        if not evento:
            guardar_diagnostico(driver)
            print(
                'No se encontró un evento "ENDURANCE" '
                f"a las {HORA_INICIO}."
            )
            return

        print(
            f"Se encontró {CLASE_BUSCADA} "
            f"de {HORA_INICIO} a {HORA_FIN}."
        )

        ocupacion = extraer_ocupacion(
            evento["texto"],
            evento["html"],
        )

        if ocupacion is None:
            ocupacion = esperar_ocupacion(
                driver,
                evento,
            )

        if ocupacion is None:
            guardar_diagnostico(driver)
            print(
                "La clase existe, pero la ocupación no aparece "
                "en el DOM cargado."
            )
            print(
                'Es posible que sea necesario abrir "Detail" '
                'o "Book" para consultar las plazas.'
            )
            return

        print(f"Ocupación detectada: {ocupacion}")

        libres = calcular_plazas_libres(ocupacion)

        print(
            f"Plazas libres interpretadas: {libres}"
        )

        if (
            libres is not None
            and libres <= UMBRAL_PLAZAS_LIBRES
        ):
            enviar_correo(
                asunto=(
                    "🏋️ Quedan pocas plazas para "
                    f"{CLASE_BUSCADA} {HORA_INICIO}"
                ),
                cuerpo=(
                    f"Quedan {libres} plazas libres para la clase "
                    f"{CLASE_BUSCADA} de las {HORA_INICIO}.\n\n"
                    f"Ocupación mostrada por el sitio: "
                    f"{ocupacion}"
                ),
            )

    finally:
        if keep_browser:
            print(
                "El navegador permanecerá abierto. "
                "Pulsa Enter para cerrarlo."
            )
            input()
        driver.quit()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--visible",
        action="store_true",
        help="Abre Chrome en modo visible para depuración.",
    )

    argumentos = parser.parse_args()

    ejecutar(
        headless=not argumentos.visible,
        keep_browser=argumentos.visible,
    )