import json
import os
import discord
import aiohttp
from datetime import datetime
from dotenv import load_dotenv

from discord.ext import commands

load_dotenv()

BOT_SERVICE_HOST = os.getenv("BOT_SERVICE_HOST", "127.0.0.1")

api_key = ""
color_codes = ["§0", "§1", "§2", "§3", "§4", "§5", "§6", "§7", "§8", "§9", "§a", "§b", "§c", "§d", "§e", "§f", "§undefined"]
bot_name = os.path.basename(os.getcwd())

try:
    with open("../parent_api/ports.json", "r") as f:
        ports: dict = json.load(f)

    port = ports.get(bot_name)
except FileNotFoundError:
    port = 3080

auth_config_options = {
    "auth_on_alt_detect": {
        "description": "Action to take when alternate accounts are detected",
        "type": str,
        "choices": ["verify", "ban", "captcha", "manual"]
    },
    "auth_alt_detected_channel": {
        "description": "Channel to log alternate account detections",
        "type": discord.TextChannel
    },
    "auth_logging_channel": {
        "description": "Channel to log authentication actions",
        "type": discord.TextChannel
    },
}

config_options = {
    "accounts_category": {
        "description": "Category for account listings",
        "type": discord.CategoryChannel,
    },
    "buy_accounts_category": {
        "description": "Category for account buying requests",
        "type": discord.CategoryChannel,
    },
    "profiles_category": {
        "description": "Category for profile listings",
        "type": discord.CategoryChannel,
    },
    "buy_profiles_category": {
        "description": "Category for profile buying requests",
        "type": discord.CategoryChannel,
    },
    "alts_category": {
        "description": "Category for alt account listings",
        "type": discord.CategoryChannel,
    },
    "sell_alt_category": {
        "description": "Category for selling alt accounts",
        "type": discord.CategoryChannel,
    },
    "sell_account_category": {
        "description": "Category for selling main accounts",
        "type": discord.CategoryChannel,
    },
    "sell_profile_category": {
        "description": "Category for selling profiles",
        "type": discord.CategoryChannel,
    },
    "buy_alts_category": {
        "description": "Category for buying alt accounts",
        "type": discord.CategoryChannel,
    },
    "buy_mfa_category": {
        "description": "Category for buying MFA accounts",
        "type": discord.CategoryChannel,
    },
    "sell_mfa_category": {
        "description": "Category for selling MFA accounts",
        "type": discord.CategoryChannel,
    },
    "coins_sell_category": {
        "description": "Category for selling coins",
        "type": discord.CategoryChannel,
    },
    "coins_buy_category": {
        "description": "Category for buying coins",
        "type": discord.CategoryChannel,
    },
    "middleman_category": {
        "description": "Category for middleman requests",
        "type": discord.CategoryChannel,
    },
    "listing_overflow_category": {
        "description": "Category for overflow account listings (how in the fuck)",
        "type": discord.CategoryChannel,
    },
    "seller_role": {
        "description": "Role given to sellers",
        "type": discord.Role,
    },
    "regular_role": {
        "description": "Role given to normal users",
        "type": discord.Role,
    },
    "ping_role": {
        "description": "Role for account pings",
        "type": discord.Role,
    },
    "customer_role": {
        "description": "Role given to customers",
        "type": discord.Role,
    },
    "auth_bot_role": {
        "description": "Role given to auth bots",
        "type": discord.Role,
    },
    "coin_seller_role": {
        "description": "Role given to coin sellers",
        "type": discord.Role,
    },
    "account_seller_role": {
        "description": "Role given to account sellers",
        "type": discord.Role,
    },
    "profile_seller_role": {
        "description": "Role given to profile sellers",
        "type": discord.Role,
    },
    "alt_seller_role": {
        "description": "Role given to alt sellers",
        "type": discord.Role,
    },
    "mfa_seller_role": {
        "description": "Role given to MFA sellers",
        "type": discord.Role,
    },
    "middleman_role": {
        "description": "Role given to middlemen",
        "type": discord.Role,
    },
    "logs_channel": {
        "description": "Channel for logging bot actions",
        "type": discord.TextChannel,
    },
    "vouch_channel": {
        "description": "Channel for user vouches",
        "type": discord.TextChannel,
    },
    "main_guild": {
        "description": "Main guild ID for the bot",
        "type": int,
    },
    "owner_id": {
        "description": "Bot owner ID",
        "type": int,
    },
    "coin_price_buy": {
        "description": "Price for customers to buy coins at",
        "type": float,
    },
    "coin_price_sell": {
        "description": "Price for customers to sell coins at",
        "type": float,
    },
    "non_price": {
        "description": "Price for unranked accounts",
        "type": float,
    },
    "vip_price": {
        "description": "Price for VIP accounts",
        "type": float,
    },
    "vip+_price": {
        "description": "Price for VIP+ accounts",
        "type": float,
    },
    "mvp_price": {
        "description": "Price for MVP accounts",
        "type": float,
    },
    "mvp+_price": {
        "description": "Price for MVP+ accounts",
        "type": float,
    },
    "share_percentage": {
        "description": "Percentage of the sale that goes to the shop owner",
        "type": float,
    },
    "prompt_tos": {
        "description": "Whether to prompt users to accept the TOS",
        "type": bool,
    },
    "terms_of_service": {
        "description": "Terms of service",
        "type": str,
    },
    "ai_info": {
        "description": "Information about the server used for the AI assistant of the bot.",
        "type": str,
    },
    "domain": {
        "description": "Domain for the bot's API",
        "type": str,
    },
    "let_customers_close_tickets": {
        "description": "Whether customers can close their own tickets",
        "type": bool,
    },
}

