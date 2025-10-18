import discord
from discord import app_commands
from discord.ext import tasks
from datetime import datetime, timedelta, time
import json, os, threading
import asyncio
from flask import Flask

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = 1421779868940763136

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True

# スラッシュコマンドをDiscordに同期する
class MyClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()

client = MyClient()

# === 定期タスク ===
@tasks.loop(time=time(hour=15, minute=0))  # 毎日JST0時に送信
async def send_json_file():
    if not os.path.exists(DATA_FILE):
        print("ファイルが存在しません。送信スキップ。")
        return

    channel = client.get_channel(CHANNEL_ID)
    if channel is None:
        print("チャンネルが見つかりません。")
        return

    # 日付付きファイル名にして送信
    filename = f"voice_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(DATA_FILE, "rb") as f:
        await channel.send(
            content=f"📊 VC記録のバックアップ（{datetime.now().strftime('%Y/%m/%d %H:%M')}）",
            file=discord.File(f, filename)
        )

    print(f"✅ JSONファイルを送信しました: {filename}")

# 🟢 手動でバックアップを送信する
@client.tree.command(name="backup", description="手動でvoice_data.jsonをDiscordに送信します。")
@app_commands.checks.has_permissions(administrator=True)
async def manual_backup(interaction: discord.Interaction):
    if not os.path.exists(DATA_FILE):
        await interaction.response.send_message("⚠️ voice_data.json が存在しません。", ephemeral=True)
        return

    jst_now = datetime.utcnow() + timedelta(hours=9)
    filename = f"voice_data_{jst_now.strftime('%Y%m%d_%H%M%S')}.json"
    with open(DATA_FILE, "rb") as f:
        await interaction.response.send_message(
            content=f"📁 手動バックアップ（{jst_now.strftime('%Y/%m/%d %H:%M')}）",
            file=discord.File(f, filename)
        )

    print(f"🟡 手動バックアップを送信しました: {filename}")

@client.tree.command(name="restore_backup", description="バックアップからvoice_data.jsonを復元")
@app_commands.checks.has_permissions(administrator=True)
async def restore_backup(interaction: discord.Interaction, file: discord.Attachment):
    await interaction.response.defer()

    if not file.filename.endswith(".json"):
        await interaction.followup.send("⚠️ JSONファイルを指定してください。")
        return

    # ファイルを読み込む
    data_bytes = await file.read()
    try:
        data = json.loads(data_bytes)
    except Exception as e:
        await interaction.followup.send(f"⚠️ JSONの読み込みに失敗しました: {e}")
        return

    # Render上のvoice_data.jsonに安全に書き込み
    global last_voice_activity
    last_voice_activity = data
    async with save_lock:
        with open(DATA_FILE, "w") as f:
            json.dump(last_voice_activity, f, indent=2, ensure_ascii=False)

    await interaction.followup.send(f"✅ voice_data.json を復元しました（{file.filename}）")


# VC記録を管理
DATA_FILE = "voice_data.json"
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        last_voice_activity = json.load(f)
else:
    last_voice_activity = {}

save_lock = asyncio.Lock()
async def save_data_async():
    async with save_lock:
        with open(DATA_FILE, "w") as f:
            json.dump(last_voice_activity, f, indent=2, ensure_ascii=False)

# === Bot起動時 ===
@client.event
async def on_ready():
    print(f"ログイン成功: {client.user}")
    if not send_json_file.is_running():
        send_json_file.start()  # 定期タスク開始

@client.event
async def on_voice_state_update(member, before, after):
    if before.channel is None and after.channel is not None:
        # VCに入った瞬間に記録更新
        guild_id = str(member.guild.id)
        last_voice_activity.setdefault(guild_id, {})
        last_voice_activity[guild_id][str(member.id)] = {
            "last_voice": datetime.utcnow().isoformat(),
            "last_role": last_voice_activity.get(guild_id, {}).get(str(member.id), {}).get("last_role")
        }

        await save_data_async()

