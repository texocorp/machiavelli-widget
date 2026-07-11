# ==========================================================
# Machiavelli Geopolitics Bot - 設定ファイル
# ==========================================================

# --- 投稿頻度の調整 ---
# posting_interval_minutes: 何分おきにツイートを試みるか
# posts_per_day_cap:        1日あたりの最大投稿数(過剰投稿の防止)
# quiet_hours:              つぶやかない時間帯(現地時間, 24h表記)
schedule:
  posting_interval_minutes: 180      # 例: 180 = 3時間おき。頻度を上げたければ数値を下げる(最小30推奨)
  posts_per_day_cap: 6
  quiet_hours:
    start: "01:00"
    end: "06:00"
  timezone: "Asia/Tokyo"

# --- 動作モード ---
# dry_run: true の間は実際には投稿せず、logs/tweets.jsonl に出力するだけ。
#          Twitter/X API の認証情報を設定し、false にすると実際に投稿する。
mode:
  dry_run: true

# --- ニュース取得元 (RSS) ---
# 地政学的に重要度の高い一次情報・通信社ソースを中心に設定。
# 自由に追加・削除可能。
news_sources:
  - name: "Reuters World"
    url: "https://feeds.reuters.com/Reuters/worldNews"
  - name: "AP Top News"
    url: "https://apnews.com/apf-topnews.rss"
  - name: "NHK国際"
    url: "https://www3.nhk.or.jp/rss/news/cat6.xml"
  - name: "防衛省ニュース"
    url: "https://www.mod.go.jp/rss/news.xml"
  - name: "外務省報道発表"
    url: "https://www.mofa.go.jp/rss/press.xml"

# --- 地政学的重要度スコアリングの重み ---
# geopolitical_scorer.py が使用するキーワード群。重要ニュースの選別基準。
scoring_weights:
  high:      # 重み 3点: 軍事的実力・主権・勢力均衡に直結
    - "軍事"
    - "侵攻"
    - "領土"
    - "核"
    - "同盟"
    - "米軍"
    - "台湾有事"
    - "戦争"
    - "封鎖"
    - "抑止"
    - "military"
    - "invasion"
    - "sovereignty"
    - "nuclear"
    - "alliance"
  medium:    # 重み 2点: 勢力圏・経済安全保障・外交
    - "外交"
    - "制裁"
    - "関税"
    - "首脳会談"
    - "国連"
    - "safety"
    - "sanction"
    - "summit"
  low:       # 重み 1点: 一般的な国際ニュース
    - "会談"
    - "声明"
    - "訪問"

# --- Twitter/X API 認証情報 (dry_run=false の場合のみ使用) ---
# ここには直接キーを書かず、環境変数から読み込む運用を強く推奨します。
twitter_api:
  api_key_env: "TWITTER_API_KEY"
  api_secret_env: "TWITTER_API_SECRET"
  access_token_env: "TWITTER_ACCESS_TOKEN"
  access_secret_env: "TWITTER_ACCESS_SECRET"

# --- ツイート文体の設定 ---
persona:
  tone: "cold_realist"   # マキャベリの冷徹な現実主義トーン固定
  max_chars: 280
  language: "ja"
  # 近現代のリベラルな規範(国際法の理想主義・主権平等の建前)を採用せず、
  # 力の実相・保護国/属国関係・恐怖と信義の道具性を軸に分析するモード。
  ignore_liberal_framing: true
