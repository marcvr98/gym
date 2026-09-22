import argparse
import os
import re
import smtplib
import ssl
import time

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


# ---------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------

LOGIN_URL = "https://login.aimharder.com"
BASE_URL = "https://wodboxtraining.aimharder.com"
SCHEDULE_URL = f"{BASE_URL}/schedule"

USERNAME_SELECTOR = 'input[name="username"]'
PASSWORD_SELECTOR = 'input[name="password"]'
SUBMIT_SELECTOR = 'button[type="submit"]'

CLASE_BUSCADA = "ENDURANCE"
HORA_INICIO = "19:15"
HORA_FIN = "20:15"

TIMEOUT = 30
UMBRAL_PLAZAS_LIBRES = 2

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465

ZONA_HORARIA = ZoneInfo("Europe/Madrid")

load_dotenv()

USER = os.getenv("USUARIO")
PASSWORD = os.getenv("CONTRASENA")

EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_TO = os.getenv("EMAIL_TO")

DEBUG_SCRAPER = os.getenv(
    "DEBUG_SCRAPER",
    "false",
).lower() in {
    "1",
    "true",
    "yes",
    "on",
}

DAY_CHECK_RESULT = None


# ---------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------

def debug(mensaje):
    if DEBUG_SCRAPER:
        print(f"[DEBUG] {mensaje}")


def guardar_archivos_diagnostico(driver, prefijo):
    if not DEBUG_SCRAPER:
        return

    try:
        ruta_html = f"{prefijo}.html"
        ruta_imagen = f"{prefijo}.png"

        with open(
            ruta_html,
            "w",
            encoding="utf-8",
        ) as archivo:
            archivo.write(driver.page_source)

        driver.save_screenshot(ruta_imagen)

        debug(f"Diagnóstico HTML guardado en {ruta_html}")
        debug(f"Captura guardada en {ruta_imagen}")

    except Exception as exc:
        debug(
            f"No se pudieron guardar los archivos "
            f"de diagnóstico: {exc!r}"
        )


# ---------------------------------------------------------------------
# Navegador
# ---------------------------------------------------------------------

def build_driver(headless=True):
    options = webdriver.ChromeOptions()

    if headless:
        options.add_argument("--headless=new")

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-networking")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--force-device-scale-factor=1")
    options.add_argument("--lang=es-ES")

    options.add_experimental_option(
        "prefs",
        {
            "intl.accept_languages": "es-ES,es,en",
        },
    )

    driver = webdriver.Chrome(
        service=ChromeService(
            ChromeDriverManager().install()
        ),
        options=options,
    )

    driver.set_window_size(1920, 1080)
    driver.set_page_load_timeout(60)

    return driver


# ---------------------------------------------------------------------
# Cookies y ventanas
# ---------------------------------------------------------------------

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
            debug(
                f"No se pudo comprobar un botón "
                f"de cookies: {exc!r}"
            )

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
        debug(
            f"No se pudo cerrar la promoción: {exc!r}"
        )

    return False


# ---------------------------------------------------------------------
# Inicio de sesión
# ---------------------------------------------------------------------

