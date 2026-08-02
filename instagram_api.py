"""Lista posts, reels e destaques do Instagram usando cookies salvos."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from urllib.parse import urlparse

import requests

from session import COOKIES_FILE

IG_APP_ID = "936619743392459"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)

# Sem teto pratico na UI; so evita loop infinito se a API falhar.
MAX_HARD_CAP = 50_000


@dataclass
class MediaItem:
    shortcode: str
    url: str
    typename: str  # GraphImage, GraphVideo, GraphSidecar, HighlightStory
    is_video: bool
    caption: str
    thumb_url: str
    taken_at: int
    product_type: str  # feed, clips, highlight, etc.
    source: str = "posts"  # posts | reels | highlights
    highlight_title: str = ""
    highlight_id: str = ""
    # URL direta CDN (video/imagem). Em video, preferir faixa DASH maxima.
    media_url: str = ""
    # Faixa de audio DASH (quando media_url e so video).
    audio_url: str = ""


@dataclass
class HighlightInfo:
    """Uma pasta de destaque do perfil (bandeja), sem midias ainda."""

    id: str  # highlight:123...
    title: str
    media_count: int
    cover_url: str = ""


def parse_username_or_url(text: str) -> str:
    text = (text or "").strip()
    if not text:
        raise ValueError("Informe um @usuario ou URL do perfil")
    if text.startswith("@"):
        return text[1:].split("/")[0].strip()
    if "instagram.com" in text:
        path = urlparse(text).path.strip("/")
        parts = [p for p in path.split("/") if p]
        if not parts:
            raise ValueError("URL de perfil invalida")
        if parts[0] in ("p", "reel", "reels", "stories", "tv"):
            raise ValueError("Isso parece post/reel, nao perfil. Use Baixar post/reel.")
        return parts[0]
    return text.lstrip("@").split("/")[0].strip()


def parse_post_url(text: str) -> str | None:
    """
    Normaliza URL de post/reel/tv/destaque.
    Aceita /reel/ e /reels/ (Instagram usa os dois).
    """
    text = (text or "").strip()
    m = re.search(
        r"(?:https?://)?(?:www\.)?instagram\.com/(p|reel|reels|tv)/([A-Za-z0-9_-]+)",
        text,
        flags=re.I,
    )
    if m:
        kind = m.group(1).lower()
        code = m.group(2)
        if kind in ("reel", "reels"):
            kind = "reel"
        return f"https://www.instagram.com/{kind}/{code}/"
    m2 = re.search(
        r"(?:https?://)?(?:www\.)?instagram\.com/stories/highlights/(\d+)",
        text,
        flags=re.I,
    )
    if m2:
        return f"https://www.instagram.com/stories/highlights/{m2.group(1)}/"
    return None


def shortcode_from_post_url(text: str) -> str | None:
    u = parse_post_url(text)
    if not u or "/stories/highlights/" in u:
        return None
    m = re.search(r"/(?:p|reel|tv)/([A-Za-z0-9_-]+)/?", u, flags=re.I)
    return m.group(1) if m else None


def _media_id_from_html(html: str) -> str | None:
    if not html:
        return None
    for pat in (
        r'instagram://media\?id=(\d+)',
        r'"media_id"\s*:\s*"(\d+)"',
        r'"pkg_id"\s*:\s*"(\d+)"',
        r'"id"\s*:\s*"(\d+)_(\d+)"',
        r'"pk"\s*:\s*(\d+)',
    ):
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return None


def fetch_media_by_url(
    text: str,
    cookies_path: Path = COOKIES_FILE,
) -> tuple[list[MediaItem], str | None]:
    """
    Resolve post/reel (inclui /reels/) pela API e devolve MediaItem com CDN.
    Retorna (itens, username_dono).
    """
    url = parse_post_url(text)
    if not url:
        raise ValueError("URL de post/reel invalida.")
    if parse_highlight_id(url):
        raise ValueError("Use o fluxo de destaques para /stories/highlights/.")
    code = shortcode_from_post_url(url)
    if not code:
        raise ValueError("Nao achei o codigo do post/reel na URL.")

    s = _session_from_cookies(cookies_path)
    # pagina publica (com cookies) traz media_id
    page = s.get(url, timeout=30)
    if page.status_code in (401, 403):
        raise RuntimeError(
            "Sessao expirada ao abrir o post. Clique em Conectar Chrome."
        )
    mid = _media_id_from_html(page.text or "")
    if not mid:
        # tenta /p/ se veio de /reel/
        alt = f"https://www.instagram.com/p/{code}/"
        page2 = s.get(alt, timeout=30)
        mid = _media_id_from_html(page2.text or "")
    if not mid:
        raise RuntimeError(
            f"Nao consegui o media_id de {code}. "
            "Conecte o Chrome e tente de novo."
        )

    r = s.get(f"https://www.instagram.com/api/v1/media/{mid}/info/", timeout=30)
    data = _json_or_raise(r, "post/reel")
    batch = data.get("items") or []
    if not batch:
        raise RuntimeError(f"API sem midia para {code} (id {mid}).")

    raw = batch[0]
    owner = ((raw.get("user") or {}).get("username") or "").strip() or None
    product = (raw.get("product_type") or "").lower()
    source = "reels" if product in ("clips", "reel", "igtv") or "/reel/" in url else "posts"
    items = _raw_to_media_list(raw, source=source)
    if not items:
        raise RuntimeError(f"Post/reel {code} sem URL CDN baixavel.")
    if not any((m.media_url or "").strip() for m in items):
        raise RuntimeError(
            f"Post/reel {code} sem URL CDN. Conecte o Chrome e tente de novo."
        )
    return items, owner


def _session_from_cookies(cookies_path: Path = COOKIES_FILE) -> requests.Session:
    if not cookies_path.is_file():
        raise RuntimeError("Sem sessao. Conecte o Chrome ou faca login primeiro.")
    jar = MozillaCookieJar(str(cookies_path))
    jar.load(ignore_discard=True, ignore_expires=True)
    s = requests.Session()
    csrftoken = ""
    for c in jar:
        s.cookies.set(
            c.name,
            c.value,
            domain=c.domain,
            path=c.path or "/",
            secure=bool(c.secure),
        )
        if c.name == "csrftoken":
            csrftoken = c.value or ""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "X-IG-App-ID": IG_APP_ID,
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.instagram.com/",
        "Origin": "https://www.instagram.com",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }
    if csrftoken:
        headers["X-CSRFToken"] = csrftoken
    s.headers.update(headers)
    return s


def _json_or_raise(r: requests.Response, contexto: str) -> dict:
    """Parse JSON da API; mensagem clara se sessao morreu / rate-limit."""
    if r.status_code in (401, 403):
        raise RuntimeError(
            f"Sessao expirada ou bloqueada em {contexto}. "
            "Clique em Conectar Chrome e tente de novo."
        )
    text = (r.text or "").strip()
    if r.status_code != 200 or not text:
        raise RuntimeError(
            f"Erro em {contexto} (HTTP {r.status_code}). "
            "Sessao invalida ou Instagram limitou. Conecte o Chrome de novo."
        )
    if text[:1] not in "{[":
        low = text[:300].lower()
        if "login" in low or "<html" in low:
            raise RuntimeError(
                f"Instagram redirecionou para login em {contexto}. "
                "Clique em Conectar Chrome (sessao morta)."
            )
        raise RuntimeError(f"Resposta invalida em {contexto}: {text[:200]}")
    try:
        data = r.json()
    except Exception as e:
        raise RuntimeError(
            f"JSON invalido em {contexto}: {e}. Conecte o Chrome de novo."
        ) from e
    if not isinstance(data, dict):
        raise RuntimeError(f"Resposta inesperada em {contexto}.")
    return data


def fetch_profile(username: str, cookies_path: Path = COOKIES_FILE) -> dict:
    s = _session_from_cookies(cookies_path)
    url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
    r = s.get(url, timeout=30)
    data = _json_or_raise(r, "perfil")
    user = (data.get("data") or {}).get("user")
    if not user:
        raise RuntimeError("Perfil nao encontrado ou privado sem acesso.")
    return user


def parse_highlight_id(text: str) -> str | None:
    """Extrai id numerico de URL /stories/highlights/ID/."""
    text = (text or "").strip()
    m = re.search(
        r"https?://(?:www\.)?instagram\.com/stories/highlights/(\d+)",
        text,
    )
    return m.group(1) if m else None


def _parse_dash_reps(manifest: str) -> list[dict]:
    """Extrai Representation (width/height/bandwidth/mime/url) do MPD."""
    if not manifest:
        return []
    blocks = re.findall(
        r"<Representation\b[^>]*>.*?</Representation>",
        manifest,
        flags=re.I | re.S,
    )
    out: list[dict] = []
    for block in blocks:
        base = re.search(r"<BaseURL>([^<]+)</BaseURL>", block, flags=re.I)
        if not base:
            continue
        url = (base.group(1) or "").strip()
        url = (
            url.replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
        )
        if not url:
            continue
        bw = re.search(r'\bbandwidth="(\d+)"', block, flags=re.I)
        w = re.search(r'\bwidth="(\d+)"', block, flags=re.I)
        h = re.search(r'\bheight="(\d+)"', block, flags=re.I)
        mime = re.search(r'\bmimeType="([^"]+)"', block, flags=re.I)
        label = re.search(r'\bFBQualityLabel="([^"]+)"', block, flags=re.I)
        out.append(
            {
                "url": url,
                "bandwidth": int(bw.group(1)) if bw else 0,
                "width": int(w.group(1)) if w else 0,
                "height": int(h.group(1)) if h else 0,
                "mime": (mime.group(1) if mime else "").lower(),
                "label": (label.group(1) if label else "").lower(),
            }
        )
    return out


def _best_dash_av(item: dict) -> tuple[str, str]:
    """
    Melhor par video+audio do video_dash_manifest (qualidade maxima).
    Retorna (video_url, audio_url). audio_url pode ser "".
    """
    manifest = item.get("video_dash_manifest") or ""
    if not isinstance(manifest, str) or not manifest.strip():
        return "", ""
    reps = _parse_dash_reps(manifest)
    if not reps:
        return "", ""
    videos = [
        r
        for r in reps
        if r["width"] > 0 or r["height"] > 0 or r["mime"].startswith("video/")
    ]
    audios = [
        r
        for r in reps
        if r["width"] == 0
        and r["height"] == 0
        and (r["mime"].startswith("audio/") or "audio" in r["mime"])
    ]
    if not videos:
        return "", ""
    best_v = max(
        videos,
        key=lambda r: (r["width"] * r["height"], r["bandwidth"]),
    )
    best_a = max(audios, key=lambda r: r["bandwidth"]) if audios else None
    return best_v["url"], (best_a["url"] if best_a else "")


def _best_progressive_video(item: dict) -> str:
    videos = item.get("video_versions") or []
    if not videos:
        return ""
    best = max(
        videos,
        key=lambda v: (
            int(v.get("width") or 0) * int(v.get("height") or 0),
            int(v.get("bandwidth") or 0),
        ),
    )
    return (best.get("url") or "").strip()


def _best_image_url(item: dict) -> str:
    versions = item.get("image_versions2") or {}
    candidates = versions.get("candidates") or []
    if candidates:
        best = max(
            candidates,
            key=lambda c: (int(c.get("width") or 0) * int(c.get("height") or 0)),
        )
        u = (best.get("url") or "").strip()
        if u:
            return u
    return (item.get("thumbnail_url") or "").strip()


def _best_cdn_url(item: dict) -> str:
    """Melhor URL unica (video progressivo ou imagem). Preferir DASH via _best_dash_av."""
    dash_v, _ = _best_dash_av(item)
    if dash_v:
        return dash_v
    prog = _best_progressive_video(item)
    if prog:
        return prog
    return _best_image_url(item)


def _raw_to_media(
    item: dict,
    *,
    source: str,
    highlight_title: str = "",
    highlight_id: str = "",
    shortcode_override: str = "",
) -> MediaItem | None:
    shortcode = shortcode_override or item.get("code") or ""
    if not shortcode:
        # stories antigas as vezes so tem pk
        pk = item.get("pk") or item.get("id")
        if pk is None:
            return None
        shortcode = str(pk).split("_")[0]
    media_type = int(item.get("media_type") or 0)
    product = item.get("product_type") or ("clips" if source == "reels" else "feed")
    if source == "highlights":
        product = "highlight"
    is_video = media_type == 2 or bool(item.get("video_versions"))
    if not is_video and product in ("clips", "igtv", "reel"):
        is_video = True
    # slides de carrossel nao sao sidecar
    if media_type == 8 and not shortcode_override:
        typename = "GraphSidecar"
    elif source == "highlights":
        typename = "HighlightStory"
    elif is_video:
        typename = "GraphVideo"
    else:
        typename = "GraphImage"
    caption = ""
    cap = item.get("caption")
    if isinstance(cap, dict):
        caption = (cap.get("text") or "")[:160]
    elif isinstance(cap, str):
        caption = cap[:160]
    if highlight_title and not caption:
        caption = f"Destaque: {highlight_title}"
    elif highlight_title:
        caption = f"[{highlight_title}] {caption}"[:160]
    thumb = ""
    versions = item.get("image_versions2") or {}
    candidates = versions.get("candidates") or []
    if candidates:
        thumb = candidates[0].get("url") or ""
    if not thumb:
        thumb = item.get("thumbnail_url") or ""
    dash_v, dash_a = _best_dash_av(item)
    if dash_v:
        media_url = dash_v
        audio_url = dash_a
    else:
        media_url = _best_cdn_url(item)
        audio_url = ""
    if source == "reels" or product == "clips":
        path = "reel"
    else:
        path = "p"
    parent = shortcode.split("_")[0] if "_" in str(shortcode) else shortcode
    # Destaques: pagina do highlight (referencia). Download usa media_url.
    if source == "highlights" and highlight_id:
        hid = highlight_id.replace("highlight:", "")
        url = f"https://www.instagram.com/stories/highlights/{hid}/"
    else:
        url = f"https://www.instagram.com/{path}/{parent}/"
    return MediaItem(
        shortcode=str(shortcode),
        url=url,
        typename=typename,
        is_video=is_video,
        caption=caption,
        thumb_url=thumb,
        taken_at=int(item.get("taken_at") or item.get("device_timestamp") or 0),
        product_type=product,
        source=source,
        highlight_title=highlight_title,
        highlight_id=highlight_id,
        media_url=media_url,
        audio_url=audio_url,
    )


def _raw_to_media_list(
    item: dict,
    *,
    source: str,
    highlight_title: str = "",
    highlight_id: str = "",
) -> list[MediaItem]:
    """
    Converte um item da API em 1+ MediaItem.
    Carrossel (media_type=8) vira um arquivo por slide com URL CDN.
    """
    slides = item.get("carousel_media") or []
    if int(item.get("media_type") or 0) == 8 and slides:
        parent = item.get("code") or ""
        if not parent:
            pk = item.get("pk") or item.get("id")
            parent = str(pk).split("_")[0] if pk is not None else "album"
        # caption do post pai
        parent_cap = item.get("caption")
        out: list[MediaItem] = []
        for i, slide in enumerate(slides, start=1):
            # herda caption do album se o slide nao tiver
            if not slide.get("caption") and parent_cap is not None:
                slide = dict(slide)
                slide["caption"] = parent_cap
            m = _raw_to_media(
                slide,
                source=source,
                highlight_title=highlight_title,
                highlight_id=highlight_id,
                shortcode_override=f"{parent}_{i}",
            )
            if m and m.media_url:
                out.append(m)
        if out:
            return out
    m = _raw_to_media(
        item,
        source=source,
        highlight_title=highlight_title,
        highlight_id=highlight_id,
    )
    return [m] if m else []


def list_posts(
    username: str,
    limit: int | None = None,
    cookies_path: Path = COOKIES_FILE,
    on_progress=None,
) -> tuple[dict, list[MediaItem]]:
    if on_progress:
        on_progress("Buscando perfil...", 0, 0)
    user = fetch_profile(username, cookies_path)
    user_id = user.get("id")
    if not user_id:
        raise RuntimeError("Perfil sem id.")
    cap = limit if limit is not None else MAX_HARD_CAP
    s = _session_from_cookies(cookies_path)
    items: list[MediaItem] = []
    max_id = None
    page = 0
    while len(items) < cap:
        page += 1
        if on_progress:
            on_progress(f"Posts: pagina {page}, {len(items)} itens...", len(items), 0)
        params: dict = {"count": min(12, cap - len(items))}
        if max_id:
            params["max_id"] = max_id
        r = s.get(
            f"https://www.instagram.com/api/v1/feed/user/{user_id}/",
            params=params,
            timeout=30,
        )
        if r.status_code in (401, 403):
            raise RuntimeError("Sessao expirada ou bloqueada. Conecte o Chrome de novo.")
        if r.status_code != 200:
            raise RuntimeError(f"Erro no feed ({r.status_code}): {r.text[:200]}")
        payload = r.json()
        batch = payload.get("items") or []
        if not batch:
            break
        for raw in batch:
            for m in _raw_to_media_list(raw, source="posts"):
                items.append(m)
                if len(items) >= cap:
                    break
            if len(items) >= cap:
                break
        if on_progress:
            on_progress(
                f"Posts: pagina {page}, {len(items)} itens...",
                len(items),
                0,
            )
        if not payload.get("more_available"):
            break
        max_id = payload.get("next_max_id")
        if not max_id:
            break
    if on_progress:
        on_progress(f"Posts: concluido ({len(items)} itens)", len(items), len(items))
    return user, items[:cap]


def list_reels(
    username: str,
    limit: int | None = None,
    cookies_path: Path = COOKIES_FILE,
    on_progress=None,
) -> tuple[dict, list[MediaItem]]:
    if on_progress:
        on_progress("Buscando perfil...", 0, 0)
    user = fetch_profile(username, cookies_path)
    user_id = user.get("id")
    if not user_id:
        raise RuntimeError("Perfil sem id.")
    cap = limit if limit is not None else MAX_HARD_CAP
    s = _session_from_cookies(cookies_path)
    items: list[MediaItem] = []
    max_id = None
    page = 0
    while len(items) < cap:
        page += 1
        if on_progress:
            on_progress(f"Reels: pagina {page}, {len(items)} itens...", len(items), 0)
        data = {
            "target_user_id": str(user_id),
            "page_size": str(min(12, cap - len(items))),
            "include_feed_video": "true",
        }
        if max_id:
            data["max_id"] = max_id
        r = s.post(
            "https://www.instagram.com/api/v1/clips/user/",
            data=data,
            timeout=30,
        )
        if r.status_code in (401, 403):
            raise RuntimeError("Sessao expirada ou bloqueada. Conecte o Chrome de novo.")
        if r.status_code != 200:
            raise RuntimeError(f"Erro nos reels ({r.status_code}): {r.text[:200]}")
        payload = r.json()
        batch = payload.get("items") or []
        if not batch:
            break
        for wrap in batch:
            raw = wrap.get("media") or wrap
            for m in _raw_to_media_list(raw, source="reels"):
                items.append(m)
                if len(items) >= cap:
                    break
            if len(items) >= cap:
                break
        if on_progress:
            on_progress(
                f"Reels: pagina {page}, {len(items)} itens...",
                len(items),
                0,
            )
        paging = payload.get("paging_info") or {}
        if not paging.get("more_available"):
            break
        max_id = paging.get("max_id")
        if not max_id:
            break
    if on_progress:
        on_progress(f"Reels: concluido ({len(items)} itens)", len(items), len(items))
    return user, items[:cap]


def _fetch_highlight_reel(
    s: requests.Session,
    highlight_id: str,
) -> tuple[str, list[dict], str]:
    """Retorna (titulo, items brutos, username) de um destaque."""
    hid = str(highlight_id).strip()
    if not hid.startswith("highlight:"):
        hid = f"highlight:{hid}"
    r = s.get(
        "https://www.instagram.com/api/v1/feed/reels_media/",
        params={"reel_ids": hid},
        timeout=45,
    )
    payload = _json_or_raise(r, f"destaque {hid}")
    reels = payload.get("reels") or {}
    reel = reels.get(hid) or {}
    if not reel:
        num = hid.replace("highlight:", "")
        reel = reels.get(num) or next(iter(reels.values()), {}) or {}
    title = (reel.get("title") or "destaque").strip()
    user = reel.get("user") or {}
    username = (user.get("username") or "").strip()
    if not username:
        for raw in reel.get("items") or []:
            u = (raw.get("user") or {}).get("username")
            if u:
                username = str(u)
                break
    return title, list(reel.get("items") or []), username


def list_highlight_url(
    url_or_id: str,
    limit: int | None = None,
    cookies_path: Path = COOKIES_FILE,
) -> tuple[str, list[MediaItem], str]:
    """Lista itens de uma URL /stories/highlights/ID/. Retorna (titulo, items, username)."""
    hid = parse_highlight_id(url_or_id) or str(url_or_id).strip()
    if not hid.isdigit() and "highlight:" not in hid:
        raise ValueError("URL de destaque invalida")
    cap = limit if limit is not None else MAX_HARD_CAP
    s = _session_from_cookies(cookies_path)
    title, raws, username = _fetch_highlight_reel(s, hid)
    items: list[MediaItem] = []
    for raw in raws:
        if len(items) >= cap:
            break
        for m in _raw_to_media_list(
            raw,
            source="highlights",
            highlight_title=title,
            highlight_id=f"highlight:{hid}" if hid.isdigit() else hid,
        ):
            items.append(m)
            if len(items) >= cap:
                break
    return title, items, username


def list_highlight_tray(
    username: str,
    cookies_path: Path = COOKIES_FILE,
    on_progress=None,
) -> tuple[dict, list[HighlightInfo]]:
    """Lista so as pastas de destaque (nome + quantidade), sem baixar midias."""
    if on_progress:
        on_progress("Buscando perfil...", 0, 0)
    user = fetch_profile(username, cookies_path)
    user_id = user.get("id")
    if not user_id:
        raise RuntimeError("Perfil sem id.")
    s = _session_from_cookies(cookies_path)
    if on_progress:
        on_progress("Carregando nomes dos destaques...", 0, 0)
    r = s.get(
        f"https://www.instagram.com/api/v1/highlights/{user_id}/highlights_tray/",
        timeout=30,
    )
    tray_data = _json_or_raise(r, "destaques (bandeja)")
    tray = tray_data.get("tray") or []
    infos: list[HighlightInfo] = []
    for hl in tray:
        hid = str(hl.get("id") or "").strip()
        if not hid:
            continue
        title = (hl.get("title") or "destaque").strip() or "destaque"
        count = int(hl.get("media_count") or 0)
        cover = ""
        cover_media = hl.get("cover_media") or {}
        cropped = cover_media.get("cropped_image_version") or {}
        cover = cropped.get("url") or ""
        if not cover:
            versions = (cover_media.get("image_versions2") or {}).get("candidates") or []
            if versions:
                cover = versions[0].get("url") or ""
        infos.append(
            HighlightInfo(id=hid, title=title, media_count=count, cover_url=cover)
        )
    if on_progress:
        on_progress(f"Destaques: {len(infos)} pastas encontradas", len(infos), len(infos))
    return user, infos


def list_highlights(
    username: str,
    limit: int | None = None,
    cookies_path: Path = COOKIES_FILE,
    on_progress=None,
    only_ids: list[str] | None = None,
) -> tuple[dict, list[MediaItem]]:
    """
    Lista midias dos destaques.
    only_ids: se informado, so carrega esses highlight ids (ex: highlight:123).
    """
    if on_progress:
        on_progress("Buscando perfil...", 0, 0)
    user = fetch_profile(username, cookies_path)
    user_id = user.get("id")
    if not user_id:
        raise RuntimeError("Perfil sem id.")
    cap = limit if limit is not None else MAX_HARD_CAP
    s = _session_from_cookies(cookies_path)
    if on_progress:
        on_progress("Carregando bandeja de destaques...", 0, 0)
    r = s.get(
        f"https://www.instagram.com/api/v1/highlights/{user_id}/highlights_tray/",
        timeout=30,
    )
    tray = (_json_or_raise(r, "destaques (bandeja)").get("tray") or [])

    if only_ids:
        want_nums = {
            str(x).strip().replace("highlight:", "")
            for x in only_ids
            if str(x).strip()
        }
        tray = [
            hl
            for hl in tray
            if str(hl.get("id") or "").replace("highlight:", "") in want_nums
        ]

    total_hl = len(tray)
    if on_progress:
        on_progress(f"Destaques: {total_hl} pastas para carregar", 0, total_hl or 0)
    items: list[MediaItem] = []
    for idx, hl in enumerate(tray, start=1):
        if len(items) >= cap:
            break
        hid = hl.get("id") or ""
        title = (hl.get("title") or "destaque").strip()
        if not hid:
            continue
        if on_progress:
            on_progress(
                f"Destaque {idx}/{total_hl}: {title} ({len(items)} itens)...",
                idx - 1,
                total_hl,
            )
        try:
            reel_title, raws, _owner = _fetch_highlight_reel(s, hid)
            if reel_title:
                title = reel_title
        except RuntimeError as e:
            if on_progress:
                on_progress(f"Erro no destaque {idx}/{total_hl}: {e}", idx, total_hl)
            continue
        added = 0
        for raw in raws:
            if len(items) >= cap:
                break
            for m in _raw_to_media_list(
                raw,
                source="highlights",
                highlight_title=title,
                highlight_id=str(hid),
            ):
                items.append(m)
                added += 1
                if len(items) >= cap:
                    break
        if on_progress:
            on_progress(
                f"Destaque {idx}/{total_hl}: {title} OK "
                f"(+{added} midias, total {len(items)})",
                idx,
                total_hl,
            )
    if on_progress:
        on_progress(
            f"Destaques: concluido ({len(items)} itens em {total_hl} pastas)",
            total_hl,
            total_hl,
        )
    return user, items


def list_profile_media(
    username: str,
    limit: int | None = None,
    cookies_path: Path = COOKIES_FILE,
    source: str = "posts",
    on_progress=None,
) -> tuple[dict, list[MediaItem]]:
    """
    source: posts | reels | highlights | all
    limit=None = tudo (sem limite da UI).
    on_progress(msg, current, total) - total=0 = indeterminado.
    """
    source = (source or "posts").lower()
    if source == "posts":
        return list_posts(
            username, limit=limit, cookies_path=cookies_path, on_progress=on_progress
        )
    if source == "reels":
        return list_reels(
            username, limit=limit, cookies_path=cookies_path, on_progress=on_progress
        )
    if source in ("highlights", "destaques"):
        return list_highlights(
            username, limit=limit, cookies_path=cookies_path, on_progress=on_progress
        )
    if source == "all":
        if on_progress:
            on_progress("Listando tudo: posts...", 0, 3)

        def wrap(prefix: str, step: int):
            def cb(msg, cur, tot):
                if on_progress:
                    on_progress(f"[{prefix}] {msg}", step, 3)

            return cb

        user, posts = list_posts(
            username, limit=limit, cookies_path=cookies_path, on_progress=wrap("posts", 1)
        )
        if on_progress:
            on_progress("Listando tudo: reels...", 1, 3)
        _, reels = list_reels(
            username, limit=limit, cookies_path=cookies_path, on_progress=wrap("reels", 2)
        )
        if on_progress:
            on_progress("Listando tudo: destaques...", 2, 3)
        _, highs = list_highlights(
            username,
            limit=limit,
            cookies_path=cookies_path,
            on_progress=wrap("destaques", 3),
        )
        seen: set[str] = set()
        merged: list[MediaItem] = []
        for m in posts + reels + highs:
            if m.shortcode in seen:
                continue
            seen.add(m.shortcode)
            merged.append(m)
            if limit is not None and len(merged) >= limit:
                break
        if on_progress:
            on_progress(f"Tudo: concluido ({len(merged)} itens)", 3, 3)
        return user, merged
    raise ValueError(f"source invalido: {source}")
