import discord
from discord import app_commands
from datetime import datetime, timedelta
import json, os, threading
import asyncio
from flask import Flask

TOKEN = os.getenv("DISCORD_TOKEN")

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

@client.event
async def on_ready():
    print(f"ログイン成功: {client.user}")

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
    await interaction.response.defer()

    guild = interaction.guild
    guild_id = str(guild.id)
    now = datetime.utcnow()
    one_month_ago = now - timedelta(days=30)

    role_active = discord.utils.get(guild.roles, name="アクティブなメンバー")
    role_busy = discord.utils.get(guild.roles, name="多忙なメンバー")
    role_never = discord.utils.get(guild.roles, name="未参加")

    await interaction.followup.send(
        f"VC参加ログをもとにロールを付与します！\n"
        f"１か月以内に参加した：{role_active.name if role_active else 'ロール未作成'}\n"
        f"１か月以内に参加していない：{role_busy.name if role_busy else 'ロール未作成'}\n"
        "実行中・・・"
    )

    log_messages = []

    for member in guild.members:
        if member.bot:
            continue

        user_id = str(member.id)
        user_data = last_voice_activity.get(guild_id, {}).get(user_id, {})
        last_active_str = user_data.get("last_voice")
        last_role_name = user_data.get("last_role")

        if last_active_str:
            last_active = datetime.fromisoformat(last_active_str)
        else:
            last_active = None

        # ロール判定
        if last_active is None and last_role_name is None:
            role_to_add = role_never
        elif last_active is None and last_role_name is not None:
            role_to_add = role_busy
        else:
            role_to_add = role_active if last_active > one_month_ago else role_busy

        # 前回と同じロールならスキップ
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
    await send_log(interaction, log_messages)
    await interaction.followup.send("ロール付与完了 ✅")

# bot導入以前からVC参加済みのメンバーを手動で登録する
@client.tree.command(name="set_initial_member", description="初期メンバーを手動で登録します")
async def set_initial_member(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.defer()
    guild = interaction.guild

    role_active = discord.utils.get(guild.roles, name="アクティブなメンバー")
    role_busy = discord.utils.get(guild.roles, name="多忙なメンバー")
    role_never = discord.utils.get(guild.roles, name="未参加")

    # メンバーに未参加ロールがついている場合のみ、多忙に変更
    if role_never in member.roles:
        await member.remove_roles(role_never)
        await member.add_roles(role_busy)

        # last_roleも更新して保存
        guild_id = str(guild.id)
        user_id = str(member.id)
        last_active_str = last_voice_activity.get(guild_id, {}).get(user_id, {}).get("last_voice")
        last_voice_activity.setdefault(guild_id, {})
        last_voice_activity[guild_id].setdefault(user_id, {"last_voice": last_active_str, "last_role": None})
        last_voice_activity[guild_id][user_id]["last_role"] = role_busy.name

        await save_data_async()

        await interaction.followup.send(f"{member.display_name} を初期メンバーとして登録しました ✅")
    else:
        await interaction.followup.send(
            f"{member.display_name} は既に登録済みのため変更できません ❌"
        )


@client.tree.command(name="get_last_vc_time_all", description="全員の最終VC参加時間を表示します")
async def get_last_vc_time_all(interaction: discord.Interaction):
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

@client.tree.command(name="get_last_vc_time", description="指定したメンバーの最終VC参加時間を表示します")
async def get_last_vc_time(interaction: discord.Interaction, member: discord.Member):
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