def realizar_login(driver):
    driver.get(LOGIN_URL)

    WebDriverWait(driver, TIMEOUT).until(
        lambda d: d.execute_script(
            "return document.readyState"
        ) == "complete"
    )

    aceptar_cookies(driver)

    try:
        usuario = WebDriverWait(
            driver,
            TIMEOUT,
        ).until(
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
            usuario = driver.find_element(
                By.ID,
                "username",
            )

            contrasena = driver.find_element(
                By.ID,
                "password",
            )

        except Exception as exc:
            guardar_archivos_diagnostico(
                driver,
                "login_sin_campos",
            )

            raise RuntimeError(
                "No se encontraron los campos "
                "de inicio de sesión."
            ) from exc

    usuario.clear()
    usuario.send_keys(USER)

    contrasena.clear()
    contrasena.send_keys(PASSWORD)

    boton = WebDriverWait(
        driver,
        TIMEOUT,
    ).until(
        lambda d: d.find_element(
            By.CSS_SELECTOR,
            SUBMIT_SELECTOR,
        )
    )

    url_antes = driver.current_url.rstrip("/")

    debug(f"URL antes del login: {driver.current_url}")

    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center'});",
        boton,
    )

    boton.click()

    try:
        WebDriverWait(
            driver,
            TIMEOUT,
            poll_frequency=0.5,
        ).until(
            lambda d: (
                d.current_url.rstrip("/") != url_antes
                or not d.find_elements(
                    By.CSS_SELECTOR,
                    USERNAME_SELECTOR,
                )
            )
        )

    except TimeoutException as exc:
        print(
            "[ERROR] El inicio de sesión "
            "no terminó correctamente."
        )
        print(
            f"[ERROR] URL actual: {driver.current_url}"
        )

        try:
            mensajes = driver.find_elements(
                By.CSS_SELECTOR,
                ".alert, .error, .errorMessage, "
                ".validation-summary-errors",
            )

            for mensaje in mensajes:
                texto = mensaje.text.strip()

                if mensaje.is_displayed() and texto:
                    print(
                        f"[ERROR] Mensaje de la web: {texto}"
                    )

        except Exception:
            pass

        guardar_archivos_diagnostico(
            driver,
            "login_error",
        )

        raise RuntimeError(
            "El login no se completó dentro "
            f"de {TIMEOUT} segundos."
        ) from exc

    # Esperar a que terminen posibles redirecciones.
    time.sleep(2)

    debug(
        f"URL después del login: {driver.current_url}"
    )


# ---------------------------------------------------------------------
# Carga de la agenda
# ---------------------------------------------------------------------

def esperar_agenda(driver):
    def agenda_disponible(d):
        url = d.current_url.lower()

        if "login.aimharder.com" in url:
            return False

        return d.execute_script(
            """
            return Boolean(
                document.getElementById("clasesDiaSel")
                || document.querySelector(".weekNavigator")
                || document.querySelector(
                    "div[id^='bloqueClass']"
                )
            );
            """
        )

    try:
        WebDriverWait(
            driver,
            TIMEOUT,
            poll_frequency=0.5,
        ).until(agenda_disponible)

    except TimeoutException as exc:
        print(
            "[ERROR] La agenda no terminó de cargar."
        )
        print(
            f"[ERROR] URL actual: {driver.current_url}"
        )

        guardar_archivos_diagnostico(
            driver,
            "agenda_error",
        )

        if (
            "login.aimharder.com"
            in driver.current_url.lower()
        ):
            raise RuntimeError(
                "La web volvió a la página de login. "
                "Comprueba USUARIO y CONTRASENA."
            ) from exc

        raise RuntimeError(
            "La página abrió, pero no apareció "
            "la agenda."
        ) from exc


# ---------------------------------------------------------------------
# Selección del miércoles
# ---------------------------------------------------------------------

def obtener_dias_semana(driver):
    return driver.execute_script(
        """
        return Array.from(
            document.querySelectorAll("#weekDays a")
        ).map((elemento, indice) => {
            const onclick =
                elemento.getAttribute("onclick") || "";

            const coincidencia = onclick.match(
                /weekSelDay\\(["'](\\d{8})["']\\)/
            );

            return {
                indice: indice,
                texto: (
                    elemento.innerText
                    || elemento.textContent
                    || ""
                ).trim(),
                clases:
                    elemento.getAttribute("class") || "",
                fecha: coincidencia
                    ? coincidencia[1]
                    : null
            };
        });
        """
    )


def fecha_activa(driver):
    return driver.execute_script(
        """
        const dias = Array.from(
            document.querySelectorAll("#weekDays a")
        );

        for (const elemento of dias) {
            const clases = (
                elemento.getAttribute("class") || ""
            ).split(/\\s+/);

            if (!clases.includes("active")) {
                continue;
            }

            const onclick =
                elemento.getAttribute("onclick") || "";

            const coincidencia = onclick.match(
                /weekSelDay\\(["'](\\d{8})["']\\)/
            );

            return coincidencia
                ? coincidencia[1]
                : null;
        }

        return null;
        """
    )