# VC参加履歴に基づいて自動でロール付与する
@client.tree.command(name="assign_roles", description="VC参加履歴に基づいてロールを付与する")
@app_commands.checks.has_permissions(administrator=True)
async def assign_roles(interaction: discord.Interaction):
    try:
        await interaction.response.defer()

        guild = interaction.guild
        guild_id = str(guild.id)
        now = datetime.utcnow()
        one_month_ago = now - timedelta(days=30)

        role_active = discord.utils.get(guild.roles, name="アクティブなメンバー")
        role_busy = discord.utils.get(guild.roles, name="多忙なメンバー")
        role_never = discord.utils.get(guild.roles, name="未参加")

        # 重要: ロールが全部揃っているかチェックしておく
        if not all([role_active, role_busy, role_never]):
            missing = [name for name, obj in (("アクティブなメンバー", role_active),("多忙なメンバー", role_busy),("未参加", role_never)) if obj is None]
            await interaction.followup.send(f"以下のロールが存在しません: {', '.join(missing)} ❌")
            return

        await interaction.followup.send("VC参加ログをもとにロールを付与します！\n実行中・・・")

        log_messages = []

        for member in guild.members:
            if member.bot:
                continue

            user_id = str(member.id)
            user_data = last_voice_activity.get(guild_id, {}).get(user_id, {})
            last_active_str = user_data.get("last_voice")
            last_role_name = user_data.get("last_role")

            # last_active を安全にパース（失敗したら None 扱い）
            if last_active_str and last_active_str != "None":
                try:
                    last_active = datetime.fromisoformat(last_active_str)
                except Exception:
                    last_active = None
            else:
                last_active = None

            if last_active is None:
                if last_role_name is None or last_role_name == role_never.name:
                    role_to_add = role_never
                else:
                    role_to_add = role_busy
            else:
                if last_active is not None and isinstance(last_active, datetime) and last_active > one_month_ago:
                    role_to_add = role_active
                else:
                    role_to_add = role_busy

            # 前回と同じロールだったらスキップ
            if role_to_add and last_role_name == role_to_add.name:
                continue

            # ロール更新
            if role_to_add:
                roles_to_remove = [r for r in [role_active, role_busy, role_never] if r in member.roles]
                if roles_to_remove:
                    await member.remove_roles(*roles_to_remove)
                await member.add_roles(role_to_add)
                log_messages.append(f"{member.display_name}({member.name}): {last_role_name} → {role_to_add.name}")

                # last_voiceは更新せず、last_roleだけ更新
                last_voice_activity.setdefault(guild_id, {})
                last_voice_activity[guild_id].setdefault(user_id, {"last_voice": last_active_str, "last_role": None})
                last_voice_activity[guild_id][user_id]["last_role"] = role_to_add.name

        await save_data_async()
        if log_messages:
            await send_log(interaction, log_messages)
            await interaction.followup.send("ロール付与完了 ✅")
        else:
            await interaction.followup.send("ロール更新はありませんでした ✅")

    except Exception as e:
        await interaction.followup.send(f"処理の途中でエラーが発生しました ❌\n{e}")

@client.tree.command(name="get_last_vc_time_all", description="全員の最終VC参加時間を表示します")
async def get_last_vc_time_all(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
        guild = interaction.guild
        guild_id = str(guild.id)

        await interaction.followup.send("VC参加履歴を取得中...")

        guild_data = last_voice_activity.get(guild_id, {})
        if not guild_data:
            await interaction.followup.send("このサーバーではまだVC参加記録がありません。")
            return

        # 最近の順にソート
        sorted_members = sorted(
            guild.members,
            key=lambda m: (
                datetime.fromisoformat(guild_data.get(str(m.id), {}).get("last_voice"))
                if guild_data.get(str(m.id), {}).get("last_voice") else datetime.min
            ),
            reverse=True
        )

        log_lines = []
        for member in sorted_members:
            if member.bot:
                continue

            user_id = str(member.id)
            user_data = guild_data.get(user_id)
            if not user_data or not user_data.get("last_voice"):
                log_lines.append(f"{member.display_name}: 参加記録なし")
            else:
                last_time = datetime.fromisoformat(user_data["last_voice"])
                # UTC → JSTに変換
                jst_time = last_time + timedelta(hours=9)
                log_lines.append(f"{member.display_name}: {jst_time.strftime('%Y-%m-%d %H:%M:%S')}")

        await send_log(interaction, log_lines)
        await interaction.followup.send("取得完了 ✅")
    except Exception as e:
        await interaction.followup.send(f"処理の途中でエラーが発生しました ❌")

@client.tree.command(name="get_last_vc_time", description="指定したメンバーの最終VC参加時間を表示します")
async def get_last_vc_time(interaction: discord.Interaction, member: discord.Member):
    try:
        await interaction.response.defer()
        guild_id = str(interaction.guild.id)
        guild_data = last_voice_activity.get(guild_id, {})

        await interaction.followup.send(f"{member.display_name} のVC履歴を確認中...")

        user_id = str(member.id)
        user_data = guild_data.get(user_id)

        if not user_data or not user_data.get("last_voice"):
            await interaction.followup.send(f"{member.display_name} はまだVCに参加した記録がありません。")
            return

        last_time = datetime.fromisoformat(user_data["last_voice"])
        jst_time = last_time + timedelta(hours=9)

        await interaction.followup.send(
            f"🕓 **{member.display_name}** の最終VC参加日時：\n"
            f"{jst_time.strftime('%Y-%m-%d %H:%M:%S')}（JST）"
        )
    except Exception as e:
        await interaction.followup.send(f"処理の途中でエラーが発生しました ❌")


MAX_MESSAGE_LENGTH = 1900
async def send_log(interaction: discord.Interaction, log_lines):
    buffer = ""
    for line in log_lines:
        if len(buffer) + len(line) + 1 > MAX_MESSAGE_LENGTH:
            await interaction.followup.send(f"```\n{buffer}\n```")
            buffer = ""
            await asyncio.sleep(3)  # discordのRate Limit対策
        buffer += line + "\n"
    if buffer:
        await interaction.followup.send(f"```\n{buffer}\n```")


# Flaskサーバーでping受信（Renderスリープ回避用）
app = Flask(__name__)

@app.route("/ping")
def ping():
    return "pong", 200

def run_flask():
    app.run(host="0.0.0.0", port=8080)

threading.Thread(target=run_flask, daemon=True).start()

client.run(TOKEN)