button_customId_info = {
    "auth:panel:init": {
        "description": "Initializes an authentication panel for the user.",
        "type": discord.ui.Button,
        "text": "Authorize",
        "emoji": "🔐",
        "style": discord.ButtonStyle.gray
    },
    "terms:accept": {
        "description": "Accepts the terms of service.",
        "type": discord.ui.Button,
        "text": "Accept Terms",
        "emoji": "✅",
        "style": discord.ButtonStyle.green
    },
    "buy:coins": {
        "description": "Opens a modal to buy coins.",
        "type": discord.ui.Button,
        "text": "Buy Coins",
        "emoji": "🪙",
        "style": discord.ButtonStyle.green
    },
    "sell:coins": {
        "description": "Opens a modal to sell coins.",
        "type": discord.ui.Button,
        "text": "Sell Coins",
        "emoji": "💰",
        "style": discord.ButtonStyle.gray
    },
    "sell:mfa": {
        "description": "Opens a modal to sell an MFA account.",
        "type": discord.ui.Button,
        "text": "Sell MFA",
        "emoji": "🔑",
        "style": discord.ButtonStyle.gray
    },
    "mfa:buy": {
        "description": "Opens a modal to buy an MFA account.",
        "type": discord.ui.Select
    },
    "request:middleman": {
        "description": "Requests a middleman for a transaction.",
        "type": discord.ui.Button,
        "text": "Request Middleman",
        "emoji": "🕵️",
        "style": discord.ButtonStyle.blurple
    },
    "sell:account": {
        "description": "Opens a modal to sell an account.",
        "type": discord.ui.Button,
        "text": "Sell Account",
        "emoji": "🧑‍💻",
        "style": discord.ButtonStyle.gray
    },
    "sell:profile": {
        "description": "Opens a modal to sell a profile.",
        "type": discord.ui.Button,
        "text": "Sell Profile",
        "emoji": "📝",
        "style": discord.ButtonStyle.gray
    },
    "sell:alt": {
        "description": "Opens a modal to sell an alt account.",
        "type": discord.ui.Button,
        "text": "Sell Alt",
        "emoji": "👤",
        "style": discord.ButtonStyle.gray
    },
}

def is_authorized_to_use_bot(strict=False):
    async def predicate(ctx: discord.ApplicationContext):
        if ctx.author.id in ctx.bot.owner_ids:
            return True
        
        if strict:
            return ctx.author.id in ctx.bot.owner_ids
        
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{BOT_SERVICE_HOST}:{port}/seller?user_id={ctx.author.id}&api_key=ae75e9b7-9f08-4da5-b99b-18b90c4ac7bc") as resp:
                data: dict = await resp.json()
                if data.get("response"):
                    return True
                
                return False
        return True

    return commands.check(predicate)

async def is_seller(user_id: int):
    async def predicate(ctx: discord.ApplicationContext):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{BOT_SERVICE_HOST}:{port}/seller?user_id={user_id}&api_key=ae75e9b7-9f08-4da5-b99b-18b90c4ac7bc") as resp:
                data: dict = await resp.json()
                if data.get("response"):
                    return True
                
                return False
        return False

def is_customer():
    async def predicate(ctx: discord.ApplicationContext):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{BOT_SERVICE_HOST}:{port}/customer?user_id={ctx.author.id}&api_key=ae75e9b7-9f08-4da5-b99b-18b90c4ac7bc") as resp:
                data: dict = await resp.json()
                if data.get("response"):
                    return True
                return False
        return True
    return commands.check(predicate)

class_emoji_mappings = {
    "mage": "BLAZE_ROD",
    "berserk": "IRON_SWORD",
    "archer": "BOW",
    "tank": "IRON_CHESTPLATE",
    "healer": "HEALING_POTION",
    "none": "BOW"
}

