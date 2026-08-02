"""Baixa midia via gallery-dl / yt-dlp / CDN direta, separados por perfil."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from session import COOKIES_FILE, ROOT

DEFAULT_OUT = ROOT / "downloads"
DONE_NAME = ".baixados.txt"
ARCHIVE_NAME = ".archive.txt"


def _is_cdn_url(url: str) -> bool:
    u = (url or "").lower()
    return any(
        x in u
        for x in (
            "cdninstagram.com",
            "fbcdn.net",
            "scontent.",
            "instagram.com/v/",
        )
    )


def _expand_urls(
    urls: list[str],
    cookies: Path,
    on_line=None,
) -> tuple[list[str], str | None, dict[str, str]]:
    """
    Expande URL de destaque ou post/reel em URLs CDN/DASH diretas.
    Retorna (urls, username, audio_por_shortcode).
    """
    from instagram_api import (
        fetch_media_by_url,
        list_highlight_url,
        parse_highlight_id,
        parse_post_url,
        shortcode_from_post_url,
    )

    expanded: list[str] = []
    audio_map: dict[str, str] = {}
    owner: str | None = None

    def _add_item(m, title: str = "") -> bool:
        target = (m.media_url or "").strip()
        if not target:
            return False
        tag = m.shortcode or hashlib.sha1(target.encode()).hexdigest()[:12]
        if title:
            tag = f"{_safe_stem(title)}_{tag}"
        expanded.append(f"{target}#ig={tag}")
        au = (getattr(m, "audio_url", None) or "").strip()
        if au:
            audio_map[tag] = au
        return True

    for url in urls:
        if parse_highlight_id(url):
            title, items, username = list_highlight_url(url, cookies_path=cookies)
            if username and not owner:
                owner = username
            if on_line:
                who = f" @{username}" if username else ""
                on_line(
                    f"Destaque '{title}'{who}: {len(items)} itens "
                    f"(download direto CDN, 1 por vez)"
                )
            if not items:
                raise RuntimeError(f"Destaque sem itens: {url}")
            added = sum(1 for m in items if _add_item(m, title=title))
            if added == 0:
                raise RuntimeError(
                    f"Destaque '{title}' sem URLs de midia (API nao devolveu CDN). "
                    "Reconecte o Chrome e tente de novo."
                )
            continue

        # post / reel / reels / tv -> resolve CDN/DASH pela API
        if parse_post_url(url) and shortcode_from_post_url(url):
            items, username = fetch_media_by_url(url, cookies_path=cookies)
            if username and not owner:
                owner = username
            has_dash = any((getattr(m, "audio_url", None) or "").strip() for m in items)
            if on_line:
                who = f" @{username}" if username else ""
                q = "DASH maxima" if has_dash else "CDN"
                on_line(
                    f"Post/reel{who}: {len(items)} arquivo(s) "
                    f"(download {q})"
                )
            added = sum(1 for m in items if _add_item(m))
            if added == 0:
                raise RuntimeError(
                    f"Post/reel sem URL CDN: {url}. "
                    "Reconecte o Chrome e tente de novo."
                )
            continue

        expanded.append(url)

    seen: set[str] = set()
    out: list[str] = []
    for u in expanded:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out, owner, audio_map


def _bin(name: str) -> list[str]:
    """Retorna comando invocavel. Prefere `python -m` (sobrevive a mover a pasta)."""
    mod = {"yt-dlp": "yt_dlp", "gallery-dl": "gallery_dl"}.get(name)
    if mod:
        return [sys.executable, "-m", mod]
    scripts = Path(sys.executable).resolve().parent
    for candidate in (scripts / f"{name}.exe", scripts / name):
        if candidate.is_file():
            return [str(candidate)]
    found = shutil.which(name)
    if found:
        return [found]
    raise FileNotFoundError(
        f"{name} nao encontrado. Rode: .venv\\Scripts\\pip install gallery-dl yt-dlp"
    )


def safe_username(name: str) -> str:
    name = (name or "").strip().lstrip("@")
    name = re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE)
    return name or "_avulsos"


def media_out_dir(base: Path | None = None) -> Path:
    """Pasta unica de midias (sem subpasta por @usuario)."""
    dest = Path(base) if base is not None else DEFAULT_OUT
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def profile_out_dir(username: str | None = None, base: Path | None = None) -> Path:
    """Compat: ignora username; tudo vai para a mesma pasta."""
    return media_out_dir(base)


def username_from_url(url: str) -> str | None:
    try:
        path = urlparse(url).path.strip("/")
    except Exception:
        return None
    parts = [p for p in path.split("/") if p]
    if not parts:
        return None
    if parts[0] in ("p", "reel", "reels", "stories", "tv", "explore"):
        return None
    return safe_username(parts[0])


def resolve_uploader(url: str, cookies: Path = COOKIES_FILE) -> str:
    direct = username_from_url(url)
    if direct:
        return direct
    proc = subprocess.run(
        [
            *_bin("yt-dlp"),
            "--cookies",
            str(cookies),
            "--skip-download",
            "--print",
            "%(uploader)s",
            "--no-warnings",
            url,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    lines = (proc.stdout or "").strip().splitlines()
    if lines and lines[0] and lines[0].lower() not in ("na", "none"):
        return safe_username(lines[0])
    return "_avulsos"


def _is_reel(url: str) -> bool:
    u = url.lower()
    return "/reel/" in u or "/reels/" in u or "/tv/" in u


def shortcode_from_url(url: str) -> str | None:
    m = re.search(r"[#&?]ig=([A-Za-z0-9_-]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"/(?:p|reel|tv)/([A-Za-z0-9_-]+)", url, flags=re.I)
    return m.group(1) if m else None


def _strip_ig_frag(url: str) -> str:
    return re.sub(r"[#&?]ig=[A-Za-z0-9_-]+", "", url).rstrip("?#&")


def _ext_from_cdn(url: str, is_video_guess: bool = False) -> str:
    path = urlparse(_strip_ig_frag(url)).path.lower()
    for ext in (".mp4", ".mov", ".webm", ".jpg", ".jpeg", ".png", ".webp"):
        if path.endswith(ext) or f"{ext}?" in (path + "?"):
            return ext.lstrip(".")
    if ".mp4" in path:
        return "mp4"
    if any(x in path for x in (".jpg", ".jpeg", ".png", ".webp")):
        return "jpg"
    return "mp4" if is_video_guess else "jpg"


def _safe_stem(text: str) -> str:
    text = re.sub(r"[^\w.\-]+", "_", (text or "").strip(), flags=re.UNICODE)
    return (text[:80] or "media").strip("._")


def _load_done(out: Path) -> set[str]:
    path = out / DONE_NAME
    if not path.is_file():
        return set()
    codes: set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        code = line.strip()
        if code and not code.startswith("#"):
            codes.add(code)
    return codes


def _mark_done(out: Path, code: str) -> None:
    if not code:
        return
    path = out / DONE_NAME
    with path.open("a", encoding="utf-8") as f:
        f.write(code + "\n")


def _already_have(out: Path, code: str | None, done: set[str]) -> bool:
    if not code:
        return False
    if code in done:
        return True
    # yt-dlp: uploader_SHORTCODE.ext | gallery-dl as vezes embute o code
    for p in out.iterdir():
        if not p.is_file() or p.name.startswith("."):
            continue
        if code in p.name:
            return True
    return False


def _looks_blocked(text: str) -> bool:
    t = (text or "").lower()
    needles = (
        "redirect to home",
        "login_required",
        "checkpoint",
        "challenge",
        "please wait",
        "rate-limit",
        "rate limit",
        "too many",
        "403 forbidden",
        "401 unauthorized",
        "csrf",
    )
    return any(n in t for n in needles)


def _ytdlp_cmd(cookies: Path, out: Path, url: str) -> list[str]:
    archive = out / ARCHIVE_NAME
    return [
        *_bin("yt-dlp"),
        "--cookies",
        str(cookies),
        "-f",
        "bv*+ba/b",
        "--merge-output-format",
        "mp4",
        "--remux-video",
        "mp4",
        "-o",
        str(out / "%(uploader)s_%(id)s.%(ext)s"),
        "--download-archive",
        str(archive),
        "--no-mtime",
        "--no-warnings",
        url,
    ]


def _gallery_cmd(cookies: Path, out: Path, url: str) -> list[str]:
    archive = out / ARCHIVE_NAME
    return [
        *_bin("gallery-dl"),
        "--cookies",
        str(cookies),
        "-d",
        str(out),
        "-o",
        "directory=[]",
        "-o",
        "videos=dash",
        "-o",
        "instagram.videos=dash",
        "--download-archive",
        str(archive),
        "--sleep-request",
        "2",
        url,
    ]


def _run_cmd(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _ffmpeg_bin() -> str | None:
    found = shutil.which("ffmpeg")
    return found


def _download_cdn(
    url: str,
    cookies: Path,
    out: Path,
    code: str | None = None,
    on_line=None,
    audio_url: str | None = None,
) -> tuple[bool, str]:
    """Baixa arquivo direto da CDN. Se audio_url (DASH), junta com ffmpeg."""
    from instagram_api import _session_from_cookies

    clean = _strip_ig_frag(url)
    stem = _safe_stem(code) if code else (
        "cdn_" + hashlib.sha1(clean.encode("utf-8", "replace")).hexdigest()[:16]
    )
    audio = (audio_url or "").strip()
    is_dash = bool(audio)
    ext = "mp4" if is_dash else _ext_from_cdn(
        clean, is_video_guess=(".mp4" in clean.lower())
    )
    dest = out / f"{stem}.{ext}"
    if dest.is_file() and dest.stat().st_size > 1024:
        if on_line:
            on_line(f"Ja existe: {dest.name}")
        return True, f"exists {dest}"

    def _stream_to(path: Path, src: str) -> tuple[bool, str, int]:
        try:
            s = _session_from_cookies(cookies)
            s.headers["Referer"] = "https://www.instagram.com/"
            s.headers["Accept"] = "*/*"
            with s.get(src, stream=True, timeout=180) as r:
                if r.status_code in (401, 403):
                    return False, f"CDN HTTP {r.status_code} (sessao/assinatura)", 0
                if r.status_code != 200:
                    return False, f"CDN HTTP {r.status_code}: {(r.text or '')[:200]}", 0
                tmp = path.with_name(path.name + ".download")
                size = 0
                with tmp.open("wb") as f:
                    for chunk in r.iter_content(chunk_size=256 * 1024):
                        if not chunk:
                            continue
                        f.write(chunk)
                        size += len(chunk)
                if size < 512:
                    try:
                        tmp.unlink(missing_ok=True)
                    except Exception:
                        pass
                    return False, f"arquivo CDN muito pequeno ({size} bytes)", 0
                tmp.replace(path)
                return True, "ok", size
        except Exception as e:
            return False, f"CDN erro: {e}", 0

    if not is_dash:
        ok, msg, size = _stream_to(dest, clean)
        if not ok:
            return False, msg
        if on_line:
            on_line(f"CDN OK: {dest.name} ({size // 1024} KB)")
        return True, f"ok {dest} {size}"

    # DASH: video + audio -> merge
    ff = _ffmpeg_bin()
    if not ff:
        # sem ffmpeg: baixa so o video (pior) e avisa
        if on_line:
            on_line(
                "Aviso: ffmpeg nao encontrado; baixando faixa de video DASH sem audio."
            )
        ok, msg, size = _stream_to(dest, clean)
        if not ok:
            return False, msg
        if on_line:
            on_line(f"CDN video OK (sem audio): {dest.name} ({size // 1024} KB)")
        return True, f"ok {dest} {size} noaudio"

    v_part = out / f"{stem}.__v__.mp4"
    a_part = out / f"{stem}.__a__.m4a"
    merged_part = out / f"{stem}.__merge__.mp4"
    try:
        if on_line:
            on_line(f"DASH maxima: baixando video+audio ({stem})...")
        ok_v, msg_v, size_v = _stream_to(v_part, clean)
        if not ok_v:
            return False, f"video DASH: {msg_v}"
        ok_a, msg_a, size_a = _stream_to(a_part, audio)
        if not ok_a:
            return False, f"audio DASH: {msg_a}"
        cmd = [
            ff,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(v_part),
            "-i",
            str(a_part),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(merged_part),
        ]
        rc, text = _run_cmd(cmd)
        if rc != 0 or not merged_part.is_file() or merged_part.stat().st_size < 1024:
            return False, f"ffmpeg merge falhou: {(text or '')[-400:]}"
        merged_part.replace(dest)
        size = dest.stat().st_size
        if on_line:
            on_line(
                f"DASH OK: {dest.name} ({size // 1024} KB) "
                f"[video {size_v // 1024}KB + audio {size_a // 1024}KB]"
            )
        return True, f"ok {dest} {size} dash"
    finally:
        for p in (v_part, a_part, merged_part):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
        for extra in out.glob(f"{stem}.__*.download"):
            try:
                extra.unlink(missing_ok=True)
            except Exception:
                pass


def _try_download(
    url: str,
    cookies: Path,
    out: Path,
    on_line=None,
    audio_url: str | None = None,
) -> tuple[bool, str]:
    """Tenta baixar uma URL. Retorna (ok, log)."""
    code = shortcode_from_url(url)
    if _is_cdn_url(url):
        return _download_cdn(
            url, cookies, out, code=code, on_line=on_line, audio_url=audio_url
        )

    clean = _strip_ig_frag(url)
    if _is_reel(clean):
        primary = _ytdlp_cmd(cookies, out, clean)
        fallback = _gallery_cmd(cookies, out, clean)
    else:
        primary = _gallery_cmd(cookies, out, clean)
        fallback = (
            _ytdlp_cmd(cookies, out, clean)
            if ("/p/" in clean.lower() or "/reel/" in clean.lower())
            else None
        )

    rc, text = _run_cmd(primary)
    if on_line:
        for line in text.splitlines()[-20:]:
            on_line(line)
    if rc == 0:
        return True, text

    if fallback:
        if on_line:
            on_line("Retry com backend alternativo...")
        rc2, text2 = _run_cmd(fallback)
        if on_line:
            for line in text2.splitlines()[-20:]:
                on_line(line)
        if rc2 == 0:
            return True, text2
        return False, text2

    return False, text


def download_media_items(
    items: list,
    out_dir: Path | None = None,
    cookies: Path = COOKIES_FILE,
    on_line=None,
    username: str | None = None,
) -> Path:
    """
    Baixa lista de MediaItem.
    Fotos: CDN imagem maxima. Videos: DASH (maior resolucao) + audio.
    """
    urls: list[str] = []
    audio_map: dict[str, str] = {}
    skipped = 0
    for m in items:
        media = (getattr(m, "media_url", None) or "").strip()
        page = (getattr(m, "url", None) or "").strip()
        code = (getattr(m, "shortcode", None) or "").strip()
        title = (getattr(m, "highlight_title", None) or "").strip()
        audio = (getattr(m, "audio_url", None) or "").strip()
        if media:
            tag = code or hashlib.sha1(media.encode()).hexdigest()[:12]
            if title:
                tag = f"{_safe_stem(title)}_{tag}"
            urls.append(f"{media}#ig={tag}")
            if audio:
                audio_map[tag] = audio
        elif page and _is_cdn_url(page):
            urls.append(page)
        else:
            skipped += 1
            if on_line and code:
                on_line(f"Sem URL CDN, pulando: {code}")
    if not urls:
        raise RuntimeError(
            "Nenhuma midia com URL CDN baixavel. "
            "Conecte o Chrome de novo e liste outra vez."
        )
    if on_line and skipped:
        on_line(f"Aviso: {skipped} itens sem CDN foram pulados.")
    return download_urls(
        urls,
        out_dir=out_dir,
        cookies=cookies,
        on_line=on_line,
        username=username,
        audio_map=audio_map,
    )


def download_urls(
    urls: list[str],
    out_dir: Path | None = None,
    cookies: Path = COOKIES_FILE,
    on_line=None,
    username: str | None = None,
    audio_map: dict[str, str] | None = None,
) -> Path:
    """
    Baixa URLs na qualidade maxima em:
      <out_dir ou downloads>/   (pasta unica, sem segregacao por perfil)
    Um por vez. Falha em um item NAO aborta o lote (pula e segue).
    Itens ja baixados sao pulados.
    Retorna a pasta de downloads.
    """
    if not cookies.is_file():
        raise RuntimeError("Sem cookies. Conecte a sessao primeiro.")

    urls = [u.strip() for u in urls if u and u.strip()]
    if not urls:
        raise RuntimeError("Nenhuma URL para baixar.")

    urls, owner, expanded_audio = _expand_urls(urls, cookies, on_line=on_line)
    merged_audio = dict(expanded_audio or {})
    if audio_map:
        merged_audio.update(audio_map)
    if not urls:
        raise RuntimeError("Nenhuma URL para baixar apos expandir destaques.")

    # username/owner so para log; pasta e sempre unica
    _ = username or owner
    out = media_out_dir(Path(out_dir) if out_dir else DEFAULT_OUT)

    if on_line:
        on_line(f"Pasta de downloads: {out}")

    done = _load_done(out)
    total = len(urls)
    ok_n = 0
    skip_n = 0
    fail_n = 0
    failed_urls: list[str] = []
    consecutive_blocks = 0

    for i, url in enumerate(urls, start=1):
        code = shortcode_from_url(url)
        if url in done or _already_have(out, code, done):
            skip_n += 1
            if code:
                done.add(code)
            done.add(url)
            if on_line:
                on_line(f"[{i}/{total}] Ja baixado, pulando: {code or url}")
            continue

        audio = merged_audio.get(code or "", "") if code else ""
        if on_line:
            shown = code or (url[:80] + "..." if len(url) > 80 else url)
            if _is_cdn_url(url) and audio:
                on_line(f"[{i}/{total}] Baixando DASH maxima: {shown}")
            elif _is_cdn_url(url):
                on_line(f"[{i}/{total}] Baixando CDN: {shown}")
            else:
                on_line(f"[{i}/{total}] Baixando (qualidade maxima, 1 por vez): {shown}")

        success, text = _try_download(
            url, cookies, out, on_line=on_line, audio_url=audio or None
        )

        # bloqueio / rate limit: espera e tenta mais uma vez
        if not success and _looks_blocked(text):
            consecutive_blocks += 1
            wait = min(20 + consecutive_blocks * 15, 120)
            if on_line:
                on_line(
                    f"[{i}/{total}] Instagram bloqueou/limitou. "
                    f"Esperando {wait}s e tentando de novo..."
                )
            time.sleep(wait)
            success, text = _try_download(
                url, cookies, out, on_line=on_line, audio_url=audio or None
            )

        if success:
            ok_n += 1
            consecutive_blocks = 0
            if code:
                done.add(code)
                _mark_done(out, code)
            _mark_done(out, url)
            done.add(url)
            if on_line:
                on_line(f"[{i}/{total}] OK")
        else:
            fail_n += 1
            failed_urls.append(url)
            if on_line:
                tip = ""
                if _looks_blocked(text):
                    tip = " (sessao/rate-limit: Conectar Chrome de novo se persistir)"
                on_line(f"[{i}/{total}] FALHOU, pulando{tip}: {url}")
            # se varios bloqueios seguidos, pausa maior antes do proximo
            if consecutive_blocks >= 3:
                if on_line:
                    on_line(
                        "Muitos bloqueios seguidos. Pausa de 90s "
                        "(ou reconecte a sessao Chrome)..."
                    )
                time.sleep(90)
                consecutive_blocks = 0
            else:
                time.sleep(2)

    summary = (
        f"Resumo: {ok_n} baixados, {skip_n} ja existiam, {fail_n} falharam "
        f"(total {total})"
    )
    if on_line:
        on_line(summary)
        if failed_urls:
            on_line(f"Falhas ({len(failed_urls)}). Exemplos:")
            for u in failed_urls[:15]:
                on_line(f"  - {u}")
            if len(failed_urls) > 15:
                on_line(f"  ... e mais {len(failed_urls) - 15}")

    if ok_n == 0 and skip_n == 0 and fail_n > 0:
        raise RuntimeError(
            "Nenhum arquivo baixado. Sessao expirada ou Instagram bloqueou. "
            "Clique em Conectar Chrome e tente de novo.\n" + summary
        )

    return out


def download_profile_all(
    username: str,
    out_dir: Path | None = None,
    cookies: Path = COOKIES_FILE,
    on_line=None,
    on_progress=None,
) -> Path:
    """
    Lista posts + reels pela API e baixa 1 por vez, com progresso no log.
    (Destaques ficam no fluxo proprio da UI.)
    """
    from instagram_api import list_posts, list_reels

    user = safe_username(username)

    def emit(msg: str, cur: int = 0, tot: int = 0) -> None:
        # prefer progress (ja vai pro log na UI); evita linha duplicada
        if on_progress:
            on_progress(msg, cur, tot)
        elif on_line:
            on_line(msg)

    def prog_posts(msg, cur, tot):
        emit(f"[posts] {msg}", cur, tot)

    def prog_reels(msg, cur, tot):
        emit(f"[reels] {msg}", cur, tot)

    emit(f"Perfil @{user}: listando posts...", 0, 0)
    _profile, posts = list_posts(
        user, limit=None, cookies_path=cookies, on_progress=prog_posts
    )
    emit(f"Perfil @{user}: listando reels...", 0, 0)
    _, reels = list_reels(
        user, limit=None, cookies_path=cookies, on_progress=prog_reels
    )

    seen: set[str] = set()
    items = []
    for m in posts + reels:
        if m.shortcode in seen:
            continue
        seen.add(m.shortcode)
        items.append(m)

    n_vid = sum(1 for m in items if m.is_video)
    emit(
        f"Perfil @{user}: {len(items)} midias ({n_vid} videos, "
        f"{len(items) - n_vid} fotos/albuns). Baixando 1 por vez...",
        0,
        len(items) or 0,
    )
    if not items:
        raise RuntimeError(f"Nenhuma midia encontrada em @{user}.")

    return download_media_items(
        items,
        out_dir=out_dir,
        cookies=cookies,
        on_line=on_line,
        username=user,
    )
