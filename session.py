"""Sessao Instagram: Chrome cookies, CDP ou login Playwright."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SESSION_DIR = ROOT / ".session"
COOKIES_FILE = SESSION_DIR / "cookies.txt"
META_FILE = SESSION_DIR / "session.json"
CHROME_DEBUG_PROFILE = SESSION_DIR / "chrome-debug-profile"
DEBUG_PORT = 9333


def _local_appdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))


def find_chrome_exe() -> Path | None:
    candidates = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        / "Google"
        / "Chrome"
        / "Application"
        / "chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        / "Google"
        / "Chrome"
        / "Application"
        / "chrome.exe",
        _local_appdata() / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        / "Microsoft"
        / "Edge"
        / "Application"
        / "msedge.exe",
    ]
    for p in candidates:
        if p.is_file():
            return p
    which = shutil.which("chrome") or shutil.which("msedge")
    return Path(which) if which else None


def chrome_user_data_dirs() -> list[Path]:
    base = _local_appdata()
    candidates = [
        base / "Google" / "Chrome" / "User Data",
        base / "Google" / "Chrome Beta" / "User Data",
        base / "Microsoft" / "Edge" / "User Data",
        base / "BraveSoftware" / "Brave-Browser" / "User Data",
    ]
    return [p for p in candidates if p.is_dir()]


def read_devtools_active_port(user_data: Path) -> tuple[int, str] | None:
    path = user_data / "DevToolsActivePort"
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    except OSError:
        return None
    if not lines:
        return None
    try:
        port = int(lines[0].strip())
    except ValueError:
        return None
    wspath = lines[1].strip() if len(lines) > 1 else ""
    return port, wspath


def _port_open(port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def discover_cdp_endpoints() -> list[dict]:
    found: list[dict] = []
    seen: set[int] = set()
    for ud in chrome_user_data_dirs():
        parsed = read_devtools_active_port(ud)
        if not parsed:
            continue
        port, wspath = parsed
        if port in seen or not _port_open(port):
            continue
        seen.add(port)
        browser = "chrome"
        name = str(ud).lower()
        if "edge" in name:
            browser = "edge"
        elif "brave" in name:
            browser = "brave"
        found.append(
            {
                "browser": browser,
                "port": port,
                "wspath": wspath,
                "user_data": str(ud),
            }
        )
    for port in (DEBUG_PORT, 9222):
        if port not in seen and _port_open(port):
            seen.add(port)
            found.append(
                {"browser": "chrome", "port": port, "wspath": "", "user_data": ""}
            )
    return found


def _http_json(url: str, timeout: float = 2.0) -> dict | list | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as res:
            return json.loads(res.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def _cdp_call(ws_url: str, method: str, params: dict | None = None) -> dict:
    import websocket

    # Chrome recente exige Origin permitido (--remote-allow-origins)
    ws = websocket.create_connection(
        ws_url,
        timeout=10,
        suppress_origin=True,
    )
    try:
        msg_id = 1
        ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        deadline = time.time() + 10
        while time.time() < deadline:
            data = json.loads(ws.recv())
            if data.get("id") == msg_id:
                if "error" in data:
                    raise RuntimeError(str(data["error"]))
                return data.get("result") or {}
        raise TimeoutError(f"CDP timeout: {method}")
    finally:
        ws.close()


def capture_cookies_via_cdp(port: int, wspath: str = "") -> list[dict]:
    base = f"http://127.0.0.1:{port}"
    tabs = _http_json(f"{base}/json/list") or _http_json(f"{base}/json")
    ws_url = None
    if isinstance(tabs, list):
        for tab in tabs:
            url = (tab.get("url") or "").lower()
            if "instagram.com" in url and tab.get("webSocketDebuggerUrl"):
                ws_url = tab["webSocketDebuggerUrl"]
                break
        if not ws_url:
            for tab in tabs:
                if tab.get("type") == "page" and tab.get("webSocketDebuggerUrl"):
                    ws_url = tab["webSocketDebuggerUrl"]
                    break
    if not ws_url and wspath:
        path = wspath if wspath.startswith("/") else f"/{wspath}"
        ws_url = f"ws://127.0.0.1:{port}{path}"
    if not ws_url:
        ver = _http_json(f"{base}/json/version")
        if isinstance(ver, dict) and ver.get("webSocketDebuggerUrl"):
            ws_url = ver["webSocketDebuggerUrl"]

    if not ws_url:
        raise RuntimeError(
            "Chrome com debug achado, mas sem aba utilizavel.\n"
            "Abra https://www.instagram.com nesse Chrome e tente de novo."
        )

    cookies: list[dict] = []
    try:
        result = _cdp_call(
            ws_url, "Network.getCookies", {"urls": ["https://www.instagram.com/"]}
        )
        cookies = result.get("cookies") or []
    except Exception:
        cookies = []
    if not cookies:
        try:
            result = _cdp_call(ws_url, "Network.getAllCookies")
            cookies = [
                c
                for c in (result.get("cookies") or [])
                if "instagram" in (c.get("domain") or "").lower()
            ]
        except Exception as e:
            raise RuntimeError(f"Falha CDP ao ler cookies: {e}") from e

    if not any(c.get("name") == "sessionid" for c in cookies):
        raise RuntimeError(
            "Chrome conectado, mas voce ainda nao esta logado no Instagram nessa janela.\n"
            "Faca login em https://www.instagram.com e clique Conectar de novo."
        )
    return cookies


def write_netscape_cookies(cookies: list[dict], path: Path = COOKIES_FILE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Netscape HTTP Cookie File",
        "# Gerado por instagram-baixar. Nao compartilhe este arquivo.",
        "",
    ]
    for c in cookies:
        domain = c.get("domain") or ".instagram.com"
        if not any(d in domain for d in ("instagram", "cdninstagram", "facebook")):
            continue
        flag = "TRUE" if str(domain).startswith(".") else "FALSE"
        cookie_path = c.get("path") or "/"
        secure = "TRUE" if c.get("secure") else "FALSE"
        expires = int(c.get("expires") or c.get("expirationDate") or 0)
        if expires < 0:
            expires = 0
        name = c.get("name") or ""
        value = c.get("value") or ""
        if not name:
            continue
        domain_out = f"#HttpOnly_{domain}" if c.get("httpOnly") else domain
        lines.append(
            f"{domain_out}\t{flag}\t{cookie_path}\t{secure}\t{expires}\t{name}\t{value}"
        )
    if not any("\tsessionid\t" in ln for ln in lines):
        raise RuntimeError("Nenhum cookie sessionid para gravar.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def save_session_meta(source: str, cookies: list[dict]) -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    user = next(
        (str(c.get("value") or "") for c in cookies if c.get("name") == "ds_user_id"),
        "",
    )
    META_FILE.write_text(
        json.dumps(
            {
                "source": source,
                "saved_at": time.time(),
                "ds_user_id": user,
                "cookie_count": len(cookies),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def session_status() -> dict:
    ok = COOKIES_FILE.is_file() and "sessionid" in COOKIES_FILE.read_text(
        encoding="utf-8", errors="replace"
    )
    meta = {}
    if META_FILE.is_file():
        try:
            meta = json.loads(META_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
    return {"logged_in": ok, "cookies_file": str(COOKIES_FILE), **meta}


def capture_from_browser_cookie3() -> list[dict]:
    """Le cookies do Chrome/Edge instalado (sem CDP). Pode falhar se o Chrome estiver aberto."""
    import browser_cookie3

    errors: list[str] = []
    for loader_name in ("chrome", "edge", "brave"):
        loader = getattr(browser_cookie3, loader_name, None)
        if not loader:
            continue
        try:
            jar = loader(domain_name="instagram.com")
            cookies = []
            for c in jar:
                cookies.append(
                    {
                        "name": c.name,
                        "value": c.value,
                        "domain": c.domain,
                        "path": c.path or "/",
                        "secure": bool(c.secure),
                        "httpOnly": True if c.name == "sessionid" else False,
                        "expires": int(c.expires or 0),
                    }
                )
            if any(c["name"] == "sessionid" for c in cookies):
                return cookies
            errors.append(f"{loader_name}: sem sessionid ({len(cookies)} cookies)")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{loader_name}: {e}")
            continue
    raise RuntimeError(
        "Nao consegui ler cookies do Chrome/Edge (browser aberto costuma travar o arquivo).\n"
        + "\n".join(errors)
        + "\nUse 'Abrir navegador e logar' se a sessao automatica falhar."
    )


def _popen_chrome(cmd: list[str], *, hide_console: bool = True) -> None:
    kwargs = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.name == "nt" and hide_console:
        # so esconde console; janela do Chrome (quando nao-headless) continua visivel
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(cmd, **kwargs)


def stop_debug_chrome() -> None:
    """Encerra Chrome/Edge do perfil de debug do app (libera a porta)."""
    marker = str(CHROME_DEBUG_PROFILE)
    if os.name == "nt":
        # PowerShell: mata so processos com nosso user-data-dir
        safe = marker.replace("'", "''")
        ps = (
            f"$m = [regex]::Escape('{safe}'); "
            "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
            "Where-Object { "
            "  $_.Name -match '^(chrome|msedge)\\.exe$' -and "
            "  $_.CommandLine -and ($_.CommandLine -match $m) "
            "} | ForEach-Object { "
            "  Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue "
            "}"
        )
        try:
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    ps,
                ],
                capture_output=True,
                timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            pass
    else:
        try:
            subprocess.run(
                ["pkill", "-f", marker],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass
    # espera porta liberar
    for _ in range(20):
        if not _port_open(DEBUG_PORT):
            break
        time.sleep(0.2)


def launch_debug_chrome(headless: bool = True) -> None:
    """
    Abre Chrome com remote debugging + perfil do app.
    headless=True: SEM janela (conexao automatica).
    headless=False: janela VISIVEL so pra login manual no Instagram.
    """
    exe = find_chrome_exe()
    if not exe:
        raise RuntimeError("Chrome/Edge nao encontrado neste PC.")
    CHROME_DEBUG_PROFILE.mkdir(parents=True, exist_ok=True)

    # Se a porta ja esta aberta, NAO dispara outro Chrome (evita janela fantasma).
    if _port_open(DEBUG_PORT):
        if headless:
            return
        # pediu visivel mas ja tem instancia: reinicia no modo visivel
        stop_debug_chrome()

    debug_args = [
        f"--remote-debugging-port={DEBUG_PORT}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-features=Translate,MediaRouter",
        "--mute-audio",
    ]
    if headless:
        debug_args += [
            "--headless=new",
            "--disable-gpu",
            "--window-size=1280,860",
            "--hide-scrollbars",
        ]

    _popen_chrome(
        [
            str(exe),
            *debug_args,
            f"--user-data-dir={CHROME_DEBUG_PROFILE}",
            "https://www.instagram.com/",
        ],
        hide_console=True,
    )
    for _ in range(50):
        if _port_open(DEBUG_PORT):
            time.sleep(0.8)  # deixa a home carregar um pouco
            return
        time.sleep(0.25)
    raise RuntimeError(
        f"Chrome nao abriu a porta de debug {DEBUG_PORT}. "
        "Feche outras instancias e tente de novo."
    )


def wait_and_capture_cdp(
    port: int = DEBUG_PORT,
    timeout_sec: int = 180,
    *,
    visible_hint: bool = False,
) -> list[dict]:
    deadline = time.time() + timeout_sec
    last = "aguardando sessao..."
    while time.time() < deadline:
        try:
            return capture_cookies_via_cdp(port)
        except Exception as e:  # noqa: BLE001
            last = str(e)
            time.sleep(1.2)
    if visible_hint:
        raise RuntimeError(
            "Timeout esperando login no Instagram.\n"
            "Na janela do Chrome que abriu, faca login e deixe a home carregar.\n"
            f"Ultimo status: {last}"
        )
    raise RuntimeError(last)


def _has_sessionid(cookies_path: Path = COOKIES_FILE) -> bool:
    if not cookies_path.is_file():
        return False
    try:
        return "sessionid" in cookies_path.read_text(
            encoding="utf-8", errors="replace"
        )
    except OSError:
        return False


def _touch_session_meta(source: str) -> None:
    meta: dict = {}
    if META_FILE.is_file():
        try:
            meta = json.loads(META_FILE.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    meta["source"] = source
    meta["saved_at"] = time.time()
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    META_FILE.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def session_cookies_work(cookies_path: Path = COOKIES_FILE) -> bool:
    """True se cookies.txt ainda autenticam no Instagram (sem abrir Chrome)."""
    if not _has_sessionid(cookies_path):
        return False
    try:
        from instagram_api import _session_from_cookies

        s = _session_from_cookies(cookies_path)
        r = s.get(
            "https://www.instagram.com/api/v1/accounts/current_user/",
            timeout=20,
        )
        if r.status_code != 200:
            return False
        data = r.json() if r.text and r.text[:1] in "{[" else {}
        return bool((data or {}).get("user") or (data or {}).get("status") == "ok")
    except Exception:
        return False


def capture_from_chrome(*, allow_visible: bool = False) -> Path:
    """
    Mantem/renova sessao SEMPRE em modo escondido (headless).
    Nunca abre janela do Chrome daqui.

    Se ja autenticado: nao sobe browser nenhum.
    Se precisa login na tela: use login_with_playwright (botao Abrir navegador).
    allow_visible e ignorado (mantido so por compat).
    """
    _ = allow_visible  # compat: conexao automatica nunca mostra janela
    errors: list[str] = []

    # 1) API OK com cookies salvos -> nao abre nada
    if session_cookies_work():
        _touch_session_meta("cookies-valid")
        return COOKIES_FILE

    # 2) Ja tem sessionid local: nao abre Chrome
    if _has_sessionid():
        _touch_session_meta("cookies-kept")
        return COOKIES_FILE

    # 3) Le cookies do perfil em disco (nao abre o navegador)
    try:
        cookies = capture_from_browser_cookie3()
        write_netscape_cookies(cookies)
        save_session_meta("browser_cookie3", cookies)
        if _has_sessionid() or session_cookies_work():
            return COOKIES_FILE
        errors.append("browser_cookie3: sem sessionid util")
    except Exception as e:  # noqa: BLE001
        errors.append(f"browser_cookie3: {e}")

    if _has_sessionid():
        _touch_session_meta("cookies-from-disk")
        return COOKIES_FILE

    # 4) Chrome HEADLESS do app (escondido; nunca visivel)
    try:
        launch_debug_chrome(headless=True)
        cookies = wait_and_capture_cdp(
            DEBUG_PORT, timeout_sec=28, visible_hint=False
        )
        write_netscape_cookies(cookies)
        save_session_meta(f"cdp-headless:{DEBUG_PORT}", cookies)
        if session_cookies_work() or _has_sessionid():
            return COOKIES_FILE
        errors.append("headless: perfil do app sem login no Instagram")
    except Exception as e:  # noqa: BLE001
        errors.append(f"headless: {e}")

    if _has_sessionid():
        return COOKIES_FILE

    raise RuntimeError(
        "Sem sessao do Instagram (Chrome ficou escondido).\n"
        "Clique em 'Abrir navegador e logar' pra autenticar uma vez.\n"
        + "\n".join(errors[-6:])
    )


def login_with_playwright(timeout_sec: int = 300) -> Path:
    """Abre Chrome VISIVEL (persistente) pra login manual quando a sessao morreu."""
    from playwright.sync_api import sync_playwright

    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    profile = SESSION_DIR / "browser-profile"
    profile.mkdir(exist_ok=True)

    with sync_playwright() as p:
        launch_kwargs = dict(
            user_data_dir=str(profile),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 860},
            locale="pt-BR",
        )
        try:
            context = p.chromium.launch_persistent_context(
                channel="chrome", **launch_kwargs
            )
        except Exception:
            context = p.chromium.launch_persistent_context(**launch_kwargs)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            cookies = context.cookies("https://www.instagram.com")
            if any(c.get("name") == "sessionid" for c in cookies):
                norm = [
                    {
                        "name": c.get("name"),
                        "value": c.get("value"),
                        "domain": c.get("domain"),
                        "path": c.get("path") or "/",
                        "secure": bool(c.get("secure")),
                        "httpOnly": bool(c.get("httpOnly")),
                        "expires": int(c.get("expires") or 0),
                    }
                    for c in cookies
                ]
                write_netscape_cookies(norm)
                save_session_meta("playwright", norm)
                context.close()
                return COOKIES_FILE
            time.sleep(1.2)
        context.close()
    raise TimeoutError(
        "Login nao concluido a tempo. Faca login na janela e clique de novo."
    )


def clear_session() -> None:
    if COOKIES_FILE.exists():
        COOKIES_FILE.unlink()
    if META_FILE.exists():
        META_FILE.unlink()
