import json
import os
from pathlib import Path


class Settings:
    """環境変数から設定を読み込む。認証情報はコードに書かない(要件9章)。"""

    def __init__(self) -> None:
        self.app_mode = os.getenv("APP_MODE", "local")  # local | cloud
        self.data_dir = Path(os.getenv("DATA_DIR", "data")).resolve()
        self.gcp_project = os.getenv("GCP_PROJECT", "")
        self.gcp_region = os.getenv("GCP_REGION", "asia-northeast1")
        self.gcs_bucket = os.getenv("GCS_BUCKET", "")
        self.allowed_emails = [
            e.strip() for e in os.getenv("ALLOWED_EMAILS", "").split(",") if e.strip()
        ]
        self.default_cost_limit_jpy = float(os.getenv("DEFAULT_COST_LIMIT_JPY", "1500"))
        # Veo/Lyria等のメディア生成モデルは提供リージョンが限られる(基本us-central1)
        self.media_region = os.getenv("MEDIA_REGION", "us-central1")
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.imagen_model = os.getenv("IMAGEN_MODEL", "gemini-2.5-flash-image")
        self.veo_model = os.getenv("VEO_MODEL", "veo-3.0-generate-001")
        self.lyria_model = os.getenv("LYRIA_MODEL", "lyria-002")
        # 音声エンジン: gemini(演技指示可・既定) | cloud_tts(Neural2/Chirp3) | voicevox(OSS)
        self.tts_engine = os.getenv("TTS_ENGINE", "gemini")
        self.tts_voice = os.getenv("TTS_VOICE", "ja-JP-Neural2-B")
        self.gemini_tts_model = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-tts")
        self.gemini_tts_voice = os.getenv("GEMINI_TTS_VOICE", "Kore")
        self.gemini_tts_style = os.getenv(
            "GEMINI_TTS_STYLE",
            "落ち着いた知的な声で、ドキュメンタリー番組のナレーションのように、"
            "聞き取りやすく読み上げてください")
        self.voicevox_url = os.getenv("VOICEVOX_URL", "http://127.0.0.1:50021")
        self.voicevox_speaker = int(os.getenv("VOICEVOX_SPEAKER", "13"))
        # キャラクター→声の固定表(要件: キャラ毎にTTS音声を固定する)
        # 形式: {"キャラ名": {"engine": "gemini", "voice": "Kore", "style": "演技指示"}}
        cast_raw = os.getenv("CAST_JSON", "")
        self.cast: dict = json.loads(cast_raw) if cast_raw else {
            "栞": {"engine": "gemini", "voice": "Despina",
                  "style": "静かな資料室で、落ち着いた知的な女性の声で、優しく読んでください。"
                           "読み方: 蔵人栞=くろうどしおり、虎爺=とらじい、ツヅリ=つづり"},
            "虎爺": {"engine": "gemini", "voice": "Orus",
                    "style": "渋みのある年配の男性職人の声で、ぶっきらぼうだが温かみを込めて読んでください。"
                             "読み方: 虎爺=とらじい、鍛治虎三=かじとらぞう、蔵人栞=くろうどしおり"},
        }
        self.uploader_url = os.getenv("UPLOADER_URL", "")
        # マスコット画像(ストレージ上のオブジェクト名)。存在するとVeoが参照して
        # キャラクター登場カットを生成する(フェーズ2b)
        self.mascot_object = os.getenv("MASCOT_OBJECT", "config/mascot/v1/mascot.png")
        self.mascot_description = os.getenv(
            "MASCOT_DESCRIPTION",
            "the small tiger cub mascot wearing a dark-blue reporter vest and "
            "holding a notebook, exactly as shown in the input image")
        raw = os.getenv("COST_TABLE_JSON", "")
        self.cost_table_override: dict = json.loads(raw) if raw else {}

    @property
    def is_local(self) -> bool:
        return self.app_mode != "cloud"


settings = Settings()
