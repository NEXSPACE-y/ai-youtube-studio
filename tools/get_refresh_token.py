"""YouTube OAuthのリフレッシュトークンを一度だけ取得するツール(豆虎が実行)。

使い方:
  1. GCPコンソールでOAuthクライアント(デスクトップアプリ)を作成しJSONをダウンロード
  2. python tools/get_refresh_token.py client_secret_xxx.json
  3. ブラウザが開くのでYouTubeチャンネルのGoogleアカウントでログインして許可
  4. 表示された refresh_token を Secret Manager に登録(コードや.envに残さない)
"""

import sys

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], SCOPES)
    creds = flow.run_local_server(port=0)
    print("\n===== refresh_token(Secret Managerに登録後、この画面を閉じる) =====")
    print(creds.refresh_token)


if __name__ == "__main__":
    main()
