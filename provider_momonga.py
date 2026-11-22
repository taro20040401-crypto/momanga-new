#!/usr/bin/env python3
"""provider_momonga.py — momon-ga.com プロバイダ

機能:
  - 検索: ?s=<query> でHTMLフェッチ → カードリスト抽出
  - 詳細: /<type>/mo<id>/ から画像URLリスト抽出
  - 新着: トップページから各セクション抽出

momon-ga.com は WordPress + DDoS-Guard。
画像は https://z{2,3}.momon-ga.me/galleries/<id>/<page>.webp
"""
import re
import ssl
import time
import urllib.request
from urllib.parse import quote_plus

ORIGIN = "https://momon-ga.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
SSL_CTX = ssl.create_default_context()
SSL_CTX.set_ciphers("DEFAULT@SECLEVEL=1")

# 共有CookieJar(opener)でDDoS-Guard cookieを保持
_COOKIE_JAR = urllib.request.HTTPCookieProcessor()
_OPENER = urllib.request.build_opener(_COOKIE_JAR)
_OPENER.addheaders = [
    ("User-Agent", UA),
    ("Accept", "text/html,application/xhtml+xml,*/*"),
    ("Accept-Language", "ja,en-US;q=0.8"),
]


def _fetch(url: str, timeout: int = 15) -> str:
    """URL をフェッチして text を返す。"""
    req = urllib.request.Request(url, headers={"Accept-Encoding": "identity"})
    with _OPENER.open(req, timeout=timeout) as r:
        data = r.read()
    return data.decode("utf-8", "replace")


# 正規表現パターン
# 1カード = <div class="post-list"> ... </div> の中に a href + img + span(title) + div.post-list-time
_RE_CARD = re.compile(
    r'<a[^>]*href="(https://momon-ga\.com/(fanzine|magazine)/mo(\d+)/?)"[^>]*>'
    r'\s*<div class="post-list-image"[^>]*>\s*'
    r'<img[^>]*src="([^"]+)"[^>]*alt="([^"]*)"[^>]*/?\s*>',
    re.S
)
_RE_TIME = re.compile(r'<div class="post-list-time"[^>]*>([^<]+)</div>', re.S)
_RE_NEXT = re.compile(r'<link[^>]*rel=["\']next["\'][^>]*href=["\']([^"\']+)', re.I)


def _parse_cards(html: str) -> list:
    cards = []
    matches = list(_RE_CARD.finditer(html))
    for m in matches:
        url, gtype, gid, thumb, title = m.groups()
        # タイトルが空の場合は alt のみを使う。altが空なら近くのspanから取得
        if not title:
            tail = html[m.end():m.end() + 300]
            sp = re.search(r'<span[^>]*>([^<]+)</span>', tail)
            if sp:
                title = sp.group(1).strip()
        # 日付は近くにある post-list-time を探す
        tail = html[m.end():m.end() + 800]
        time_m = _RE_TIME.search(tail)
        date = time_m.group(1).strip() if time_m else ""
        cards.append({
            "source": "momonga",
            "id": gid,
            "type": gtype,
            "title": title or "(無題)",
            "thumbnail": thumb,
            "url": url,
            "date": date,
            "language": "japanese",
            "language_local": "日本語",
        })
    return cards


# ===== 公開API =====
def search(query: str, page: int = 1) -> dict:
    """検索実行。{cards: [...], total_pages: int} を返す。"""
    q = quote_plus(query)
    if page <= 1:
        url = f"{ORIGIN}/?s={q}"
    else:
        url = f"{ORIGIN}/page/{page}/?s={q}"
    html = _fetch(url)
    cards = _parse_cards(html)
    total_pages = 1
    if _RE_NEXT.search(html):
        total_pages = page + 1  # 次があるので現在+1を上限とする
    elif len(cards) >= 10:
        total_pages = max(2, page + 1)
    return {"cards": cards, "page": page, "total_pages": total_pages}


def get_gallery(gallery_id: str, gallery_type: str = "fanzine") -> dict:
    """詳細ページを取得して画像リストを返す。"""
    url = f"{ORIGIN}/{gallery_type}/mo{gallery_id}/"
    html = _fetch(url)
    # post-hentai 内の img を全抽出
    images = re.findall(
        r'<div id="post-hentai"[^>]*>(.*?)</div>\s*<!--',
        html, re.S
    )
    if not images:
        # 別の区切り方
        images = re.findall(
            r'<div[^>]*id="post-hentai"[^>]*>(.*?)(?:<div[^>]*id="post-number"|<footer|$)',
            html, re.S
        )
    img_urls = []
    if images:
        img_urls = re.findall(
            r'<img[^>]*src="([^"]+momon-ga\.me/galleries/[^"]+)"',
            images[0], re.S
        )
    if not img_urls:
        # フォールバック: ページ全体から zN.momon-ga.me/galleries/<id>/ の画像
        img_urls = re.findall(
            r'src="(https://z\d+\.momon-ga\.me/galleries/' + re.escape(gallery_id) + r'/\d+\.webp)"',
            html
        )
    # タイトル
    title_m = re.search(r'<h1[^>]*class="entry-title"[^>]*>([^<]+)</h1>', html)
    if not title_m:
        title_m = re.search(r'<title>([^<|]+)', html)
    title = title_m.group(1).strip() if title_m else f"mo{gallery_id}"
    return {
        "source": "momonga",
        "id": gallery_id,
        "type": gallery_type,
        "title": title,
        "images": img_urls,
        "url": url,
        "language": "japanese",
        "language_local": "日本語",
    }


def latest(page: int = 1, category: str = "") -> dict:
    """新着リスト。category は fanzine / magazine / 空。"""
    if category:
        url = f"{ORIGIN}/{category}/page/{page}/" if page > 1 else f"{ORIGIN}/{category}/"
    else:
        url = f"{ORIGIN}/page/{page}/" if page > 1 else f"{ORIGIN}/"
    html = _fetch(url)
    cards = _parse_cards(html)
    total_pages = 50 if len(cards) >= 10 else page
    return {"cards": cards, "page": page, "total_pages": total_pages}


def image_url(gallery_id: str, page: int, host: str = "z2") -> str:
    """画像URLを生成。"""
    return f"https://{host}.momon-ga.me/galleries/{gallery_id}/{page}.webp"


if __name__ == "__main__":
    import json
    print("=== search ===")
    r = search("幼なじみ", page=1)
    print(json.dumps(r, ensure_ascii=False, indent=2)[:2000])
    if r["cards"]:
        gid = r["cards"][0]["id"]
        gtype = r["cards"][0]["type"]
        print(f"\n=== get_gallery({gid}, {gtype}) ===")
        g = get_gallery(gid, gtype)
        print(json.dumps(g, ensure_ascii=False, indent=2)[:1500])
