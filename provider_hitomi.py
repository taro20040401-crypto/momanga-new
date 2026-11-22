#!/usr/bin/env python3
"""provider_hitomi.py — hitomi.la プロバイダ

機能:
  - 検索: .nozomi Range取得 → IDリスト → 各IDの詳細を取得して絞り込み
  - 詳細: galleries/<id>.js → galleryinfo JSON
  - 画像URL: gg.js の gg.b/gg.s/gg.m から計算

参考:
  - 新CDN: gold-usergeneratedcontent.net
  - nozomi: ltn.gold-usergeneratedcontent.net/<path>.nozomi (big-endian int32 ID配列)
  - 詳細: ltn.gold-usergeneratedcontent.net/galleries/<id>.js (var galleryinfo = {...};)
  - 画像: w{1|2}.gold-usergeneratedcontent.net/<b>/<dir_num>/<hash>.webp
  - Referer: https://hitomi.la/ 必須
"""
import json
import re
import ssl
import struct
import time
import urllib.request
from urllib.parse import quote_plus

# ===== 定数 =====
CDN = "https://ltn.gold-usergeneratedcontent.net"
IMG_CDN = "gold-usergeneratedcontent.net"
ORIGIN = "https://hitomi.la/"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
SSL_CTX = ssl.create_default_context()
SSL_CTX.set_ciphers("DEFAULT@SECLEVEL=1")

# ===== gg.js のキャッシュ =====
_gg_cache = {"b": "", "shards": set(), "ts": 0}
_GG_TTL = 1800  # 30分

LANG_LOCAL = {
    "japanese": "日本語", "english": "English", "chinese": "中文",
    "korean": "한국어", "french": "Français", "spanish": "Español",
    "german": "Deutsch", "italian": "Italiano", "portuguese": "Português",
    "russian": "Русский", "thai": "ไทย", "vietnamese": "Tiếng Việt",
    "indonesian": "Bahasa Indonesia", "tagalog": "Tagalog",
    "arabic": "العربية", "hindi": "हिन्दी", "turkish": "Türkçe",
    "polish": "Polski", "dutch": "Nederlands", "czech": "Čeština",
    "hungarian": "Magyar", "romanian": "Română", "greek": "Ελληνικά",
    "ukrainian": "Українська", "finnish": "Suomi", "swedish": "Svenska",
    "danish": "Dansk", "norwegian": "Norsk",
}


