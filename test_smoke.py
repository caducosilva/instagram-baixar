#!/usr/bin/env python3
"""Testes automaticos do que da pra validar sem login real do usuario."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def ok(name: str) -> None:
    print(f"[OK] {name}")


def fail(name: str, err: Exception) -> None:
    print(f"[FAIL] {name}: {err}")
    raise SystemExit(1)


def main() -> None:
    from downloader import _bin
    from instagram_api import parse_post_url, parse_username_or_url
    from session import (
        COOKIES_FILE,
        DEBUG_PORT,
        SESSION_DIR,
        _port_open,
        capture_cookies_via_cdp,
        clear_session,
        discover_cdp_endpoints,
        find_chrome_exe,
        launch_debug_chrome,
        session_status,
        write_netscape_cookies,
    )

    # imports app
    import app  # noqa: F401

    ok("imports")

    assert _bin("gallery-dl")
    assert _bin("yt-dlp")
    ok("binarios gallery-dl/yt-dlp")

    assert parse_username_or_url("@cadu") == "cadu"
    assert parse_username_or_url("https://www.instagram.com/cadu/") == "cadu"
    assert "ABC" in (parse_post_url("https://www.instagram.com/p/ABC123/") or "")
    ok("parse urls")

    assert find_chrome_exe() is not None
    ok(f"chrome exe: {find_chrome_exe()}")

    SESSION_DIR.mkdir(exist_ok=True)
    # Nao destruir sessao real do usuario: usa arquivo temporario
    from session import write_netscape_cookies as _write
    import session as session_mod

    tmp_cookies = SESSION_DIR / "cookies_smoke_tmp.txt"
    real_cookies = session_mod.COOKIES_FILE
    real_meta = session_mod.META_FILE
    backup = None
    if real_cookies.is_file():
        backup = real_cookies.read_text(encoding="utf-8")
    _write(
        [
            {
                "name": "sessionid",
                "value": "smoke",
                "domain": ".instagram.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
                "expires": 9999999999,
            }
        ],
        path=tmp_cookies,
    )
    assert "sessionid" in tmp_cookies.read_text(encoding="utf-8")
    tmp_cookies.unlink(missing_ok=True)
    if backup is not None:
        real_cookies.write_text(backup, encoding="utf-8")
    ok("cookies write (temp, sessao real preservada)")

    # Lanca Chrome debug e valida CDP HTTP
    launch_debug_chrome()
    ready = False
    for _ in range(40):
        if _port_open(DEBUG_PORT):
            ready = True
            break
        time.sleep(0.25)
    if not ready:
        fail("chrome debug port", RuntimeError(f"porta {DEBUG_PORT} nao abriu"))
    ok(f"chrome debug na porta {DEBUG_PORT}")

    eps = discover_cdp_endpoints()
    if not any(e["port"] == DEBUG_PORT for e in eps):
        fail("discover_cdp", RuntimeError(f"endpoints={eps}"))
    ok(f"discover_cdp: {eps}")

    # Sem login, deve falhar com mensagem clara (nao crash)
    try:
        capture_cookies_via_cdp(DEBUG_PORT)
        # se o usuario ja estiver logado no perfil debug, isso passa — tambem ok
        ok("cdp cookies (ja logado no perfil debug)")
    except RuntimeError as e:
        msg = str(e).lower()
        if "logado" in msg or "sessionid" in msg or "aba" in msg:
            ok(f"cdp sem login retorna erro claro: {e}")
        else:
            fail("cdp erro inesperado", e)

    print("\nSMOKE OK — fluxos basicos validados.")
    print("Proximo passo manual: no Chrome que abriu, logue no Instagram e clique Conectar Chrome no app.")


if __name__ == "__main__":
    main()
