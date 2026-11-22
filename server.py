#!/usr/bin/env python3
"""momanga — 複数ソース統合 漫画ビューア
   Python 標準ライブラリのみ。momon-ga.com + hitomi.la を統合。

ルーティング:
  GET /                          # メインUI
  GET /style.css, /app.js, /logo.png
  GET /api/search?q=&source=&lang=&page=
  GET /api/gallery/<source>/<id>
  GET /img/<source>/<id>?page=<n>  # 画像プロキシ
  GET /healthz
"""
import json
import os
import re
import threading
import time
import urllib.request
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import provider_momonga
import provider_hitomi

PORT = int(os.environ.get("PORT", "10000"))
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
DEBUG = os.environ.get("DEBUG", "0") == "1"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_FILES = {
    "index.html": "text/html; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
    "app.js": "application/javascript; charset=utf-8",
    "logo.png": "image/png",
}

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
SSL_CTX = ssl.create_default_context()
SSL_CTX.set_ciphers("DEFAULT@SECLEVEL=1")

# ===== 5分キャッシュ =====
_CACHE_LOCK = threading.Lock()
_CACHE = {}  # key=(kind, *args) -> (data, expires_at)
_CACHE_TTL = 300  # 5分


def cache_get(key):
    with _CACHE_LOCK:
        v = _CACHE.get(key)
        if v and v[1] > time.time():
            return v[0]
        if v:
            _CACHE.pop(key, None)
    return None


def cache_set(key, value, ttl=_CACHE_TTL):
    with _CACHE_LOCK:
        _CACHE[key] = (value, time.time() + ttl)
        # 古いエントリを掃除(簡易)
        if len(_CACHE) > 200:
            now = time.time()
            for k in list(_CACHE.keys()):
                if _CACHE[k][1] < now:
                    _CACHE.pop(k, None)


# ===== 統合検索 =====
def unified_search(query: str, source: str = "all", language: str = "all", page: int = 1) -> dict:
    """両プロバイダを並行検索して統合。"""
    if source == "all":
        # 並行取得(スレッド)
        results = {}
        def fetch_momonga():
            try:
                results["momonga"] = provider_momonga.search(query, page=page)
            except Exception as e:
                if DEBUG: print(f"[momonga search error] {e}")
                results["momonga"] = {"cards": [], "page": page, "total_pages": 0, "error": str(e)}
        def fetch_hitomi():
            try:
                # hitomi の言語マッピング: all → all, ja → japanese, en → english 等
                lang_map = {"all": "all", "ja": "japanese", "en": "english",
                            "zh": "chinese", "ko": "korean"}
                hl = lang_map.get(language, language)
                results["hitomi"] = provider_hitomi.search(query, page=page, language=hl)
            except Exception as e:
                if DEBUG: print(f"[hitomi search error] {e}")
                results["hitomi"] = {"cards": [], "page": page, "total_pages": 0, "error": str(e)}
        t1 = threading.Thread(target=fetch_momonga)
        t2 = threading.Thread(target=fetch_hitomi)
        t1.start(); t2.start()
        t1.join(timeout=20); t2.join(timeout=20)
        # 統合(日本語優先でソート)
        cards = []
        cards.extend(results.get("momonga", {}).get("cards", []))
        cards.extend(results.get("hitomi", {}).get("cards", []))
        # 日本語優先ソート
        cards.sort(key=lambda c: 0 if c.get("language") == "japanese" else 1)
        total_pages = max(
            results.get("momonga", {}).get("total_pages", 1),
            results.get("hitomi", {}).get("total_pages", 1),
        )
        return {"cards": cards, "page": page, "total_pages": total_pages,
                "sources": {"momonga": len(results.get("momonga", {}).get("cards", [])),
                           "hitomi": len(results.get("hitomi", {}).get("cards", []))}}
    elif source == "momonga":
        return provider_momonga.search(query, page=page)
    elif source == "hitomi":
        lang_map = {"all": "all", "ja": "japanese", "en": "english",
                    "zh": "chinese", "ko": "korean"}
        return provider_hitomi.search(query, page=page, language=lang_map.get(language, language))
    return {"cards": [], "page": page, "total_pages": 0}


