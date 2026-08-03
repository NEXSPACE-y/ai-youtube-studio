# AI YouTube Studio

Googleエコシステム限定のAI YouTube半自動制作システム。
企画 → リサーチ → 台本 → 素材生成 → 編集 → 品質確認 → **公開承認(豆虎Gate)** → 投稿・分析 を1つの管理画面で回す。

- 要件: [docs/01_技術選定書.md](docs/01_技術選定書.md)(要件定義書・追補は別管理)
- セットアップ: [docs/02_セットアップ手順.md](docs/02_セットアップ手順.md)
- 使い方: [docs/03_使い方.md](docs/03_使い方.md)

## 2つの動作モード

| モード | 用途 | 生成物 |
|---|---|---|
| `local` | 動作確認。GCP不要・費用ゼロ | ダミー画像・無音声・HTMLプレビュー |
| `cloud` | 本番。Cloud Run上で稼働 | Veo動画・Imagen画像・TTS音声・Lyria BGM・mp4 |

## ローカルで試す(GCP不要)

```
pip install -r requirements-local.txt
python run_local.py
```

→ http://localhost:8080 を開く。企画作成から公開承認まで全工程をダミー素材で体験できる。

## テスト

```
python -m pytest tests -q
```

E2Eテスト(`tests/test_flow.py`)が企画→投稿済みまでの全工程と、
承認なし公開の拒否・差し戻し・コスト記録を検証する。

## 構成

```
app/
  config.py      設定(環境変数)
  models.py      案件・シーン・素材・承認記録などのデータモデル
  states.py      12状態の状態機械と差し戻し規則
  repo.py        永続化(local=JSON / cloud=Firestore)
  storage.py     成果物保存(local=ファイル / cloud=GCS)。命名規則=案件/工程/シーン/版
  costs.py       コストメータ(上限超過の予測時に生成を停止)
  llm.py         Gemini呼び出し(検索グラウンディング対応)
  prompts.py     各工程のプロンプト
  services/      企画/リサーチ/台本/構成/素材/字幕/編集/投稿準備/承認/分析
  web/           管理・承認UI(FastAPI + Jinja2)
uploader/        投稿サービス(YouTube権限を持つ唯一のサービス。分離デプロイ)
tools/           YouTube OAuthトークン取得(初回のみ)
deploy/          GCPセットアップ・デプロイスクリプト
tests/           単体 + E2Eテスト
```

## 安全設計(要件9章)

- 公開操作は投稿サービス(`uploader/`)に分離。管理アプリはYouTube権限を持たない
- 投稿サービスは**Firestore上の公開承認レコードを自前で再検証**してからのみ公開する
- YouTube認証情報はSecret Manager経由。コード・ログ・.envに書かない
- 管理画面はIAP + メール許可リストで保護
