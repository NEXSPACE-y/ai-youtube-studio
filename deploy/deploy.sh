#!/usr/bin/env bash
# Cloud Runへのデプロイ(更新のたびに実行)。プロジェクトルートで実行すること。
set -euo pipefail

PROJECT="${GCP_PROJECT:-ai-youtube-studio-503109}"
REGION="${GCP_REGION:-asia-northeast1}"
BUCKET="${GCS_BUCKET:-${PROJECT}-assets}"
ALLOWED="${ALLOWED_EMAILS:-matsunaga@nexspace.jp}"
APP_SA="studio-app@${PROJECT}.iam.gserviceaccount.com"
UP_SA="studio-uploader@${PROJECT}.iam.gserviceaccount.com"
AR="asia-northeast1-docker.pkg.dev/${PROJECT}/studio"

gcloud config set project "$PROJECT" -q

echo "== イメージをビルド =="
gcloud builds submit --config deploy/cloudbuild-app.yaml .
gcloud builds submit --config deploy/cloudbuild-uploader.yaml .

echo "== 投稿サービスをデプロイ(認証必須・IAM保護) =="
gcloud run deploy studio-uploader \
  --image "${AR}/uploader:latest" --region "$REGION" \
  --service-account "$UP_SA" \
  --no-allow-unauthenticated \
  --memory 1Gi --timeout 900 \
  --set-env-vars "GCP_PROJECT=$PROJECT,GCS_BUCKET=$BUCKET" \
  --set-secrets "YT_CLIENT_ID=yt-client-id:latest,YT_CLIENT_SECRET=yt-client-secret:latest,YT_REFRESH_TOKEN=yt-refresh-token:latest"

UPLOADER_URL=$(gcloud run services describe studio-uploader --region "$REGION" \
  --format="value(status.url)")

echo "== 管理アプリからの呼び出しのみ許可 =="
gcloud run services add-iam-policy-binding studio-uploader --region "$REGION" \
  --member="serviceAccount:$APP_SA" --role="roles/run.invoker" -q

echo "== 管理アプリをデプロイ =="
gcloud run deploy studio-app \
  --image "${AR}/app:latest" --region "$REGION" \
  --service-account "$APP_SA" \
  --no-allow-unauthenticated \
  --memory 2Gi --cpu 2 --timeout 3600 \
  --set-env-vars "APP_MODE=cloud,GCP_PROJECT=$PROJECT,GCP_REGION=$REGION,GCS_BUCKET=$BUCKET,ALLOWED_EMAILS=$ALLOWED,UPLOADER_URL=$UPLOADER_URL"

echo "== アクセス権(IAP/IAM)を付与 =="
for email in ${ALLOWED//,/ }; do
  gcloud run services add-iam-policy-binding studio-app --region "$REGION" \
    --member="user:$email" --role="roles/run.invoker" -q || true
done

gcloud run services describe studio-app --region "$REGION" --format="value(status.url)"
echo "↑ 管理画面URL。IAP未設定の間はローカルから: gcloud run services proxy studio-app --region $REGION"
