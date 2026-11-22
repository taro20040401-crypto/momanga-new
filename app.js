/* momanga — フロントエンドJS
   機能:
     - 検索 (クエリ+ソース+言語)
     - カードグリッド (24件+もっと見る)
     - 詳細モーダル (ページ送り, 全画面, 遅延読み込み)
     - ブックマーク (LocalStorage)
     - ショートカットキー (/, Esc, ←, →, G)
*/
(function () {
  "use strict";

  var STORE_KEY = "momanga_v3";
  var PER_PAGE = 24;

  // ===== 状態 =====
  var state = {
    query: "",
    source: "all",
    lang: "all",
    page: 1,
    cards: [],
    total_pages: 1,
    loading: false,
  };

  // ===== DOM =====
  var $ = function (s) { return document.querySelector(s); };
  var $$ = function (s) { return document.querySelectorAll(s); };

  var grid = $("#card-grid");
  var loadMoreArea = $("#load-more-area");
  var loadMoreBtn = $("#load-more-btn");
  var loadingArea = $("#loading-area");
  var emptyState = $("#empty-state");
  var searchBar = $("#status-bar");
  var pageTitle = $("#page-title");
  var searchForm = $("#search-form");
  var searchInput = $("#search-input");

  var modal = $("#gallery-modal");
  var modalTitle = $("#modal-title");
  var modalMeta = $("#modal-meta");
  var modalPages = $("#modal-pages");
  var modalClose = $("#modal-close");
  var bookmarkBtn = $("#bookmark-btn");
  var fullscreenBtn = $("#fullscreen-btn");
  var prevBtn = $("#prev-page-btn");
  var nextBtn = $("#next-page-btn");
  var pageIndicator = $("#page-indicator");
  var topBtn = $("#top-btn");

  // ===== ストレージ =====
  function loadStore() {
    try {
      var raw = localStorage.getItem(STORE_KEY);
      return raw ? JSON.parse(raw) : { bookmarks: [], lastQuery: "" };
    } catch (e) { return { bookmarks: [], lastQuery: "" }; }
  }
  function saveStore(d) {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(d)); } catch (e) {}
  }
  var store = loadStore();

  function isBookmarked(source, id) {
    return store.bookmarks.some(function (b) {
      return b.source === source && b.id === id;
    });
  }
  function toggleBookmark(card) {
    var existing = store.bookmarks.filter(function (b) {
      return b.source === card.source && b.id === card.id;
    });
    if (existing.length) {
      store.bookmarks = store.bookmarks.filter(function (b) {
        return !(b.source === card.source && b.id === card.id);
      });
    } else {
      store.bookmarks.unshift({
        source: card.source,
        id: card.id,
        title: card.title,
        thumbnail: card.thumbnail,
        language: card.language,
        language_local: card.language_local,
        type: card.type,
        url: card.url,
        ts: Date.now()
      });
    }
    saveStore(store);
  }

  // ===== ユーティリティ =====
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;",
        '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function langShort(lang) {
    return {
      "japanese": "JA", "english": "EN", "chinese": "ZH", "korean": "KO",
      "french": "FR", "spanish": "ES", "german": "DE", "italian": "IT",
      "portuguese": "PT", "russian": "RU", "thai": "TH",
      "vietnamese": "VI", "indonesian": "ID", "tagalog": "TL",
      "arabic": "AR", "hindi": "HI", "turkish": "TR",
      "polish": "PL", "dutch": "NL", "czech": "CS",
      "hungarian": "HU", "romanian": "RO", "greek": "EL",
      "ukrainian": "UK", "finnish": "FI", "swedish": "SV",
      "danish": "DA", "norwegian": "NO"
    }[lang] || lang.toUpperCase().substr(0, 2);
  }

  function timeAgo(dateStr) {
    if (!dateStr) return "";
    // momonga: "2025年05月03日", hitomi: "2025-05-03 12:34:56-06"
    var d;
    if (/^\d{4}年/.test(dateStr)) {
      var m = dateStr.match(/(\d{4})年(\d{1,2})月(\d{1,2})日/);
      if (m) d = new Date(+m[1], +m[2] - 1, +m[3]);
    } else {
      d = new Date(dateStr);
    }
    if (!d || isNaN(d)) return dateStr;
    var diff = Date.now() - d.getTime();
    var days = Math.floor(diff / 86400000);
    if (days === 0) return "今日";
    if (days === 1) return "昨日";
    if (days < 7) return days + "日前";
    if (days < 30) return Math.floor(days / 7) + "週間前";
    if (days < 365) return Math.floor(days / 30) + "ヶ月前";
    return Math.floor(days / 365) + "年前";
  }

  // ===== API呼び出し =====
  function apiSearch(page) {
    var q = encodeURIComponent(state.query);
    var url = "/api/search?q=" + q +
      "&source=" + state.source +
      "&lang=" + state.lang +
      "&page=" + page;
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  function apiGallery(source, id) {
    var url = "/api/gallery/" + source + "/" + id;
    if (source === "momonga") {
      // type を判定するためにまず検索カードから探す
      var card = state.cards.find(function (c) {
        return c.source === source && c.id === id;
      });
      if (card && card.type) {
        url += "?type=" + card.type;
      } else {
        url += "?type=fanzine";
      }
    }
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  // ===== レンダリング =====
  function renderCards() {
    grid.innerHTML = "";
    state.cards.forEach(function (c) {
      var card = document.createElement("div");
      card.className = "card";
      if (isBookmarked(c.source, c.id)) card.classList.add("bookmarked");
      card.dataset.source = c.source;
      card.dataset.id = c.id;
      // サムネイルはプロキシ経由で取得(Referer問題を回避)
      var thumbSrc;
      if (c.source === "hitomi") {
        thumbSrc = "/thumb/hitomi/" + c.id;
      } else if (c.source === "momonga") {
        thumbSrc = "/img/momonga/" + c.id + "?page=1";
      } else {
        thumbSrc = c.thumbnail;
      }
      var thumbHtml = thumbSrc
        ? '<img class="card-thumb" src="' + escapeHtml(thumbSrc) +
          '" alt="' + escapeHtml(c.title) + '" loading="lazy">'
        : '<div class="card-thumb placeholder">No image</div>';
      card.innerHTML =
        '<div class="card-thumb-wrap">' +
          thumbHtml +
          '<span class="card-source-badge ' + c.source + '">' + c.source + '</span>' +
          '<span class="card-lang-badge ' + (c.language || "") + '">' +
            escapeHtml(langShort(c.language)) +
          '</span>' +
        '</div>' +
        '<div class="card-body">' +
          '<div class="card-title">' + escapeHtml(c.title) + '</div>' +
          '<div class="card-meta">' +
            '<span class="card-date">' + escapeHtml(timeAgo(c.date)) + '</span>' +
          '</div>' +
        '</div>';
      card.addEventListener("click", function () {
        openGallery(c);
      });
      grid.appendChild(card);
    });
  }

  function showStatus(msg) {
    if (!msg) {
      searchBar.hidden = true;
      return;
    }
    searchBar.hidden = false;
    searchBar.innerHTML = msg;
  }

  function updateLoadMore() {
    if (state.loading) {
      loadingArea.hidden = false;
      loadMoreArea.hidden = true;
      return;
    }
    loadingArea.hidden = true;
    if (state.cards.length === 0) {
      loadMoreArea.hidden = true;
      emptyState.hidden = false;
      return;
    }
    emptyState.hidden = true;
    if (state.page < state.total_pages) {
      loadMoreArea.hidden = false;
    } else {
      loadMoreArea.hidden = true;
    }
  }

  // ===== 検索実行 =====
  function doSearch(page, fromPopState) {
    if (page === 1) {
      state.page = 1;
      state.cards = [];
      renderCards();
    }
    state.loading = true;
    updateLoadMore();
    if (state.query) {
      pageTitle.textContent = '検索: "' + state.query + '"';
    } else {
      pageTitle.textContent = "新着";
    }
    // History API: 検索状態をURLに反映(popstate由来の場合は不要)
    if (!fromPopState && !modalOpenStatePushed) {
      var newHash = buildHash();
      if (location.hash !== newHash) {
        history.pushState({ search: true }, "", newHash);
      }
    }

    apiSearch(page).then(function (data) {
      if (page === 1) state.cards = data.cards || [];
      else state.cards = state.cards.concat(data.cards || []);
      state.page = data.page || page;
      state.total_pages = data.total_pages || 1;
      state.loading = false;
      renderCards();
      updateLoadMore();
      // ステータスバー
      if (data.fallback) {
        showStatus('<span class="status-item" style="color:var(--warning)">' +
          escapeHtml(data.fallback) + '</span>');
      } else if (data.sources) {
        showStatus(
          '<span class="status-item"><span class="status-dot"></span> ' +
            (data.sources.momonga || 0) + '件 (momon-ga) / ' +
            (data.sources.hitomi || 0) + '件 (hitomi)</span>'
        );
      } else if (state.source === "momonga") {
        showStatus('<span class="status-item"><span class="status-dot"></span> ' +
          (state.cards.length) + '件 (momon-ga)</span>');
      } else if (state.source === "hitomi") {
        showStatus('<span class="status-item"><span class="status-dot"></span> ' +
          (state.cards.length) + '件 (hitomi)</span>');
      }
    }).catch(function (e) {
      state.loading = false;
      updateLoadMore();
      showStatus('<span class="status-item" style="color:var(--danger)">' +
        'エラー: ' + escapeHtml(e.message) + '</span>');
    });
  }

  // ===== モーダル =====
  var currentGallery = null;
  var currentPage = 1;
  // 戻るボタンでモーダルを閉じるためのHistory API対応
  var modalOpenStatePushed = false;

  function buildHash() {
    var parts = [];
    if (state.query) parts.push("q=" + encodeURIComponent(state.query));
    parts.push("src=" + state.source);
    parts.push("lang=" + state.lang);
    parts.push("p=" + state.page);
    return "#" + parts.join("&");
  }

  function applyHash() {
    var h = location.hash.replace(/^#/, "");
    if (!h) {
      state.query = "";
      state.source = "all";
      state.lang = "all";
      state.page = 1;
      syncUIFromState();
      doSearch(1);
      return;
    }
    var params = {};
    h.split("&").forEach(function (kv) {
      var p = kv.split("=", 2);
      if (p.length === 2) params[p[0]] = decodeURIComponent(p[1]);
    });
    var changed = false;
    if (params.q !== undefined && params.q !== state.query) {
      state.query = params.q; changed = true;
    }
    if (params.src && params.src !== state.source) {
      state.source = params.src; changed = true;
    }
    if (params.lang && params.lang !== state.lang) {
      state.lang = params.lang; changed = true;
    }
    var newPage = parseInt(params.p || "1", 10) || 1;
    if (newPage !== state.page) {
      state.page = newPage; changed = true;
    }
    syncUIFromState();
    if (changed || state.cards.length === 0) doSearch(state.page);
  }

  function syncUIFromState() {
    searchInput.value = state.query;
    $$(".seg-btn[data-source]").forEach(function (b) {
      b.classList.toggle("active", b.dataset.source === state.source);
    });
    $$(".seg-btn[data-lang]").forEach(function (b) {
      b.classList.toggle("active", b.dataset.lang === state.lang);
    });
  }

  function openGallery(card) {
    currentPage = 1;
    modalTitle.textContent = card.title;
    modalMeta.innerHTML = "";
    modalPages.innerHTML = '<div class="page-placeholder">読み込み中...</div>';
    pageIndicator.textContent = "1 / ?";
    bookmarkBtn.classList.toggle("active", isBookmarked(card.source, card.id));
    modal.hidden = false;
    document.body.style.overflow = "hidden";
    // History API: モーダルを開いた履歴エントリを追加
    if (!modalOpenStatePushed) {
      var newState = { modal: true, source: card.source, id: card.id };
      history.pushState(newState, "", "#gallery=" + card.source + ":" + card.id);
      modalOpenStatePushed = true;
    }

    apiGallery(card.source, card.id).then(function (g) {
      currentGallery = g;
      currentGallery._source = card.source;
      currentGallery._id = card.id;
      modalTitle.textContent = g.title || card.title;
      // メタ情報
      var metaHtml = "";
      if (g.language_local) {
        metaHtml += '<span class="meta-tag">' + escapeHtml(g.language_local) + '</span>';
      }
      if (g.type) {
        metaHtml += '<span class="meta-tag">' + escapeHtml(g.type) + '</span>';
      }
      if (g.tags && g.tags.length) {
        var tagStr = g.tags.slice(0, 5).join(", ");
        metaHtml += '<span class="meta-tag">' + escapeHtml(tagStr) + '</span>';
      }
      if (g.artists && g.artists.length) {
        metaHtml += '<span class="meta-tag">作: ' + escapeHtml(g.artists.join(", ")) + '</span>';
      }
      modalMeta.innerHTML = metaHtml;
      renderGalleryPages();
    }).catch(function (e) {
      modalPages.innerHTML = '<div class="page-placeholder">エラー: ' +
        escapeHtml(e.message) + '</div>';
    });
  }

  function renderGalleryPages() {
    if (!currentGallery) return;
    modalPages.innerHTML = "";
    var images = currentGallery.images || [];
    if (!images.length) {
      modalPages.innerHTML = '<div class="page-placeholder">画像が見つかりません</div>';
      return;
    }
    var src = currentGallery._source;
    var gid = currentGallery._id;
    images.forEach(function (_, i) {
      var page = i + 1;
      var url = "/img/" + src + "/" + gid + "?page=" + page;
      var img = document.createElement("img");
      img.dataset.src = url;
      img.dataset.page = page;
      img.dataset.retry = "0";
      img.alt = "page " + page;
      img.referrerpolicy = "no-referrer";
      img.loading = "lazy";
      // 読み込み失敗時のリトライ
      img.addEventListener("error", function () {
        var retry = parseInt(img.dataset.retry || "0", 10);
        if (retry < 3) {
          img.dataset.retry = String(retry + 1);
          // キャッシュ回避のためにタイムスタンプ付与
          var sep = url.indexOf("?") >= 0 ? "&" : "?";
          img.src = url + sep + "retry=" + (retry + 1) + "&t=" + Date.now();
        } else {
          // 最終的に失敗したら再読み込みボタン表示
          img.alt = "page " + page + " (読み込み失敗)";
          img.classList.add("img-failed");
          var wrap = document.createElement("div");
          wrap.className = "img-error-wrap";
          wrap.innerHTML = '<button class="img-retry-btn" type="button">再読み込み</button>';
          wrap.querySelector("button").addEventListener("click", function () {
            img.dataset.retry = "0";
            img.classList.remove("img-failed");
            var sep = url.indexOf("?") >= 0 ? "&" : "?";
            img.src = url + sep + "t=" + Date.now();
            wrap.remove();
          });
          img.parentNode.insertBefore(wrap, img.nextSibling);
        }
      });
      modalPages.appendChild(img);
    });
    pageIndicator.textContent = "1 / " + images.length;
    // 遅延読み込み (IntersectionObserver)
    setupLazyLoad();
  }

  function setupLazyLoad() {
    if (!("IntersectionObserver" in window)) {
      $$("img[data-src]").forEach(function (img) { img.src = img.dataset.src; });
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          var img = entry.target;
          if (img.dataset.src) {
            img.src = img.dataset.src;
            img.removeAttribute("data-src");
            io.unobserve(img);
          }
        }
      });
    }, { rootMargin: "500px" });  // 余裕を持って先読み
    $$("img[data-src]").forEach(function (img) { io.observe(img); });
  }

  function closeModal() {
    if (!modal.hidden) {
      modal.hidden = true;
      document.body.style.overflow = "";
      currentGallery = null;
      // モーダルを開く時にpushした履歴エントリを戻す
      if (modalOpenStatePushed) {
        modalOpenStatePushed = false;
        // pushState していた場合は戻るボタンで対応させる
        // ただし閉じるボタン等で明示的に閉じた場合は直接history.back()
        if (history.state && history.state.modal) {
          history.back();
          return;
        }
      }
    }
  }

  function scrollToPage(n) {
    if (!currentGallery) return;
    var images = currentGallery.images || [];
    if (n < 1) n = 1;
    if (n > images.length) n = images.length;
    var imgs = modalPages.querySelectorAll("img");
    if (imgs[n - 1]) {
      imgs[n - 1].scrollIntoView({ behavior: "smooth", block: "start" });
      currentPage = n;
      pageIndicator.textContent = n + " / " + images.length;
    }
  }

  // ===== イベント =====
  searchForm.addEventListener("submit", function (e) {
    e.preventDefault();
    state.query = searchInput.value.trim();
    doSearch(1);
  });

  $$(".seg-btn[data-source]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      $$(".seg-btn[data-source]").forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      state.source = btn.dataset.source;
      doSearch(1);
    });
  });

  $$(".seg-btn[data-lang]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      $$(".seg-btn[data-lang]").forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      state.lang = btn.dataset.lang;
      doSearch(1);
    });
  });

  loadMoreBtn.addEventListener("click", function () {
    if (state.page < state.total_pages) {
      doSearch(state.page + 1);
    }
  });

  modalClose.addEventListener("click", closeModal);
  modal.addEventListener("click", function (e) {
    if (e.target === modal) closeModal();
  });
  bookmarkBtn.addEventListener("click", function () {
    if (!currentGallery) return;
    var card = { source: currentGallery._source, id: currentGallery._id,
                 title: currentGallery.title,
                 thumbnail: "", language: currentGallery.language,
                 language_local: currentGallery.language_local,
                 type: currentGallery.type, url: currentGallery.url };
    toggleBookmark(card);
    bookmarkBtn.classList.toggle("active");
  });
  fullscreenBtn.addEventListener("click", function () {
    if (!document.fullscreenElement) {
      modal.requestFullscreen && modal.requestFullscreen();
    } else {
      document.exitFullscreen && document.exitFullscreen();
    }
  });
  prevBtn.addEventListener("click", function () { scrollToPage(currentPage - 1); });
  nextBtn.addEventListener("click", function () { scrollToPage(currentPage + 1); });

  // スクロール位置でページ番号更新
  modalPages.addEventListener("scroll", function () {
    if (!currentGallery) return;
    var imgs = modalPages.querySelectorAll("img");
    var scrollTop = modalPages.scrollTop;
    var pageH = modalPages.clientHeight;
    var n = Math.floor(scrollTop / (pageH * 0.9)) + 1;
    var total = (currentGallery.images || []).length;
    if (n < 1) n = 1;
    if (n > total) n = total;
    currentPage = n;
    pageIndicator.textContent = n + " / " + total;
  });

  // トップへ
  window.addEventListener("scroll", function () {
    if (window.scrollY > 400) topBtn.hidden = false, topBtn.classList.add("visible");
    else topBtn.hidden = true, topBtn.classList.remove("visible");
  }, { passive: true });
  topBtn.addEventListener("click", function () {
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  // ショートカット
  document.addEventListener("keydown", function (e) {
    if (e.key === "/" && document.activeElement !== searchInput) {
      e.preventDefault();
      searchInput.focus();
      searchInput.select();
    } else if (e.key === "Escape") {
      if (!modal.hidden) closeModal();
      else if (document.activeElement === searchInput) {
        searchInput.value = "";
        searchInput.blur();
      }
    } else if (e.key === "g" && !modal.hidden) {
      e.preventDefault();
      modalPages.scrollTo({ top: 0, behavior: "smooth" });
    } else if (e.key === "G" && modal.hidden) {
      e.preventDefault();
      window.scrollTo({ top: 0, behavior: "smooth" });
    } else if (e.key === "ArrowLeft" && !modal.hidden) {
      scrollToPage(currentPage - 1);
    } else if (e.key === "ArrowRight" && !modal.hidden) {
      scrollToPage(currentPage + 1);
    }
  });

  // ===== 初期化 =====
  // History API: popstate で状態復元
  window.addEventListener("popstate", function (e) {
    var st = e.state || {};
    if (st.modal) {
      // モーダル開状態に戻る場合はそのまま維持
      return;
    }
    // モーダルが開いていれば閉じる(履歴を戻ったので)
    if (!modal.hidden) {
      modal.hidden = true;
      document.body.style.overflow = "";
      currentGallery = null;
      modalOpenStatePushed = false;
    }
    // ハッシュから検索状態を復元
    applyHash();
  });

  if (store.lastQuery) {
    searchInput.value = store.lastQuery;
    state.query = store.lastQuery;
  }
  // 起動時にURLハッシュがあれば適用、無ければ新着
  if (location.hash) {
    applyHash();
  } else {
    doSearch(1);
  }
  searchForm.addEventListener("submit", function () {
    store.lastQuery = searchInput.value.trim();
    saveStore(store);
  });
})();
