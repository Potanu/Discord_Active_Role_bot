## 1. Discord Botを作成
1. Discord Developer Portal にアクセス
2. 「New Application」を作成 → 名前をつける
3. 左メニューの Bot を選択
4. 「Reset Token」でトークンをコピーして保存（あとで使う）。　※これは 他人に絶対教えない。漏れたら不正利用される。
5. Botの権限設定
- Privileged Gateway Intents で下記をONにする
  - SERVER MEMBERS INTENT
  - MESSAGE CONTENT INTENT
6. 左メニューの OAuth2 を選択
- URL Generator
  - SCOPES: bot
- BOT PERMISSIONS:
  - Manage Roles
  - View Channels
  - Connect
7. 生成されたURLからサーバーにBotを招待

## 2. Bot用コードを作成
```
project/
  ├─ bot.py
  ├─ requirements.txt
```

## 3. Renderにデプロイ
1. Render にサインアップ（GitHub連携すると楽）
2. サービスを作成
- 「New +」 → 「Web Service」
- リポジトリを選択（BotコードをGitHubにpushしておく）
  - 設定
    - Name: 任意
    - Runtime: Python 3.x
    - Build Command: pip install -r requirements.txt
    - Start Command: python bot.py
    - 環境変数に DISCORD_TOKEN を追加（Botのトークンを貼り付け）
3. デプロイする

## 4. UptimeRobotでスリープ防止
1. UptimeRobot に登録
2. モニターを追加
- 「Add New Monitor」 →
  - Monitor Type: HTTP(s)
  - Friendly Name: 任意（例: VC-Bot）
  - URL: https://RenderのURL/ping
  - Monitoring Interval: 5分（無料枠の最小）
3. 保存 → これでUptimeRobotが定期的にアクセスしてくれるのでRenderがスリープしない