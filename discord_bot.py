# -*- coding: utf-8 -*-
import os
import re
import calendar
from datetime import datetime, timedelta
import asyncio
import discord
from discord import app_commands
from discord.ui import View, Button, Select
import vk_api
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
load_dotenv()

# ========== НАСТРОЙКИ VK ==========
vk_session = vk_api.VkApi(token=os.environ['VK_USER_TOKEN'])
vk = vk_session.get_api()
VK_GROUP_ID = -193489972
# ========== ДАННЫЕ ==========
SIGNS = [
    '♈️Овен', '♉️Телец', '♊️Близнецы', '♋️Рак',
    '♌️Лев', '♍️Дева', '♎️Весы', '♏️Скорпион',
    '♐️Стрелец', '♑️Козерог', '♒️Водолей', '♓️Рыбы'
]

ARROW_LEFT = "⬅️"
ARROW_RIGHT = "➡️"

user_dates = {}

class DiscordBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.scheduler = AsyncIOScheduler()
    
    async def setup_hook(self):
        await self.tree.sync()
        print("✅ Команды синхронизированы")
        self.scheduler.start()
        print("✅ Планировщик запущен")

bot = DiscordBot()

async def get_horoscope(sign: str, date: datetime) -> str:
    try:
        posts = vk.wall.get(owner_id=VK_GROUP_ID, count=100)
        
        for post in posts['items']:
            if 'is_pinned' in post:
                continue
            post_date = datetime.fromtimestamp(post['date']).date()
            if post_date != date.date():
                continue
            pattern = re.compile(f"^{re.escape(sign)}.*", re.MULTILINE)
            match = re.search(pattern, post['text'])
            if match:
                horoscope = match.group(0)
                date_text = post_date.strftime("%d.%m.%Y")
                diff = (datetime.today().date() - post_date).days
                if diff == 0:
                    diff_text = "сегодня"
                elif diff == 1:
                    diff_text = "вчера"
                elif diff == 2:
                    diff_text = "позавчера"
                else:
                    diff_text = f"{diff} дней назад"
                return f"{horoscope}\n\n*({date_text}, {diff_text})*"
        return f"❌ Гороскоп для {sign} на {date.strftime('%d.%m.%Y')} не найден"
    except Exception as e:
        return f"❌ Ошибка: {e}"

class HoroscopeView(View):
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id
        if user_id not in user_dates:
            user_dates[user_id] = datetime.today()
        select = Select(
            placeholder="🔮 Выбери свой знак зодиака",
            options=[
                discord.SelectOption(label=sign, emoji=sign.split('️')[0], value=sign)
                for sign in SIGNS
            ]
        )
        select.callback = self.sign_callback
        self.add_item(select)
        self.add_item(DateButton(ARROW_LEFT, user_id))
        self.add_item(DateButton(user_dates[user_id].strftime("%d.%m.%Y"), user_id, disabled=True))
        self.add_item(DateButton(ARROW_RIGHT, user_id))
    
    async def sign_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        sign = interaction.data['values'][0]
        date = user_dates[self.user_id]
        horoscope = await get_horoscope(sign, date)
        embed = discord.Embed(
            title=f"🔮 {sign} | {date.strftime('%d.%m.%Y')}",
            description=horoscope,
            color=discord.Color.purple()
        )
        await interaction.followup.send(embed=embed, view=HoroscopeView(self.user_id))

class DateButton(Button):
    def __init__(self, label: str, user_id: int, disabled: bool = False):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, disabled=disabled)
        self.user_id = user_id
    
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if self.label == ARROW_LEFT:
            user_dates[self.user_id] = user_dates[self.user_id] - timedelta(days=1)
        elif self.label == ARROW_RIGHT:
            user_dates[self.user_id] = user_dates[self.user_id] + timedelta(days=1)
        await interaction.followup.send(
            f"📅 Выбрана дата: {user_dates[self.user_id].strftime('%d.%m.%Y')}",
            view=HoroscopeView(self.user_id),
            ephemeral=True
        )

@bot.tree.command(name="гороскоп", description="🔮 Получить гороскоп по знаку зодиака")
async def cmd_horoscope(interaction: discord.Interaction):
    await interaction.response.send_message(
        "🔮 **Выбери свой знак зодиака**",
        view=HoroscopeView(interaction.user.id),
        ephemeral=False
    )

@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user} запущен!')
    if os.getenv('AUTO_POST_CHANNEL_ID'):
        channel_id = int(os.getenv('AUTO_POST_CHANNEL_ID'))
        bot.scheduler.add_job(
            post_daily_horoscopes,
            CronTrigger(hour=0, minute=1),
            id='daily_horoscopes',
            replace_existing=True
        )
        print("✅ Запланирован ежедневный пост в 00:01")

async def post_daily_horoscopes():
    if not os.getenv('AUTO_POST_CHANNEL_ID'):
        return
    channel = bot.get_channel(int(os.getenv('AUTO_POST_CHANNEL_ID')))
    if not channel:
        return
    today = datetime.today()
    date_str = today.strftime("%d.%m.%Y")
    weekdays = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    weekday = weekdays[today.weekday()]
    header = f"🌅 **НЕЙРОГОРОСКОПЫ НА {date_str.upper()}** ({weekday})\n\n"
    all_horoscopes = []
    for sign in SIGNS:
        horoscope = await get_horoscope(sign, today)
        all_horoscopes.append(f"**{sign}**\n{horoscope}")
    messages = []
    current_message = header
    for horoscope in all_horoscopes:
        if len(current_message) + len(horoscope) + 4 > 2000:
            messages.append(current_message)
            current_message = horoscope + "\n\n"
        else:
            current_message += horoscope + "\n\n"
    if current_message:
        messages.append(current_message)
    for msg in messages:
        await channel.send(msg)
        await asyncio.sleep(1)


class HealthCheck(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_health_server():
    server = HTTPServer(('0.0.0.0', 10000), HealthCheck)
    server.serve_forever()

threading.Thread(target=run_health_server, daemon=True).start()
if __name__ == "__main__":
    bot.run(os.environ['DISCORD_TOKEN'])