def hacer_click_en_dia(driver, indice):
    return driver.execute_script(
        """
        const indice = arguments[0];

        const dias = Array.from(
            document.querySelectorAll("#weekDays a")
        );

        if (!dias[indice]) {
            return false;
        }

        dias[indice].scrollIntoView({
            block: "center"
        });

        dias[indice].click();

        return true;
        """,
        indice,
    )


def clase_objetivo_cargada(driver):
    return driver.execute_script(
        """
        const hora = arguments[0];
        const clase = arguments[1].toUpperCase();

        const bloques = Array.from(
            document.querySelectorAll(
                "div[id^='bloqueClass']"
            )
        );

        return bloques.some((bloque) => {
            const texto = (
                bloque.innerText
                || bloque.textContent
                || ""
            )
                .replace(/\\s+/g, " ")
                .trim()
                .toUpperCase();

            return (
                texto.includes(hora)
                && texto.includes(clase)
            );
        });
        """,
        HORA_INICIO,
        CLASE_BUSCADA,
    )


def seleccionar_miercoles(driver):
    global DAY_CHECK_RESULT

    try:
        WebDriverWait(
            driver,
            TIMEOUT,
            poll_frequency=0.5,
        ).until(
            lambda d: len(obtener_dias_semana(d)) > 0
        )

    except TimeoutException as exc:
        guardar_archivos_diagnostico(
            driver,
            "sin_dias_semana",
        )

        raise RuntimeError(
            "No se encontraron los días "
            "del navegador semanal."
        ) from exc

    dias = obtener_dias_semana(driver)

    activo = None

    for dia in dias:
        clases = dia.get("clases", "").split()

        if "active" in clases:
            activo = dia
            break

    if activo is None:
        guardar_archivos_diagnostico(
            driver,
            "sin_dia_activo",
        )

        raise RuntimeError(
            "No se pudo identificar el día activo."
        )

    active_index = activo["indice"]

    debug(
        f"Día activo: índice={active_index}, "
        f"fecha={activo.get('fecha')}, "
        f"texto={activo.get('texto')!r}"
    )

    # Índices esperados:
    # 0 = lunes
    # 1 = martes
    # 2 = miércoles
    # 3 = jueves
    # etc.
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

    elif active_index == 1:
        indice_miercoles = active_index + 1

        if len(dias) <= indice_miercoles:
            raise RuntimeError(
                "No existe un enlace para el miércoles."
            )

        objetivo = dias[indice_miercoles]
        fecha_miercoles = objetivo.get("fecha")

        if not fecha_miercoles:
            raise RuntimeError(
                "No se pudo determinar la fecha "
                "del miércoles."
            )

        print(
            "El día activo parece ser martes; "
            "selecciono el siguiente día (miércoles)."
        )

        debug(
            f"Fecha objetivo del miércoles: "
            f"{fecha_miercoles}, "
            f"texto={objetivo.get('texto')!r}"
        )

        click_realizado = hacer_click_en_dia(
            driver,
            indice_miercoles,
        )

        if not click_realizado:
            raise RuntimeError(
                "No se pudo pulsar el miércoles."
            )

        debug(
            "Esperando a que la agenda "
            "del miércoles cargue..."
        )

        try:
            WebDriverWait(
                driver,
                TIMEOUT,
                poll_frequency=0.5,
            ).until(
                lambda d: fecha_activa(d)
                == fecha_miercoles
            )

        except TimeoutException as exc:
            guardar_archivos_diagnostico(
                driver,
                "miercoles_no_activo",
            )

            raise RuntimeError(
                "Se pulsó el miércoles, pero no pasó "
                "a ser el día activo."
            ) from exc

        DAY_CHECK_RESULT = "clicked_to_wednesday"

    else:
        DAY_CHECK_RESULT = "before_tuesday"

        print(
            "El día activo es anterior al martes. "
            "No se cambiará automáticamente "
            "al miércoles."
        )

        return False

    # Esperar a que aparezcan bloques en el DOM actual.
    try:
        WebDriverWait(
            driver,
            TIMEOUT,
            poll_frequency=0.5,
        ).until(
            lambda d: d.execute_script(
                """
                return document.querySelectorAll(
                    "div[id^='bloqueClass']"
                ).length > 0;
                """
            )
        )

    except TimeoutException as exc:
        guardar_archivos_diagnostico(
            driver,
            "miercoles_sin_bloques",
        )

        raise RuntimeError(
            "El miércoles está seleccionado, "
            "pero no aparecieron bloques de clases."
        ) from exc

    # Esperar específicamente a la clase buscada.
    try:
        WebDriverWait(
            driver,
            TIMEOUT,
            poll_frequency=0.5,
        ).until(clase_objetivo_cargada)

    except TimeoutException:
        print(
            f"[ERROR] La agenda del miércoles cargó, "
            f"pero no apareció {CLASE_BUSCADA} "
            f"a las {HORA_INICIO}."
        )

        guardar_archivos_diagnostico(
            driver,
            "miercoles_sin_endurance",
        )

        return False

    # Margen para peticiones AJAX adicionales.
    time.sleep(2)

    return True