slayer_emoji_mappings = {
    "zombie": "ZOMBIE_SLAYER",
    "spider": "SPIDER_SLAYER",
    "wolf": "WOLF_SLAYER",
    "enderman": "ENDERMAN_SLAYER",
    "blaze": "BLAZE_SLAYER",
    "vampire": "VAMPIRE_SLAYER",
}

slayer_names = {
    "zombie": "Revenant Horror",
    "spider": "Tarantula Broodmother",
    "wolf": "Sven Packmaster",
    "enderman": "Voidgloom Seraph",
    "blaze": "Inferno Demonlord",
    "vampire": "Riftstalker Bloodfiend"
}

skill_emoji_mappings = {
    "farming": "GOLDEN_HOE",
    "mining": "STONE_PICKAXE",
    "combat": "STONE_SWORD",
    "foraging": "JUNGLE_SAPLING",
    "fishing": "FISHING_ROD",
    "enchanting": "ENCHANTING_TABLE",
    "alchemy": "BREWING_STAND",
    "taming": "DECOY",
    "catacombs": "MORT",
    "runecrafting": "MAGMA_CREAM",
    "social": "EMERALD",
    "carpentry": "CRAFTING_TABLE"
}

garden_plot_mappings = [
    ["expert_1", "advanced_5", "advanced_1", "advanced_6", "expert_2"],
    ["advanced_7", "intermediate_1", "beginner_1", "intermediate_2", "advanced_8"],
    ["advanced_2", "beginner_2", "unlocked", "beginner_3", "advanced_3"],
    ["advanced_9", "intermediate_3", "beginner_4", "intermediate_4", "advanced_10"],
    ["expert_3", "advanced_11", "advanced_4", "advanced_12", "expert_4"],
]

networth_categories = [{"keys": ["armor", "wardrobe", "equipment"], "title": "Armor"},{"keys": ["inventory", "enderchest", "storage", "personal_vault"], "title": "Items"},{"keys": ["accessories"], "title": "Accessories"},{"keys": ["pets"], "title": "Pets"},]

networth_embed_field_emoji_mappings = {
    "Armor": "IRON_CHESTPLATE",
    "Items": "CHEST",
    "Pets": "DECOY",
    "Accessories": "HEGEMONY_ARTIFACT"
}

rarity_emoji_mappings = {
    "COMMON": "COMMON_C",
    "UNCOMMON": "UNCOMMON_U",
    "RARE": "RARE_R",
    "EPIC": "EPIC_E",
    "LEGENDARY": "LEGENDARY_L",
    "MYTHIC": "MYTHIC_M",
    "MYTHICAL": "MYTHIC_M",
    "SPECIAL": "SPECIAL_S",
    "VERY": "SPECIAL_S",
    "recomb": "RECOMBOBULATOR"
}