# ===== 画像プロキシ =====
def fetch_image(source: str, gallery_id: str, page: int) -> tuple:
    """画像を取得して (bytes, content_type) を返す。"""
    if source == "momonga":
        # momonga は thumbnails と詳細画像で同じホスト
        # 詳細画像: https://zN.momon-ga.me/galleries/<id>/<page>.webp
        # サムネも同じ形式で page=1
        url = f"https://z2.momon-ga.me/galleries/{gallery_id}/{page}.webp"
        headers = {"User-Agent": UA, "Accept-Encoding": "identity"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
            return r.read(), "image/webp"
    elif source == "hitomi":
        # galleryinfo を取得 → files[page-1].hash → webp URL
        info = provider_hitomi.get_gallery(gallery_id)
        if not info or not info.get("images"):
            raise ValueError(f"hitomi gallery {gallery_id} が見つかりません")
        # page は1-indexed
        if page < 1 or page > len(info["images"]):
            raise ValueError(f"page {page} が範囲外 (max={len(info['images'])})")
        url = info["images"][page - 1]
        # Referer 必須
        headers = {"User-Agent": UA, "Accept-Encoding": "identity",
                   "Referer": "https://hitomi.la/"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
            return r.read(), "image/webp"
    raise ValueError(f"unknown source: {source}")


def fetch_thumbnail(source: str, gallery_id: str) -> tuple:
    """サムネイル画像を取得。検索時に保存した thumbnail URL を使う。"""
    if source == "momonga":
        return fetch_image("momonga", gallery_id, 1)
    elif source == "hitomi":
        # galleryinfo を取得してサムネ URL を計算(キャッシュ)
        cache_key = ("thumb_url", gallery_id)
        thumb_url = cache_get(cache_key)
        if not thumb_url:
            raw_info = provider_hitomi._fetch_galleryinfo(int(gallery_id))
            if raw_info and raw_info.get("files"):
                h = raw_info["files"][0].get("hash", "")
                if h:
                    urls = provider_hitomi._hash_to_paths(h)
                    thumb_url = urls.get("thumb")
                    if thumb_url:
                        cache_set(cache_key, thumb_url, ttl=600)
        if not thumb_url:
            raise ValueError(f"hitomi thumbnail for {gallery_id} not found")
        headers = {"User-Agent": UA, "Accept-Encoding": "identity",
                  "Referer": "https://hitomi.la/"}
        req = urllib.request.Request(thumb_url, headers=headers)
        with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
            return r.read(), "image/webp"
    raise ValueError(f"unknown source: {source}")


# ===== HTTPハンドラ =====
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if DEBUG:
            print("%s %s" % (self.command, self.path), flush=True)

    def _send(self, status, body: bytes, ctype: str, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status, obj, extra=None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", extra)

    def _serve_static(self, name: str, ctype: str):
        path = os.path.join(SCRIPT_DIR, name)
        if not os.path.exists(path):
            return self._send(404, b"not found", "text/plain; charset=utf-8")
        with open(path, "rb") as f:
            data = f.read()
        self._send(200, data, ctype, {"Cache-Control": "public, max-age=3600"})

    def do_GET(self):
        self._handle("GET")
    def do_HEAD(self):
        self._handle("HEAD")

    def _handle(self, method: str):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        # ===== ヘルスチェック =====
        if path == "/healthz":
            return self._send(200, b"ok", "text/plain; charset=utf-8")

        # ===== 静的ファイル =====
        if path == "/" or path == "/index.html":
            return self._serve_static("index.html", "text/html; charset=utf-8")
        if path.lstrip("/") in STATIC_FILES:
            return self._serve_static(path.lstrip("/"), STATIC_FILES[path.lstrip("/")])

        # ===== API: 検索 =====
        if path == "/api/search":
            q = (qs.get("q", [""])[0] or "").strip()
            source = qs.get("source", ["all"])[0]
            lang = qs.get("lang", ["all"])[0]
            page = int(qs.get("page", ["1"])[0] or "1")
            cache_key = ("search", q, source, lang, page)
            cached = cache_get(cache_key)
            if cached:
                return self._json(200, cached, {"X-Cache": "HIT"})
            try:
                result = unified_search(q, source, lang, page)
                cache_set(cache_key, result)
                return self._json(200, result, {"X-Cache": "MISS"})
            except Exception as e:
                return self._json(500, {"error": str(e), "cards": [], "page": page})

        # ===== API: 詳細 =====
        m = re.match(r"^/api/gallery/(\w+)/(\w+)$", path)
        if m:
            source, gid = m.group(1), m.group(2)
            cache_key = ("gallery", source, gid)
            cached = cache_get(cache_key)
            if cached:
                return self._json(200, cached, {"X-Cache": "HIT"})
            try:
                if source == "momonga":
                    # type をクエリで受け取る(デフォルト fanzine)
                    gtype = qs.get("type", ["fanzine"])[0]
                    data = provider_momonga.get_gallery(gid, gtype)
                elif source == "hitomi":
                    data = provider_hitomi.get_gallery(gid)
                else:
                    return self._json(404, {"error": "unknown source"})
                cache_set(cache_key, data, ttl=600)  # 詳細は10分キャッシュ
                return self._json(200, data, {"X-Cache": "MISS"})
            except Exception as e:
                return self._json(500, {"error": str(e)})

        # ===== 画像プロキシ =====
        m = re.match(r"^/img/(\w+)/(\w+)$", path)
        if m:
            source, gid = m.group(1), m.group(2)
            page = int(qs.get("page", ["1"])[0] or "1")
            try:
                body, ctype = fetch_image(source, gid, page)
                return self._send(200, body, ctype,
                                 {"Cache-Control": "public, max-age=86400"})
            except Exception as e:
                if DEBUG: print(f"[img error] {source}/{gid}/{page}: {e}")
                return self._send(404, b"image not found", "text/plain; charset=utf-8")

        # ===== サムネプロキシ =====
        m = re.match(r"^/thumb/(\w+)/(\w+)$", path)
        if m:
            source, gid = m.group(1), m.group(2)
            try:
                body, ctype = fetch_thumbnail(source, gid)
                return self._send(200, body, ctype,
                                 {"Cache-Control": "public, max-age=86400"})
            except Exception as e:
                if DEBUG: print(f"[thumb error] {source}/{gid}: {e}")
                return self._send(404, b"thumbnail not found", "text/plain; charset=utf-8")

        # ===== 404 =====
        self._send(404, b"not found", "text/plain; charset=utf-8")


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    print(f"momanga listening on :{PORT}", flush=True)
    print(f"DEBUG={'on' if DEBUG else 'off'}", flush=True)
    print(f"ADMIN_TOKEN={'set' if ADMIN_TOKEN else '(none)'}", flush=True)
    Server(("0.0.0.0", PORT), Handler).serve_forever()