# ---------------------------------------------------------------------
# Búsqueda de la clase
# ---------------------------------------------------------------------

def buscar_endurance(driver):
    evento = driver.execute_script(
        """
        const horaInicio = arguments[0];
        const horaFin = arguments[1];
        const clase = arguments[2].toUpperCase();

        const bloques = Array.from(
            document.querySelectorAll(
                "div[id^='bloqueClass']"
            )
        );

        for (
            let indice = 0;
            indice < bloques.length;
            indice++
        ) {
            const bloque = bloques[indice];

            const texto = (
                bloque.innerText
                || bloque.textContent
                || ""
            )
                .replace(/\\s+/g, " ")
                .trim();

            const textoMayusculas =
                texto.toUpperCase();

            if (
                texto.includes(horaInicio)
                && texto.includes(horaFin)
                && textoMayusculas.includes(clase)
            ) {
                return {
                    indice: indice,
                    texto: texto,
                    html: bloque.outerHTML
                };
            }
        }

        return null;
        """,
        HORA_INICIO,
        HORA_FIN,
        CLASE_BUSCADA,
    )

    if evento:
        debug(
            f"ENDURANCE encontrado en bloque "
            f"{evento['indice']}"
        )
        debug(
            f"Texto del bloque: {evento['texto']}"
        )
        debug(
            f"HTML del bloque: {evento['html']}"
        )

    return evento


# ---------------------------------------------------------------------
# Ocupación y plazas
# ---------------------------------------------------------------------

