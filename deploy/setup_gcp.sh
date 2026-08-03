#!/usr/bin/env bash
# GCP初期セットアップ(1回だけ実行)。gcloud auth login 済みが前提。
set -euo pipefail

PROJECT="${GCP_PROJECT:-ai-youtube-studio-503109}"
REGION="${GCP_REGION:-asia-northeast1}"
BUCKET="${GCS_BUCKET:-${PROJECT}-assets}"
APP_SA="studio-app"
UP_SA="studio-uploader"

gcloud config set project "$PROJECT"

echo "== APIを有効化 =="
gcloud services enable \
  run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  aiplatform.googleapis.com firestore.googleapis.com storage.googleapis.com \
  texttospeech.googleapis.com speech.googleapis.com \
  secretmanager.googleapis.com iap.googleapis.com \
  youtube.googleapis.com youtubeanalytics.googleapis.com

echo "== Firestore(Native)を作成 =="
gcloud firestore databases create --location="$REGION" --type=firestore-native || true

echo "== GCSバケットを作成 =="
gcloud storage buckets create "gs://$BUCKET" --location="$REGION" \
  --uniform-bucket-level-access || true

echo "== サービスアカウントを作成 =="
gcloud iam service-accounts create "$APP_SA" --display-name="Studio App" || true
gcloud iam service-accounts create "$UP_SA" --display-name="Studio Uploader" || true
APP_SA_EMAIL="${APP_SA}@${PROJECT}.iam.gserviceaccount.com"
UP_SA_EMAIL="${UP_SA}@${PROJECT}.iam.gserviceaccount.com"

echo "== 権限付与(最小限: 要件9章) =="
# 管理アプリ: 生成AI・DB・ストレージ。YouTube権限は持たない
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:$APP_SA_EMAIL" --role="roles/aiplatform.user" -q
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:$APP_SA_EMAIL" --role="roles/datastore.user" -q
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member="serviceAccount:$APP_SA_EMAIL" --role="roles/storage.objectAdmin" -q
# 投稿サービス: DB(承認レコード検証+動画ID書込)・ストレージ読取・Secret読取
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:$UP_SA_EMAIL" --role="roles/datastore.user" -q
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member="serviceAccount:$UP_SA_EMAIL" --role="roles/storage.objectViewer" -q
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:$UP_SA_EMAIL" --role="roles/secretmanager.secretAccessor" -q

echo "== YouTube認証情報のSecret登録(値は後から) =="
for s in yt-client-id yt-client-secret yt-refresh-token; do
  gcloud secrets create "$s" --replication-policy=automatic || true
done

echo "完了。次は deploy/deploy.sh でデプロイしてください。"
echo "YouTube認証情報の登録例:"
echo "  echo -n 'VALUE' | gcloud secrets versions add yt-client-id --data-file=-"