hotm_tree_mapping = [
    [
        {"type": "gemstone_infusion", "maxLevel": 3, "name": "Gemstone Infusion"},
        {"type": "gifts_from_the_departed", "maxLevel": 100, "name": "Gifts From The Departed"},
        {"type": "frozen_solid", "maxLevel": 1, "name": "Frozen Solid"},
        {"type": "hungry_for_more", "maxLevel": 50, "name": "Dead Man's Chest"},
        {"type": "excavator", "maxLevel": 50, "name": "Excavator"},
        {"type": "rags_of_riches", "maxLevel": 50, "name": "Rags to Riches"},
        {"type": "hazardous_miner", "maxLevel": 3, "name": "Hazardous Miner"}
    ],
    [
        {"type": "empty"},
        {"type": "surveyor", "maxLevel": 20, "name": "Surveyor"},
        {"type": "empty"},
        {"type": "subzero_mining", "maxLevel": 100, "name": "SubZero Mining"},
        {"type": "empty"},
        {"type": "eager_adventurer", "maxLevel": 100, "name": "Eager Adventurer"},
        {"type": "empty"}
    ],
    [
        {"name": "Keen Eye", "maxLevel": 1, "type": "keen_eye"},
        {"name": "Warm Hearted", "maxLevel": 50, "type": "warm_hearted"},
        {"name": "Dust Collector", "maxLevel": 20, "type": "dust_collector"},
        {"name": "Daily Grind", "maxLevel": 100, "type": "daily_grind"},
        {"name": "Strong Arm", "maxLevel": 100, "type": "strong_arm"},
        {"name": "No Stone Unturned", "maxLevel": 50, "type": "no_stone_unturned"},
        {"name": "Mineshaft Mayhem", "maxLevel": 1, "type": "mineshaft_mayhem"}
    ],
    [
        {"type": "empty"},
        {"type": "mining_speed_2", "maxLevel": 50, "name": "Mining Speed II"},
        {"type": "empty"},
        {"type": "powder_buff", "maxLevel": 50, "name": "Powder Buff"},
        {"type": "empty"},
        {"type": "mining_fortune_2", "maxLevel": 50, "name": "Mining Fortune II"},
        {"type": "empty"}
    ],
    [
        {"type": "vein_seeker", "maxLevel": 1, "name": "Vein Seeker"},
        {"type": "lonesome_miner", "maxLevel": 45, "name": "Lonesome Miner"},
        {"type": "professional", "maxLevel": 140, "name": "Professional"},
        {"type": "mole", "maxLevel": 190, "name": "Mole"},
        {"type": "fortunate", "maxLevel": 20, "name": "Fortunate"},
        {"type": "great_explorer", "maxLevel": 20, "name": "Great Explorer"},
        {"type": "maniac_miner", "maxLevel": 1, "name": "Maniac Miner"}
    ],
    [
        {"type": "empty"},
        {"type": "goblin_killer", "maxLevel": 1, "name": "Goblin Killer"},
        {"type": "empty"},
        {"type": "special_0", "maxLevel": 10, "name": "Peak Of The Mountain"},
        {"type": "empty"},
        {"type": "star_powder", "maxLevel": 1, "name": "Star Powder"},
        {"type": "empty"}
    ],
    [
        {"type": "daily_effect", "maxLevel": 1, "name": "Sky Mall"},
        {"type": "mining_madness", "maxLevel": 1, "name": "Mining Madness"},
        {"type": "mining_experience", "maxLevel": 100, "name": "Seasoned Mineman"},
        {"type": "efficient_miner", "maxLevel": 100, "name": "Efficient Miner"},
        {"type": "experience_orbs", "maxLevel": 80, "name": "Orbiter"},
        {"type": "front_loaded", "maxLevel": 1, "name": "Front Loaded"},
        {"type": "precision_mining", "maxLevel": 1, "name": "Precision Mining"}
    ],
    [
        {"type": "empty"},
        {"type": "random_event", "maxLevel": 45, "name": "Luck Of The Cave"},
        {"type": "empty"},
        {"type": "daily_powder", "maxLevel": 100, "name": "Daily Powder"},
        {"type": "empty"},
        {"type": "fallen_star_bonus", "maxLevel": 30, "name": "Crystallized"},
        {"type": "empty"}
    ],
    [
        {"type": "empty"},
        {"type": "mining_speed_boost", "maxLevel": 1, "name": "Mining Speed Boost"},
        {"type": "titanium_insanium", "maxLevel": 50, "name": "Titanium Insanium"},
        {"type": "mining_fortune", "maxLevel": 50, "name": "Mining Fortune"},
        {"type": "forge_time", "maxLevel": 20, "name": "Quick Forge"},
        {"type": "pickaxe_toss", "maxLevel": 1, "name": "Pickobulus"},
        {"type": "empty"}
    ],
    [
        {"type": "empty"},
        {"type": "empty"},
        {"type": "empty"},
        {"type": "mining_speed", "maxLevel": 50, "name": "Mining Speed"},
        {"type": "empty"},
        {"type": "empty"},
        {"type": "empty"}
    ]
]

special_hotm_types = ["mining_speed_boost", "vein_seeker", "maniac_miner", "pickaxe_toss", "special_0", "gifts_from_the_departed", "hazardous_miner"]

# Cog action types for configuration
cog_action_types = {
    "join_leave_messages": {
        "name": "Join/Leave Messages",
        "description": "Send messages when members join or leave the server",
        "channels": ["join_channel", "leave_channel"],
        "settings": ["join_message", "leave_message"]
    },
    "auto_role": {
        "name": "Auto Role Assignment",
        "description": "Automatically assign roles to new members",
        "settings": ["auto_role_id"]
    },
    "welcome_dm": {
        "name": "Welcome DM",
        "description": "Send a direct message to new members",
        "settings": ["welcome_dm_message"]
    },
    "member_count": {
        "name": "Member Count Display",
        "description": "Update channel names with current member count",
        "channels": ["member_count_channel"],
        "settings": ["member_count_format"]
    },
    "moderation_logs": {
        "name": "Moderation Logs",
        "description": "Log moderation actions to a channel",
        "channels": ["mod_log_channel"]
    },
    "message_logs": {
        "name": "Message Logs",
        "description": "Log deleted and edited messages",
        "channels": ["message_log_channel"]
    },
    "ticket_auto_close": {
        "name": "Ticket Auto Delete",
        "description": "Automatically delete tickets when members leave the server",
        "settings": ["close_delay_minutes"]
    }
}