def extraer_ocupacion(texto, html=""):
    texto_html = BeautifulSoup(
        html,
        "lxml",
    ).get_text(
        " ",
        strip=True,
    )

    contenido = f"{texto} {texto_html}"

    patrones = [
        (
            r"Occupied\s+places?\s*:?\s*"
            r"(\d+\s*/\s*\d+)"
        ),
        (
            r"Booked\s*:?\s*"
            r"(\d+\s*/\s*\d+)"
        ),
        (
            r"Reservadas?\s*:?\s*"
            r"(\d+\s*/\s*\d+)"
        ),
        (
            r"Ocupadas?\s*:?\s*"
            r"(\d+\s*/\s*\d+)"
        ),
        (
            r"Plazas?\s*:?\s*"
            r"(\d+\s*/\s*\d+)"
        ),
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


def esperar_ocupacion(driver):
    def consultar_ocupacion(d):
        evento = buscar_endurance(d)

        if not evento:
            return False

        return (
            extraer_ocupacion(
                evento["texto"],
                evento["html"],
            )
            or False
        )

    try:
        return WebDriverWait(
            driver,
            10,
            poll_frequency=0.5,
        ).until(consultar_ocupacion)

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

        return max(
            totales - reservadas,
            0,
        )

    match = re.search(r"\d+", texto)

    if match:
        return int(match.group(0))

    return None


# ---------------------------------------------------------------------
# Correo
# ---------------------------------------------------------------------

def enviar_correo(asunto, cuerpo):
    if not (
        EMAIL_FROM
        and EMAIL_PASSWORD
        and EMAIL_TO
    ):
        print(
            "Faltan EMAIL_FROM, EMAIL_PASSWORD "
            "o EMAIL_TO; no se envía correo."
        )
        return False

    mensaje = MIMEMultipart()
    mensaje["From"] = EMAIL_FROM
    mensaje["To"] = EMAIL_TO
    mensaje["Subject"] = asunto

    mensaje.attach(
        MIMEText(
            cuerpo,
            "plain",
            "utf-8",
        )
    )

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
    return True

# ---------------------------------------------------------------------
# Ejecución
# ---------------------------------------------------------------------

def ejecutar(
    headless=True,
    keep_browser=False,
):
    if not USER or not PASSWORD:
        raise RuntimeError(
            "Las variables USUARIO y CONTRASENA "
            "no están definidas."
        )

    ahora = datetime.now(ZONA_HORARIA)

    print(
        "Inicio:",
        ahora.strftime(
            "%Y-%m-%d %H:%M:%S %Z"
        ),
    )

    driver = build_driver(
        headless=headless,
    )

    try:
        realizar_login(driver)

        driver.get(SCHEDULE_URL)

        esperar_agenda(driver)
        cerrar_promocion(driver)
        aceptar_cookies(driver)

        debug(
            f"URL de la agenda: {driver.current_url}"
        )
        debug(f"Título: {driver.title}")
        debug(
            f"Ventana: {driver.get_window_size()}"
        )
        debug(
            "User-Agent: "
            + driver.execute_script(
                "return navigator.userAgent;"
            )
        )

        if not seleccionar_miercoles(driver):
            guardar_archivos_diagnostico(
                driver,
                "seleccion_dia_final",
            )
            return

        evento = buscar_endurance(driver)

        if not evento:
            guardar_archivos_diagnostico(
                driver,
                "endurance_no_encontrado",
            )

            print(
                f'No se encontró "{CLASE_BUSCADA}" '
                f"de {HORA_INICIO} a {HORA_FIN}."
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
            debug(
                "La ocupación todavía no aparece; "
                "se esperará hasta 10 segundos."
            )

            ocupacion = esperar_ocupacion(
                driver
            )

        if ocupacion is None:
            guardar_archivos_diagnostico(
                driver,
                "endurance_sin_ocupacion",
            )

            print(
                "La clase existe, pero la ocupación "
                "no aparece en el DOM cargado."
            )
            print(
                'Es posible que sea necesario abrir '
                '"Detail" o "Book" para consultar '
                "las plazas."
            )
            return

        print(
            f"Ocupación detectada: {ocupacion}"
        )

        libres = calcular_plazas_libres(
            ocupacion
        )

        print(
            f"Plazas libres interpretadas: {libres}"
        )

        if (
            libres is not None
            and libres <= UMBRAL_PLAZAS_LIBRES
        ):
            enviado = enviar_correo(
                asunto=(
                    "🏋️ Quedan pocas plazas para "
                    f"{CLASE_BUSCADA} {HORA_INICIO}"
                ),
                cuerpo=(
                    f"Quedan {libres} plazas libres "
                    f"para la clase {CLASE_BUSCADA} "
                    f"de las {HORA_INICIO}.\n\n"
                    f"Ocupación mostrada por el sitio: "
                    f"{ocupacion}"
                ),
            )

            if enviado:
                github_output = os.getenv("GITHUB_OUTPUT")
                if github_output:
                    with open(github_output, "a") as f:
                        f.write(
                            "mail_sent=true\n"
                        )

    except Exception:
        guardar_archivos_diagnostico(
            driver,
            "error_inesperado",
        )
        raise

    finally:
        if keep_browser:
            print(
                "El navegador permanecerá abierto. "
                "Pulsa Enter para cerrarlo."
            )
            input()

        driver.quit()


# ---------------------------------------------------------------------
# Entrada principal
# ---------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--visible",
        action="store_true",
        help=(
            "Abre Chrome en modo visible "
            "para depuración."
        ),
    )

    argumentos = parser.parse_args()

    ejecutar(
        headless=not argumentos.visible,
        keep_browser=argumentos.visible,
    )