def _fetch(url: str, headers: dict = None, timeout: int = 20) -> bytes:
    """URL をフェッチして bytes を返す。"""
    h = {"User-Agent": UA, "Accept-Encoding": "identity"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        return r.read()


def _fetch_range(url: str, start: int, end: int, timeout: int = 15) -> bytes:
    """Range リクエストで部分取得。"""
    h = {
        "User-Agent": UA,
        "Accept-Encoding": "identity",
        "Range": f"bytes={start}-{end}",
    }
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        return r.read()


def _refresh_gg(force: bool = False) -> None:
    """gg.js を再取得・パース。"""
    if not force and time.time() - _gg_cache["ts"] < _GG_TTL:
        return
    try:
        js = _fetch(f"{CDN}/gg.js").decode("utf-8", "replace")
    except Exception:
        return
    # gg.b = '<value>/' (形式: b: '1795341602/')
    b_m = re.search(r"\bb:\s*'([^']+)'\s*", js)
    if b_m:
        _gg_cache["b"] = b_m.group(1)
    # gg.m の case リスト → shard 1 になる数値の集合
    cases = set(int(m) for m in re.findall(r"case (\d+):", js))
    _gg_cache["shards"] = cases
    _gg_cache["ts"] = time.time()


def _hash_to_paths(file_hash: str) -> dict:
    """hash から webp/avif/thumbnail URL を計算。"""
    _refresh_gg()
    # 末尾3文字を分割
    m = re.match(r".*(..)(.)$", file_hash)
    if not m:
        return {}
    last2, last1 = m.group(1), m.group(2)
    dir_num = int(last1 + last2, 16)  # 0..4095
    g = dir_num
    shard = 1 if g in _gg_cache["shards"] else 0
    base = _gg_cache["b"]
    # 画像URL
    webp = f"https://w{1+shard}.{IMG_CDN}/{base}{dir_num}/{file_hash}.webp"
    avif = f"https://a{1+shard}.{IMG_CDN}/{base}{dir_num}/{file_hash}.avif"
    # サムネ (tn.gold-usergeneratedcontent.net/webpbigtn/<last1>/<last2>/<hash>.webp)
    thumb = f"https://tn.{IMG_CDN}/webpbigtn/{last1}/{last2}/{file_hash}.webp"
    return {"webp": webp, "avif": avif, "thumb": thumb}


# ===== nozomi (IDリスト) =====
def _fetch_nozomi(path: str, page: int = 1, per_page: int = 25) -> list:
    """nozomi ファイルからIDリストを取得。1ページ = 25件(100バイト)。"""
    url = f"{CDN}/{path}"
    start = (page - 1) * per_page * 4
    end = start + per_page * 4 - 1
    data = _fetch_range(url, start, end)
    if not data:
        return []
    # 4バイトずつ big-endian int32
    ids = []
    for i in range(0, len(data) - 3, 4):
        ids.append(struct.unpack(">I", data[i:i+4])[0])
    return ids


# ===== galleryinfo =====
def _fetch_galleryinfo(gallery_id: int) -> dict:
    """galleries/<id>.js を取得して galleryinfo dict を返す。"""
    url = f"{CDN}/galleries/{gallery_id}.js"
    text = _fetch(url).decode("utf-8", "replace")
    # var galleryinfo = {...}; (末尾に ; がある場合もない場合も対応)
    m = re.search(r"var\s+galleryinfo\s*=\s*(\{.*\})\s*;?\s*$", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


# ===== 公開API =====
def search(query: str, page: int = 1, language: str = "all") -> dict:
    """検索。

    戻り値: {cards: [...], page: int, total_pages: int}

    戦略:
      - queryが空 → index-all.nozomi (新着)
      - queryがタグ形式(tag:xxx等) → tag/<query>-all.nozomi
      - それ以外 → nozomiから新着N件取得→各galleryinfo取得→タイトル部分一致でフィルタ
    """
    q = query.strip()
    # 言語別 nozomi:
    #   all → index-all.nozomi
    #   japanese → index-japanese.nozomi
    #   english → index-english.nozomi (etc.)
    # タグ/artist は -all か -<lang> をsuffixとして付ける
    lang_suffix = language  # "all" or "japanese" or ...

    if not q:
        # 新着
        nozomi_path = f"index-{lang_suffix}.nozomi"
    elif q.startswith("tag:"):
        # タグ検索
        tag = q[4:]
        nozomi_path = f"tag/{quote_plus(tag)}-{lang_suffix}.nozomi"
    elif q.startswith("artist:"):
        artist = q[7:]
        nozomi_path = f"artist/{quote_plus(artist)}-{lang_suffix}.nozomi"
    else:
        # フリーテキスト検索 → 新着から取得してフィルタ
        nozomi_path = f"index-{lang_suffix}.nozomi"

    # 1ページ25件取得
    ids = _fetch_nozomi(nozomi_path, page=page, per_page=25)
    if not ids:
        return {"cards": [], "page": page, "total_pages": page}

    # galleryinfo を並行取得(最大10並列)
    import concurrent.futures
    is_freetext = bool(q) and not (q.startswith("tag:") or q.startswith("artist:"))
    q_lower = q.lower()
    cards = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        future_to_id = {ex.submit(_fetch_galleryinfo, gid): gid for gid in ids}
        for future in concurrent.futures.as_completed(future_to_id, timeout=15):
            gid = future_to_id[future]
            try:
                info = future.result()
            except Exception:
                continue
            if not info:
                continue
            title = info.get("japanese_title") or info.get("title") or ""
            lang = info.get("language", "unknown")
            # フリーテキストフィルタ
            if is_freetext and q_lower not in title.lower():
                tags = [t.get("tag", "") if isinstance(t, dict) else str(t)
                        for t in info.get("tags", [])]
                if not any(q_lower in t.lower() for t in tags):
                    continue
            # サムネ取得 (1枚目のfile hash)
            files = info.get("files", [])
            thumb = ""
            if files:
                first = files[0]
                h = first.get("hash", "")
                if h:
                    thumb = _hash_to_paths(h).get("thumb", "")
            cards.append({
                "source": "hitomi",
                "id": str(gid),
                "type": info.get("type", "doujinshi"),
                "title": title or f"#{gid}",
                "thumbnail": thumb,
                "url": f"https://hitomi.la/{info.get('type','doujinshi')}/{_slugify(title)}-{lang}-{gid}.html",
                "date": info.get("date", ""),
                "language": lang,
                "language_local": LANG_LOCAL.get(lang, lang),
                "tags": [t.get("tag","") if isinstance(t, dict) else str(t)
                         for t in info.get("tags", [])][:10],
            })

    # nozomi の順序を保つ
    id_order = {gid: i for i, gid in enumerate(ids)}
    cards.sort(key=lambda c: id_order.get(int(c["id"]), 9999))
    total_pages = page + 1 if len(ids) >= 25 else page
    return {"cards": cards, "page": page, "total_pages": total_pages}


def _slugify(s: str) -> str:
    """URL用スラッグ化(簡易)。"""
    s = re.sub(r"[^\w\s-]", "", s.lower())
    return re.sub(r"[\s_-]+", "-", s).strip("-") or "untitled"


def get_gallery(gallery_id: str) -> dict:
    """詳細取得。"""
    gid = int(gallery_id)
    info = _fetch_galleryinfo(gid)
    if not info:
        return {"source": "hitomi", "id": gallery_id, "title": "(取得失敗)",
                "images": [], "url": "", "language": "unknown",
                "language_local": "unknown"}
    title = info.get("japanese_title") or info.get("title") or f"#{gid}"
    lang = info.get("language", "unknown")
    # 全画像URLを計算
    images = []
    for f in info.get("files", []):
        h = f.get("hash", "")
        if h:
            urls = _hash_to_paths(h)
            images.append(urls.get("webp", ""))
    return {
        "source": "hitomi",
        "id": gallery_id,
        "type": info.get("type", "doujinshi"),
        "title": title,
        "images": [i for i in images if i],
        "url": f"https://hitomi.la/{info.get('type','doujinshi')}/{_slugify(title)}-{lang}-{gid}.html",
        "language": lang,
        "language_local": LANG_LOCAL.get(lang, lang),
        "tags": [t.get("tag","") if isinstance(t, dict) else str(t)
                 for t in info.get("tags", [])],
        "artists": [a.get("artist","") if isinstance(a, dict) else str(a)
                    for a in info.get("artists", [])],
        "parodys": [p.get("parody","") if isinstance(p, dict) else str(p)
                    for p in info.get("parodys", [])],
        "date": info.get("date", ""),
    }


def latest(page: int = 1, language: str = "all") -> dict:
    """新着。"""
    return search("", page=page, language=language)


if __name__ == "__main__":
    import json
    print("=== gg.js refresh ===")
    _refresh_gg(force=True)
    print(f"gg.b = {_gg_cache['b']}, shards = {len(_gg_cache['shards'])}件")
    print()
    print("=== latest(1) ===")
    r = latest(page=1, language="japanese")
    print(json.dumps(r, ensure_ascii=False, indent=2)[:2500])
    if r["cards"]:
        gid = r["cards"][0]["id"]
        print(f"\n=== get_gallery({gid}) ===")
        g = get_gallery(gid)
        print(f"title: {g['title']}")
        print(f"images: {len(g['images'])}枚 (最初3件)")
        for u in g["images"][:3]: print(" ", u)
