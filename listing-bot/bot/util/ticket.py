from bot.bot import Bot
import discord
import aiohttp
import os
from bot.util.listing_objects.ticket import OpenedTicket
from bot.util.fetch import fetch_mojang_api
from bot.util.calcs import calculate_coin_price
from bot.util.transform import unabbreviate
from bot.util.get_default_overwrites import get_default_overwrites, get_role_config_name
import aiohttp
from dotenv import load_dotenv

from bot.util.constants import port

load_dotenv()
BOT_SERVICE_HOST = os.getenv("BOT_SERVICE_HOST", "127.0.0.1")

async def hylist_lookup(user_id: int) -> discord.Embed:
    # goodbye the hylist lookup (I might bring back some other feature referencing this function later)
    return None

class LowballView(discord.ui.View):
    def __init__(self, bot: Bot, *args, **kwargs):
        super().__init__(*args, **kwargs, timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="Lowball",
        style=discord.ButtonStyle.grey,
        custom_id="lowball:panel:init"
    )
    async def lowball(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.defer()

        async def check_authorized():

            if interaction.user.id in self.bot.owner_ids:
                return True
            
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://{BOT_SERVICE_HOST}:{port}/seller?user_id={interaction.user.id}&api_key=API_KEY") as resp:
                    data: dict = await resp.json()
                    if data.get("response"):
                        return True
                    
                    return False
            return True
        
        if await check_authorized():
            
            try:
                await interaction.response.defer(ephemeral=True)
            except discord.errors.InteractionResponded:
                pass

            return await self.bot.get_application_command('lowball').callback(self, ctx=interaction, username=interaction.channel.topic, profile=None)

        embed = discord.Embed(
            title="Permission Denied",
            description="You do not have permission to use this button!",
            color=discord.Color.red()
        )
        await interaction.respond(embed=embed, ephemeral=True)

class SellGoods(discord.ui.Modal):
    def __init__(self, bot: Bot, good: str, *args, **kwargs):
        super().__init__(
            discord.ui.InputText(label="Username of the Account", placeholder="56ms"), 
            discord.ui.InputText(label="Method of Payment", placeholder="PayPal"), 
            discord.ui.InputText(label="Offer", placeholder="100$"), 
            *args, **kwargs,
            title=f"Sell a(n) {good.title()}"
        )
        self.bot = bot
        self.good = good
        """
        good can be one of the following:
        alt
        account
        profile
        """

    async def callback(self, interaction: discord.Interaction):

        await interaction.response.defer(ephemeral=True)

        response_embed = discord.Embed(
            color=discord.Color.red()
        )

        open_tickets_user = await self.bot.db.fetchone("SELECT * FROM tickets WHERE opened_by = ?", interaction.user.id)
        if open_tickets_user:
            response_embed.title = "An Error Occurred"
            response_embed.description = "You already have an open ticket, please close that ticket before opening a new one."
            await interaction.respond(embed=response_embed, ephemeral=True)
            return

        username = self.children[0].value
        payment_method = self.children[1].value
        offer = self.children[2].value

        async with aiohttp.ClientSession() as session:
            data, status = await fetch_mojang_api(session, username)
            if data["id"] == "Invalid username.":
                response_embed.title = "An Error Occurred"
                response_embed.description = "The username you provided is invalid."
                await interaction.respond(embed=response_embed, ephemeral=True)
                return

        category = await self.bot.db.get_config(f"sell_{self.good}_category")
        category: discord.CategoryChannel = self.bot.get_channel(category)
        if not category:
            response_embed.title = "An Error Occurred"
            response_embed.description = "An error occurred while fetching the category."
            await interaction.respond(embed=response_embed, ephemeral=True)
            return

        if len(category.channels) >= 50:
            category = None

        overwrites, role, tos_agreed = await get_default_overwrites(self.bot, interaction.guild.id, interaction.user.id, ticket_type=f"sell-{self.good}")

        if category:
            channel = await category.create_text_channel(name=f"sell-{username}", overwrites=overwrites, topic=username)
        else:
            channel = await interaction.guild.create_text_channel(name=f"sell-{username}", overwrites=overwrites, topic=username)

        response_embed.color = discord.Color.green()

        await interaction.user.add_roles(role)
        response_embed.title = "Ticket Created"
        response_embed.description = f"Your ticket has been created, go to {channel.mention}!"

        await interaction.respond(embed=response_embed, ephemeral=True)

        embed = discord.Embed(
            title=f"{self.good.title()} Sale",
            description=f"Thank you for your interest in selling a(n) {self.good}. Please wait for a seller to get to you.",
            color=discord.Color.green()
        )
        embed.add_field(
            name="Payment Method",
            value=payment_method
        )
        embed.add_field(
            name="Offer",
            value=offer
        )
        embed.add_field(
            name="Username",
            value=username
        )

        role_config_name = get_role_config_name(f"sell-{self.good}")
        if role_config_name:
            config_exists = await self.bot.db.get_config(role_config_name)
            if config_exists:
                seller_role = config_exists
            else:
                seller_role = await self.bot.db.get_config("seller_role")

        initial_message = await channel.send(
            embed=embed,
            content=f"<@&{seller_role}>, <@{interaction.user.id}>",
            view=OpenedTicket(self.bot)
        )
        await initial_message.pin()
        await self.bot.db.execute(
            "INSERT INTO tickets (opened_by, channel_id, initial_message_id, role_id, is_open, claimed, ticket_type) VALUES (?, ?, ?, ?, ?, ?, ?)",
            interaction.user.id, channel.id, initial_message.id, role.id, 1, 0, f"sell-{self.good}"
        )

        embed = discord.Embed(
            color=discord.Color.red(),
            description=f"""# Disclaimer
### We will only deal within this ticket\nso if anyone pretending to be one of us messages you, please ignore them."""
        )
        embed.set_footer(text="Made by noemt | https://bots.noemt.dev", icon_url="https://noemt.dev/assets/icon.webp")
        await channel.send(embed=embed)

        hylist_embed = await hylist_lookup(interaction.user.id)
        if hylist_embed:
            await channel.send(embed=hylist_embed)
            await channel.edit(name=f'❌-{channel.name}')

        await channel.send(f'https://sky.shiiyu.moe/stats/{username}', view=LowballView(self.bot))

        if tos_agreed is False:
            await channel.send(
                embed=discord.Embed(
                    title="Terms of Service",
                    description=f"We require you to agree to our Terms of Service before you can buy something.\nRefer to {self.bot.get_command_link('terms view')}.",
                    color=discord.Color.red()
                ))

class CoinTicket(discord.ui.Modal):
    def __init__(self, bot: Bot, buy: bool, *args, **kwargs):
        if buy:
            title = "Buy Coins"
        else:
            title = "Sell Coins"

        super().__init__(
            discord.ui.InputText(label="Username of your Account", placeholder="56ms"), 
            discord.ui.InputText(label="Method of Payment", placeholder="PayPal"), 
            discord.ui.InputText(label="Amount of Coins", placeholder="3b"), 
            *args, **kwargs,
            title=title
        )
        self.bot = bot
        self.buy = buy
        
        self.title = title
        self.verb = "Buy" if buy else "Sell"

    async def callback(self, interaction: discord.Interaction):

        await interaction.response.defer(ephemeral=True)

        response_embed = discord.Embed(
            color=discord.Color.red()
        )

        open_tickets_user = await self.bot.db.fetchone("SELECT * FROM tickets WHERE opened_by = ?", interaction.user.id)
        if open_tickets_user:
            response_embed.title = "An Error Occurred"
            response_embed.description = "You already have an open ticket, please close that ticket before opening a new one."
            await interaction.respond(embed=response_embed, ephemeral=True)
            return

        username = self.children[0].value
        payment_method = self.children[1].value
        amount = self.children[2].value

        async with aiohttp.ClientSession() as session:
            data, status = await fetch_mojang_api(session, username)
            if data["id"] == "Invalid username.":
                response_embed.title = "An Error Occurred"
                response_embed.description = "The username you provided is invalid."
                await interaction.respond(embed=response_embed, ephemeral=True)
                return

        category = await self.bot.db.get_config(f"coins_{self.verb.lower()}_category")
        category: discord.CategoryChannel = self.bot.get_channel(category)
        if not category:
            response_embed.title = "An Error Occurred"
            response_embed.description = "An error occurred while fetching the category."
            await interaction.respond(embed=response_embed, ephemeral=True)
            return
        
        if len(category.channels) >= 50:
            category = None
        
        overwrites, role, tos_agreed = await get_default_overwrites(self.bot, interaction.guild.id, interaction.user.id, ticket_type=f"{self.verb.lower()}-coins")

        if category:
            channel = await category.create_text_channel(name=f"{self.verb}-{amount.replace('.', '-')}", overwrites=overwrites)
        else:
            channel = await interaction.guild.create_text_channel(name=f"{self.verb}-{amount.replace('.', '-')}", overwrites=overwrites)

        response_embed.color = discord.Color.green()

        await interaction.user.add_roles(role)
        response_embed.title = "Ticket Created"
        response_embed.description = f"Your ticket has been created, go to {channel.mention}!"

        await interaction.respond(embed=response_embed, ephemeral=True)

        embed = discord.Embed(
            title=self.title,
            description=f"Thank you for your interest in {self.verb.lower()}ing coins. Please wait for a seller to get to you.",
            color=discord.Color.green()
        )
        embed.add_field(
            name="Payment Method",
            value=payment_method
        )
        embed.add_field(
            name="Amount",
            value=f'{amount} ({round((await calculate_coin_price(self.verb.lower(), self.bot, unabbreviate(amount))), 2)}$)'
        )
        embed.add_field(
            name="Username",
            value=username
        )

        role_config_name = get_role_config_name(f"{self.verb.lower()}-coins")
        if role_config_name:
            config_exists = await self.bot.db.get_config(role_config_name)
            if config_exists:
                seller_role = config_exists
            else:
                seller_role = await self.bot.db.get_config("seller_role")

        initial_message = await channel.send(
            embed=embed,
            content=f"<@&{seller_role}>, <@{interaction.user.id}>",
            view=OpenedTicket(self.bot)
        )
        await initial_message.pin()
        await self.bot.db.execute(
            "INSERT INTO tickets (opened_by, channel_id, initial_message_id, role_id, is_open, claimed, ticket_type) VALUES (?, ?, ?, ?, ?, ?, ?)",
            interaction.user.id, channel.id, initial_message.id, role.id, 1, 0, f"{self.verb.lower()}-coins"
        )

        embed = discord.Embed(
            color=discord.Color.red(),
            description=f"""# Disclaimer
### We will only deal within this ticket\nso if anyone pretending to be one of us messages you, please ignore them."""
        )
        embed.set_footer(text="Made by noemt | https://bots.noemt.dev", icon_url="https://noemt.dev/assets/icon.webp")
        await channel.send(embed=embed)

        hylist_embed = await hylist_lookup(interaction.user.id)
        if hylist_embed:
            await channel.send(embed=hylist_embed)
            await channel.edit(name=f'❌-{channel.name}')

        await channel.send(f'https://sky.shiiyu.moe/stats/{username}')

        if tos_agreed is False:
            await channel.send(
                embed=discord.Embed(
                    title="Terms of Service",
                    description=f"We require you to agree to our Terms of Service before you can buy something.\nRefer to {self.bot.get_command_link('terms view')}.",
                    color=discord.Color.red()
                ))

class MFASell(discord.ui.Modal):
    def __init__(self, bot: Bot, *args, **kwargs):

        super().__init__(
            discord.ui.InputText(label="Rank", placeholder="VIP+"), 
            discord.ui.InputText(label="Method of Payment", placeholder="PayPal"), 
            discord.ui.InputText(label="How many MFA's?", placeholder="3"), 
            *args, **kwargs,
            title="Sell an MFA"
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)


        response_embed = discord.Embed(
            color=discord.Color.red()
        )

        open_tickets_user = await self.bot.db.fetchone("SELECT * FROM tickets WHERE opened_by = ?", interaction.user.id)
        if open_tickets_user:
            response_embed.title = "An Error Occurred"
            response_embed.description = "You already have an open ticket, please close that ticket before opening a new one."
            await interaction.respond(embed=response_embed, ephemeral=True)
            return
        
        rank = self.children[0].value.replace("+", "-plus")
        payment_method = self.children[1].value
        amount = self.children[2].value

        category = await self.bot.db.get_config(f"sell_mfa_category")
        category: discord.CategoryChannel = self.bot.get_channel(category)
        if not category:
            response_embed.title = "An Error Occurred"
            response_embed.description = "An error occurred while fetching the category."
            await interaction.respond(embed=response_embed, ephemeral=True)
            return
        
        if len(category.channels) >= 50:
            category = None
        
        overwrites, role, tos_agreed = await get_default_overwrites(self.bot, interaction.guild.id, interaction.user.id, ticket_type=f"sell-mfa")

        if category:
            channel = await category.create_text_channel(name=f"sell-{rank}-{amount}", overwrites=overwrites)
        else:
            channel = await interaction.guild.create_text_channel(name=f"sell-{rank}-{amount}", overwrites=overwrites)

        response_embed.color = discord.Color.green()

        await interaction.user.add_roles(role)
        response_embed.title = "Ticket Created"
        response_embed.description = f"Your ticket has been created, go to {channel.mention}!"

        await interaction.respond(embed=response_embed, ephemeral=True)

        embed = discord.Embed(
            title=self.title,
            description=f"Thank you for your interest in selling an MFA. Please wait for a seller to get to you.",
            color=discord.Color.green()
        )
        embed.add_field(
            name="Payment Method",
            value=payment_method
        )
        embed.add_field(
            name="Amount",
            value=f'{amount}'
        )
        embed.add_field(
            name="Rank",
            value=self.children[0].value
        )

        role_config_name = get_role_config_name(f"sell-mfa")
        if role_config_name:
            config_exists = await self.bot.db.get_config(role_config_name)
            if config_exists:
                seller_role = config_exists
            else:
                seller_role = await self.bot.db.get_config("seller_role")

        initial_message = await channel.send(
            embed=embed,
            content=f"<@&{seller_role}>, <@{interaction.user.id}>",
            view=OpenedTicket(self.bot)
        )
        await initial_message.pin()
        await self.bot.db.execute(
            "INSERT INTO tickets (opened_by, channel_id, initial_message_id, role_id, is_open, claimed, ticket_type) VALUES (?, ?, ?, ?, ?, ?, ?)",
            interaction.user.id, channel.id, initial_message.id, role.id, 1, 0, "sell-mfa"
        )

        embed = discord.Embed(
            color=discord.Color.red(),
            description=f"""# Disclaimer
### We will only deal within this ticket\nso if anyone pretending to be one of us messages you, please ignore them."""
        )
        embed.set_footer(text="Made by noemt | https://bots.noemt.dev", icon_url="https://noemt.dev/assets/icon.webp")
        await channel.send(embed=embed)

        hylist_embed = await hylist_lookup(interaction.user.id)
        if hylist_embed:
            await channel.send(embed=hylist_embed)
            await channel.edit(name=f'❌-{channel.name}')

        if tos_agreed is False:
            await channel.send(
                embed=discord.Embed(
                    title="Terms of Service",
                    description=f"We require you to agree to our Terms of Service before you can buy something.\nRefer to {self.bot.get_command_link('terms view')}.",
                    color=discord.Color.red()
                ))

class MFABuy(discord.ui.Modal):
    def __init__(self, bot: Bot, rank: str, *args, **kwargs):

        super().__init__(
            discord.ui.InputText(label="Rank", placeholder="VIP+", value=rank), 
            discord.ui.InputText(label="Method of Payment", placeholder="PayPal"), 
            discord.ui.InputText(label="How many MFA's?", placeholder="3"), 
            *args, **kwargs,
            title="Buy an MFA"
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)


        response_embed = discord.Embed(
            color=discord.Color.red()
        )

        open_tickets_user = await self.bot.db.fetchone("SELECT * FROM tickets WHERE opened_by = ?", interaction.user.id)
        if open_tickets_user:
            response_embed.title = "An Error Occurred"
            response_embed.description = "You already have an open ticket, please close that ticket before opening a new one."
            await interaction.respond(embed=response_embed, ephemeral=True)
            return
        
        rank = self.children[0].value.replace("+", "-plus")
        payment_method = self.children[1].value
        amount = self.children[2].value

        category = await self.bot.db.get_config(f"buy_mfa_category")
        category: discord.CategoryChannel = self.bot.get_channel(category)
        if not category:
            response_embed.title = "An Error Occurred"
            response_embed.description = "An error occurred while fetching the category."
            await interaction.respond(embed=response_embed, ephemeral=True)
            return
        
        if len(category.channels) >= 50:
            category = None
        
        overwrites, role, tos_agreed = await get_default_overwrites(self.bot, interaction.guild.id, interaction.user.id, ticket_type=f"buy-mfa")
        
        if category:
            channel = await category.create_text_channel(name=f"buy-{rank}-{amount}", overwrites=overwrites)
        else:
            channel = await interaction.guild.create_text_channel(name=f"buy-{rank}-{amount}", overwrites=overwrites)

        response_embed.color = discord.Color.green()

        await interaction.user.add_roles(role)
        response_embed.title = "Ticket Created"
        response_embed.description = f"Your ticket has been created, go to {channel.mention}!"

        await interaction.respond(embed=response_embed, ephemeral=True)

        embed = discord.Embed(
            title=self.title,
            description=f"Thank you for your interest in buying an MFA. Please wait for a seller to get to you.",
            color=discord.Color.green()
        )
        embed.add_field(
            name="Payment Method",
            value=payment_method
        )
        embed.add_field(
            name="Amount",
            value=f'{amount}'
        )
        embed.add_field(
            name="Rank",
            value=self.children[0].value
        )

        role_config_name = get_role_config_name(f"buy-mfa")
        if role_config_name:
            config_exists = await self.bot.db.get_config(role_config_name)
            if config_exists:
                seller_role = config_exists
            else:
                seller_role = await self.bot.db.get_config("seller_role")

        initial_message = await channel.send(
            embed=embed,
            content=f"<@&{seller_role}>, <@{interaction.user.id}>",
            view=OpenedTicket(self.bot)
        )
        await initial_message.pin()
        await self.bot.db.execute(
            "INSERT INTO tickets (opened_by, channel_id, initial_message_id, role_id, is_open, claimed, ticket_type) VALUES (?, ?, ?, ?, ?, ?, ?)",
            interaction.user.id, channel.id, initial_message.id, role.id, 1, 0, "buy-mfa"
        )

        embed = discord.Embed(
            color=discord.Color.red(),
            description=f"""# Disclaimer
### We will only deal within this ticket\nso if anyone pretending to be one of us messages you, please ignore them."""
        )
        embed.set_footer(text="Made by noemt | https://bots.noemt.dev", icon_url="https://noemt.dev/assets/icon.webp")
        await channel.send(embed=embed)

        hylist_embed = await hylist_lookup(interaction.user.id)
        if hylist_embed:
            await channel.send(embed=hylist_embed)
            await channel.edit(name=f'❌-{channel.name}')

        if tos_agreed is False:
            await channel.send(
                embed=discord.Embed(
                    title="Terms of Service",
                    description=f"We require you to agree to our Terms of Service before you can buy something.\nRefer to {self.bot.get_command_link('terms view')}.",
                    color=discord.Color.red()
                ))


class MiddlemanTicket(discord.ui.Modal):
    def __init__(self, bot: Bot, *args, **kwargs):

        super().__init__(
            discord.ui.InputText(label="Amount involved", placeholder="100$"), 
            discord.ui.InputText(label="Description of the deal", placeholder="Account Sale"), 
            discord.ui.InputText(label="Discord ID of the other user", placeholder="1323257877711818753"), 
            *args, **kwargs,
            title="Request a Middleman"
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        amount = self.children[0].value
        description = self.children[1].value
        user_id = self.children[2].value

        response_embed = discord.Embed(
            color=discord.Color.red()
        )

        if not user_id.isdigit():
            response_embed.title = "An Error Occurred"
            response_embed.description = "[The Discord ID you provided is invalid.](https://www.youtube.com/watch?v=mc3cV57m3mM)"
            await interaction.respond(embed=response_embed, ephemeral=True)
            return
        
        other_member = await interaction.guild.fetch_member(int(user_id))
        if not other_member:
            response_embed.title = "An Error Occurred"
            response_embed.description = "The user you provided is not in this server."
            await interaction.respond(embed=response_embed, ephemeral=True)
            return

        open_tickets_user = await self.bot.db.fetchone("SELECT * FROM tickets WHERE opened_by = ?", interaction.user.id)
        if open_tickets_user:
            response_embed.title = "An Error Occurred"
            response_embed.description = "You already have an open ticket, please close that ticket before opening a new one."
            await interaction.respond(embed=response_embed, ephemeral=True)
            return

        category = await self.bot.db.get_config(f"middleman_category")
        category: discord.CategoryChannel = self.bot.get_channel(category)
        if not category:
            response_embed.title = "An Error Occurred"
            response_embed.description = "An error occurred while fetching the category."
            await interaction.respond(embed=response_embed, ephemeral=True)
            return
        
        if len(category.channels) >= 50:
            category = None
        
        overwrites, role, tos_agreed = await get_default_overwrites(self.bot, interaction.guild.id, interaction.user.id, ticket_type=f"middleman")
        
        if category:
            channel = await category.create_text_channel(name=f"middleman-{amount}", overwrites=overwrites)
        else:
            channel = await interaction.guild.create_text_channel(name=f"middleman-{amount}", overwrites=overwrites)
            
        response_embed.color = discord.Color.green()

        await interaction.user.add_roles(role)
        await other_member.add_roles(role)

        response_embed.title = "Ticket Created"
        response_embed.description = f"Your ticket has been created, go to {channel.mention}!"

        await interaction.respond(embed=response_embed, ephemeral=True)

        embed = discord.Embed(
            title=self.title,
            description=f"Thank you for choosing our middlemanning service. Please wait for a middleman to get to you.",
            color=discord.Color.green()
        )
        embed.add_field(
            name="Amount Involved",
            value=amount
        )
        embed.add_field(
            name="Deal Desciption",
            value=description
        )
        embed.add_field(
            name="Discord ID of the other user",
            value=user_id
        )

        role_config_name = get_role_config_name(f"middleman")
        if role_config_name:
            config_exists = await self.bot.db.get_config(role_config_name)
            if config_exists:
                seller_role = config_exists
            else:
                seller_role = await self.bot.db.get_config("seller_role")

        initial_message = await channel.send(
            embed=embed,
            content=f"<@&{seller_role}>, <@{interaction.user.id}>, {other_member.mention}",
            view=OpenedTicket(self.bot)
        )
        await initial_message.pin()
        await self.bot.db.execute(
            "INSERT INTO tickets (opened_by, channel_id, initial_message_id, role_id, is_open, claimed, ticket_type) VALUES (?, ?, ?, ?, ?, ?, ?)",
            interaction.user.id, channel.id, initial_message.id, role.id, 1, 0, "middleman"
        )

        embed = discord.Embed(
            color=discord.Color.red(),
            description=f"""# Disclaimer
### We will only deal within this ticket\nso if anyone pretending to be one of us messages you, please ignore them."""
        )
        embed.set_footer(text="Made by noemt | https://bots.noemt.dev", icon_url="https://noemt.dev/assets/icon.webp")
        await channel.send(embed=embed)

        if tos_agreed is False:
            await channel.send(
                embed=discord.Embed(
                    title="Terms of Service",
                    description=f"We require you to agree to our Terms of Service before you can buy something.\nRefer to {self.bot.get_command_link('terms view')}.",
                    color=discord.Color.red()
                ))
