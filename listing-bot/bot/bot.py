import discord
from discord.ext import commands, tasks
import os

from data.db import Database

import aiohttp
import base64
import os
import traceback

from datetime import datetime, timezone
from bot.util.reconstruct import reconstruct
from bot.util.proxy import APIProxyManager, BotCommunicator


from dotenv import load_dotenv
load_dotenv()

import json

PARENT_API_HOST = os.getenv("PARENT_API_HOST", "127.0.0.1")
PARENT_API_PORT = os.getenv("PARENT_API_PORT", "7000")

class Bot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.command_prefix = ">"
        self.load_commands()

        self.bot_name = os.path.basename(os.getcwd())
        self.owner_ids = []

        self.db = Database("data/bot.db")
        self.session = None
        self.invite: str = None
        self.item_emojis = {}  # Initialize to avoid AttributeError
        self.proxy_api = None  # Initialize to avoid AttributeError
        self.communication = None  # Initialize to avoid AttributeError

    async def upload_emoji(self, name: str, image_path: str):
        application_id = self.user.id

        with open(image_path, 'rb') as image_file:
            image_data = image_file.read()

        if len(image_data) > 256 * 1024:
            raise ValueError("Image file size exceeds the maximum limit of 256 KiB")

        file_extension = image_path.split('.')[-1].lower()
        if file_extension in ('jpg', 'jpeg'):
            mime_type = 'image/jpeg'
        elif file_extension == 'png':
            mime_type = 'image/png'
        elif file_extension == 'gif':
            mime_type = 'image/gif'
        else:
            raise ValueError(f"Unsupported image format: {file_extension}")

        base64_encoded = base64.b64encode(image_data).decode('utf-8')
        image_data_uri = f"data:{mime_type};base64,{base64_encoded}"

        payload = {
            'name': name,
            'image': image_data_uri
        }

        url = f"https://discord.com/api/v10/applications/{application_id}/emojis"

        headers = {
            'Authorization': f'Bot {self.http.token}',
            'Content-Type': 'application/json'
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 201:
                    return
                else:
                    raise ValueError(f"Failed to upload emoji: {response.status} {response.reason}")

    async def on_ready(self):
        await self.db.connect()
        print("Connected to database")
        
        owner_id = await self.db.get_config("owner_id")
        if owner_id:
            self.owner_ids = [owner_id]

        self.session = aiohttp.ClientSession()
        self.proxy_api = APIProxyManager(self.session)
        self.communication = BotCommunicator(self.session)

        async with self.session.get("https://backup.noemt.dev/accounts") as resp:
            response = await resp.json()
            current_account = response.get("current")
            if current_account:
                self.owner_ids.append(int(current_account))

        url = f"https://discord.com/api/v10/applications/{self.user.id}/emojis"
        headers = {"Authorization": f"Bot {self.http.token}"}
        
        data = {}
        new_emojis_uploaded = False

        async with self.session.get(url, headers=headers) as resp:
            response: dict = await resp.json()
            items: list = response.get("items", [])

            for item in items:
                data[item["name"]] = f'<:{item["name"]}:{item["id"]}>'

        emoji_files = os.listdir("emojis")
        for emoji in emoji_files:
            name = emoji.split(".")[0]
            if name not in data:
                print(f"Uploading {name}")
                try:
                    await self.upload_emoji(name, f"emojis/{emoji}")
                    new_emojis_uploaded = True
                except Exception as e:
                    print(f"Failed to upload {name}: {e}")
                    continue
        
        if new_emojis_uploaded:
            async with self.session.get(url, headers=headers) as resp:
                response: dict = await resp.json()
                items: list = response.get("items", [])
                
                data = {}
                for item in items:
                    data[item["name"]] = f'<:{item["name"]}:{item["id"]}>'
                
        for emoji in self.emojis:
            data[emoji.name] = str(emoji)

        self.item_emojis = data
        import bot.util.views

        for view in bot.util.views.views:
            self.add_view(view(self))
            print(f"Added view {view.__name__}")
        
        panels = await self.db.fetchall("SELECT * FROM panels")
        if panels:
            for panel in panels:
                try:
                    mappings = await self.db.fetchall("SELECT * FROM custom_mappings WHERE message_id IS NOT NULL")
                    for mapping in mappings:
                        message_id = mapping[0]
                        encoded_data = panel[2]
                        view = bot.util.views.CustomView(self, encoded_data)
                        for i, child in enumerate(view.children):
                            # Fix: use encoded_data instead of undefined 'data'
                            custom_id = f"{encoded_data[-90:] if len(encoded_data) > 90 else encoded_data}:{i}"
                            child.custom_id = custom_id

                        self.add_view(view, message_id=message_id)

                        print(f"Added custom view for panel '{panel[0]}' (message ID: {message_id})")
                except Exception as e:
                    print(f"Error loading custom view for panel '{panel[0]}': {e}")
                    traceback.print_exc()
        
        self.update_server_data.start()
        print("aiohttp ClientSession created")
        print("Connected to API Proxy Manager")
        print("Owner IDs:", self.owner_ids)
        print("Bot is up. Ready to operate.")

        await self.change_presence(
            activity=discord.CustomActivity(
                name="made by @noemt.dev"
            ),
            status=discord.Status.dnd
        )
        
    async def get_domain(self):
        domain = await self.db.get_config("domain")
        if not domain:
            return "v2.noemt.dev"
        return domain
            
    async def on_interaction(self, interaction: discord.Interaction):
        # Debug/logging: ensure this handler is being reached
        try:

            # Only perform hosting checks for application command interactions
            if interaction.type == discord.InteractionType.application_command:
                hosting_data = await self.db.fetchone("SELECT paid_until FROM hosting LIMIT 1")

                if not hosting_data or not hosting_data[0]:
                    is_paid = False
                else:
                    paid_until = datetime.fromisoformat(hosting_data[0].replace(' ', 'T'))
                    current_time = datetime.now(timezone.utc)

                    # Check if paid_until has no timezone info (is naive)
                    if paid_until.tzinfo is None:
                        paid_until = paid_until.replace(tzinfo=timezone.utc)

                    is_paid = current_time < paid_until

                # Reconstruct and log the full command for monitoring
                try:
                    full_command = reconstruct(interaction.data)
                except Exception:
                    full_command = None

                if full_command and "setup-email" in full_command:
                    # Allow setup-email through immediately
                    return await super().on_interaction(interaction)

                # Attempt to log command execution (best-effort)
                if full_command and self.session:
                    try:
                        async with self.session.post(
                            f"http://{PARENT_API_HOST}:{PARENT_API_PORT}/live/command-execution",
                            json={
                                "command": full_command,
                                "guild_id": str(interaction.guild_id) if interaction.guild_id else None,
                                "user": {
                                    "id": str(interaction.user.id),
                                    "name": interaction.user.name,
                                    "avatar_url": interaction.user.display_avatar.url
                                }
                            }
                        ) as resp:
                            if resp.status != 200:
                                print(f"Failed to log command execution: {resp.status} {await resp.text()}")
                    except Exception as e:
                        print(f"Failed to POST command execution: {e}")

                # If hosting is unpaid, block command execution and inform user
                if not is_paid:
                    embed = discord.Embed(
                        title="⚠️ Hosting Payment Required",
                        description=(
                            "This bot's hosting subscription has expired.\n\n"
                            "The bot will continue to barely function, but commands cannot be used "
                            "until hosting is paid for."
                        ),
                        color=discord.Color.red()
                    )

                    embed.add_field(
                        name="Payment Options",
                        value=(
                            "1$ ≙ 3 days of hosting. (10$/month)\n"
                            "Can be paid in any amount, but minimum is 1$.\n"
                            "You can pay via PayPal, Stripe, or Crypto.\n"
                            "`⚠️` We will not refund any payments. We will round down to the nearest dollar amount."
                        ),
                        inline=False
                    )

                    embed.add_field(
                        name="Email",
                        value=f"If not already done, use {self.get_command_link('setup-email')} and enter that email in the checkout window for the bot to recognize your payment. (Bot **Owner** only)",
                        inline=False
                    )

                    view = discord.ui.View()
                    view.add_item(discord.ui.Button(
                        label="Pay Now",
                        style=discord.ButtonStyle.success,
                        url="https://noemt.dev/product/listing-bot-hosting-payment"
                    ))

                    # Respond and do not call super() to prevent the command from executing
                    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
                    return

            # For any interaction types not explicitly blocked/handled above,
            # delegate to the parent implementation so Py‑Cord can dispatch the event normally.
            return await super().on_interaction(interaction)

        except Exception as e:
            # Ensure exceptions in this handler don't prevent normal dispatch
            print(f"Error in on_interaction: {e}")
            traceback.print_exc()
            try:
                return await super().on_interaction(interaction)
            except Exception:
                # If even super fails, swallow to avoid crashing the loop
                return

    @tasks.loop(seconds=60)
    async def update_server_data(self):

        now = datetime.now(timezone.utc)
        current_day = now.day
        current_month = now.month
        current_year = now.year

        if current_day >= 1:
            ai_config = await self.db.fetchone("SELECT monthly_limit, remaining_credits_free, last_reset FROM ai_config")
            if ai_config:
                monthly_limit, remaining_credits_free, last_reset = ai_config
                
                if last_reset:
                    try:
                        last_reset_date = datetime.fromisoformat(last_reset.replace(' ', 'T'))
                        if (last_reset_date.month != current_month or 
                            last_reset_date.year != current_year):
                            await self.db.execute(
                                "UPDATE ai_config SET remaining_credits_free = monthly_limit, last_reset = CURRENT_TIMESTAMP"
                            )
                            print(f"AI credits reset: {remaining_credits_free} -> {monthly_limit} (Monthly reset)")
                    except (ValueError, TypeError) as e:
                        print(f"Error parsing last_reset timestamp: {e}")
                        await self.db.execute(
                            "UPDATE ai_config SET remaining_credits_free = monthly_limit, last_reset = CURRENT_TIMESTAMP"
                        )
                        print(f"AI credits reset: {remaining_credits_free} -> {monthly_limit} (Error recovery)")
                else:
                    await self.db.execute(
                        "UPDATE ai_config SET last_reset = CURRENT_TIMESTAMP"
                    )
                    print("AI credits last_reset timestamp initialized")


        if not os.path.exists("./data/server_data.json"):
            with open("./data/server_data.json", "w") as f:
                json.dump({}, f)

        with open("./data/server_data.json", "r") as f:
            data = json.load(f)

        for guild in self.guilds:

            key = str(guild.id)
            if key not in data:
                data[key] = {}
            
            key_data = {
                "name": guild.name,
                "members": data[key].get("members", []),
                "channels": [],
                "roles": []
            }

            existing_members = {member["id"]: member for member in key_data["members"]}

            for member in guild.members:
                member_data = {
                    "id": member.id,
                    "bot": member.bot,
                    "roles": [role.id for role in member.roles]
                }
                existing_members[member.id] = member_data

            key_data["members"] = list(existing_members.values())

            key_data["channels"] = [
                {
                    channel.name: {
                        "type": str(channel.type),
                        "id": channel.id,
                        "position": channel.position,
                        "category": channel.category.name if channel.category else None,
                        "overwrites": {
                            overwrite.name: [value.value for value in channel.overwrites[overwrite].pair()]
                            for overwrite in channel.overwrites
                        }
                    }
                } for channel in guild.channels
            ]

            key_data["roles"] = [
                {
                    role.name: {
                        "id": role.id,
                        "color": role.color.value,
                        "position": role.position,
                        "permissions": role.permissions.value,
                        "mentionable": role.mentionable,
                        "hoist": role.hoist,
                        "managed": role.managed,
                        "is_bot_managed": role.is_bot_managed(),
                        "is_premium_subscriber": role.is_premium_subscriber()
                    }
                } for role in guild.roles
            ]

            data[key] = key_data

        with open("./data/server_data.json", "w") as f:
            json.dump(data, f)

        try:
            main_guild = self.get_guild(int(await self.db.get_config("main_guild")))
        except Exception as e:
            print(f"Error getting main guild: {e}")

        invite = (await main_guild.invites())[0] if main_guild and (await main_guild.invites()) else None
        self.invite = invite.url if invite else None

    def get_emoji(self, name):
        return self.item_emojis.get(name)

    def load_commands(self):
        for filename in os.listdir("bot/cogs"):
            if filename.endswith(".py"):
                self.load_extension(f"bot.cogs.{filename[:-3]}")

    def run(self, app, port):
        token = os.getenv("TOKEN")
        self.loop.create_task(self.start(token))
        app.bot = self
        self.loop.create_task(app.run_task("0.0.0.0", port=port))
        self.loop.run_forever()

    def get_command_link(self, qualified_name: str) -> str:
        for cog in self.cogs:
            cog_commands = []
            cog_object = self.get_cog(cog)
            for cog_command in cog_object.walk_commands():
                if isinstance(cog_command, discord.SlashCommandGroup):
                    continue
                cog_commands.append(cog_command)

                for command in cog_commands:
                    if command.qualified_name == qualified_name:
                        try:
                            string = f"</{command.qualified_name}:{command.qualified_id}>"
                        except AttributeError:
                            string = f"/{command.qualified_name}"
                        return string

        return "/"+qualified_name

def create_bot():
    intents = discord.Intents.all()
    bot = Bot(command_prefix="!", intents=intents)

    return bot
