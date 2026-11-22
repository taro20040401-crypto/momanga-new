# momanga

momon-ga.com と hitomi.la を統合したオリジナル漫画ビューア。Python標準ライブラリのみで動作。

## 機能

- **複数ソース統合**: momon-ga.com(日本語) + hitomi.la(45言語) を統合表示
- **リアルタイム検索**: タイトル部分一致(例: 「幼なじみ」→ タイトルにそのキーワードを含む漫画)
- **ダーク漫画サイト風UI**: mangaraw/klmangaライクな黒背景のカードグリッド
- **言語表示**: 各漫画カードに言語バッジを表示。日本語優先ソート、言語フィルタ
- **画像プロキシ**: 両サイトの画像を自ホスト経由で配信。Referer制限を回避
- **詳細ビューア**: ページ送り、全画面モード、遅延読み込み
- **ブックマーク**: LocalStorageで永続化
- **ショートカット**: `/` 検索, `Esc` 閉じる, `←`/`→` ページ送り, `G` トップへ
- **レスポンシブ**: モバイル2列 / デスクトップ5列

## アーキテクチャ

```
momanga/                  # フラット構成
├── server.py             # メインHTTPサーバー + 画像プロキシ + API
├── provider_momonga.py   # momon-ga.com プロバイダ(検索・詳細)
├── provider_hitomi.py    # hitomi.la プロバイダ(gg.jsパーサ・nozomi・画像URL計算)
├── index.html            # メインUI
├── style.css             # ダークテーマ
├── app.js                # フロントエンド(JS)
├── logo.png              # ブランドロゴ
├── render.yaml           # Render設定
├── requirements.txt      # (空 - 標準ライブラリのみ)
├── .gitignore
└── README.md
```

## API

| Endpoint | Description |
| --- | --- |
| `GET /` | メインUI |
| `GET /api/search?q=<query>&source=<all\|momonga\|hitomi>&lang=<all\|ja\|en\|...>&page=<n>` | 検索(5分キャッシュ) |
| `GET /api/gallery/<source>/<id>` | 詳細(10分キャッシュ) |
| `GET /img/<source>/<id>?page=<n>` | 画像プロキシ |
| `GET /thumb/<source>/<id>` | サムネプロキシ |
| `GET /healthz` | ヘルスチェック |

## 検索クエリ

- 空欄: 新着リスト
- `幼なじみ`: タイトル/タグ部分一致(hitomiはフリーテキスト、momon-gaはWP標準検索)
- `tag:slime girl`: hitomi タグ検索
- `artist:xxx`: hitomi 作家検索

## 言語

- `all`: 全言語
- `ja`: 日本語
- `en`, `zh`, `ko`, `fr`, `es`, ... : 各言語

## Render デプロイ手順

### 1. GitHub へ push

```bash
cd momanga
git init
git add .
git commit -m "init: momanga"
git branch -M main
git remote add origin https://github.com/<ユーザー>/<リポジトリ>.git
git push -u origin main
```

### 2. Render でWeb Serviceを作成

1. https://render.com にログイン
2. "New +" → "Web Service"
3. GitHubリポジトリを選択
4. `render.yaml` が自動で設定を入力:
   - **Name**: `momanga`
   - **Runtime**: `Python 3.12.6`
   - **Plan**: Free
   - **Region**: Singapore
   - **Build**: `pip install -r requirements.txt`
   - **Start**: `python server.py`
   - **Health Check**: `/healthz`

5. **Start Command** が空欄の場合は手動で `python server.py` を入力
6. "Create Web Service" をクリック

### 3. 環境変数 (任意)

Render管理画面の「Environment」タブで:

- **ADMIN_TOKEN**: 任意の文字列(統計API保護用、未設定時は公開)
- **DEBUG**: `0` または `1`(デフォルト `0`)

### 4. デプロイ完了

`https://momanga-xxxx.onrender.com` でアクセス可能。

## ローカル実行

```bash
python server.py
# http://localhost:10000 を開く
```

環境変数:

| 変数 | デフォルト | 説明 |
| --- | --- | --- |
| `PORT` | `10000` | 待ち受けポート |
| `DEBUG` | `0` | `1` でログ出力 |
| `ADMIN_TOKEN` | (なし) | 統計API保護用 |

## 注意

- 本ツールは成人コンテンツを含む場合があります。利用地域の法律と各サイトの利用規約を遵守してください。
- momon-ga.com, hitomi.la は第三者のサイトです。本ツールはそれらの運営者とは無関係です。
- 検索キャッシュ: 5分(検索結果) / 10分(詳細) / 30分(gg.js) / 1時間(サムネ)
- Render Freeプランでは15分でスリープします。再アクセス時に30秒ほどかかります。
- hitomi.la の画像URL計算は gg.js のバージョン依存です。30分キャッシュで最新を保持します。

## トラブルシューティング

### 画像が表示されない

- `/img/<source>/<id>?page=1` に直接アクセスして200が返るか確認
- hitomi.la の画像は `Referer: https://hitomi.la/` が必須(server.pyで注入済)
- momon-ga.com の画像はホットリンク保護なし

### 検索結果が空

- `/api/search?q=幼なじみ&source=momonga` でJSONを確認
- hitomi は `lang=ja` 指定で日本語のみ
- momonga は日本語のみ

### Render のビルドが失敗する

- `requirements.txt` は空(標準ライブラリのみ)
- Python 3.12.6 を `render.yaml` で指定済み
