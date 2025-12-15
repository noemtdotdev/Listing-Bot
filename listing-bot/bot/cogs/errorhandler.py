import discord
from discord.ext import commands
import traceback
import asyncio
import aiohttp
import datetime

import os
import io
from bot.util.errors import MojangError, ApiError

class ErrorHandler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Set up UI error handling for PyChord
        self._setup_ui_error_handling()

    def _get_github_link(self, error: Exception) -> str | None:
        """
        Generate a GitHub link to the file and line number where the error occurred.
        Tries to find the most relevant frame in the bot's codebase.
        """
        try:
            # Extract traceback stacks
            tb = traceback.extract_tb(error.__traceback__)
            
            # Iterate in reverse to find the most recent call in our code
            for frame in reversed(tb):
                filename = frame.filename
                # Normalize path separators
                filename = filename.replace('\\', '/')
                
                # Filter out standard library and site-packages
                if '/lib/' in filename or '/site-packages/' in filename:
                    continue
                
                try:
                    # Determine the project root relative to this file
                    # This file is in bot/cogs/errorhandler.py
                    # We want the parent directory of 'bot'
                    current_file = os.path.abspath(__file__)
                    # .../bot/cogs/errorhandler.py -> .../bot/cogs -> .../bot -> .../listing-bot
                    project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
                    
                    # Get path relative to the project root
                    rel_path = os.path.relpath(frame.filename, project_root)
                    rel_path = rel_path.replace('\\', '/')
                    
                    # If the path starts with .., it's outside the project, skip
                    if rel_path.startswith('..'):
                        continue
                        
                    return f"https://github.com/noemtdotdev/Listing-Bot/tree/master/listing-bot/{rel_path}#L{frame.lineno}"
                except ValueError:
                    continue

            return None
        except Exception as e:
            print(f"Error generating GitHub link: {e}")
            return None

    def _setup_ui_error_handling(self):
        """Set up UI component error handling for PyChord"""
        # Store original error handler methods
        self._original_modal_on_error = getattr(discord.ui.Modal, 'on_error', None)
        self._original_view_on_error = getattr(discord.ui.View, 'on_error', None)
        
        # Define custom error handlers
        async def modal_error_handler(modal_self, error, interaction):
            await self._handle_ui_error(interaction, error, "Modal")
            
        async def view_error_handler(view_self, error, item, interaction):
            await self._handle_ui_error(interaction, error, "Button")
        
        # Patch the error handlers
        discord.ui.Modal.on_error = modal_error_handler
        discord.ui.View.on_error = view_error_handler

    async def _handle_ui_error(self, interaction: discord.Interaction, error: Exception, component_type: str):
        """Handle UI component errors with full traceback and webhook notification"""
        try:
            # Check if this is a timeout error (Unknown Interaction)
            if isinstance(error, discord.NotFound):
                # DM the user about timeout, don't send webhook
                try:
                    dm_desc = "The bot failed to respond in time, please retry!"
                    dm_embed = self._create_error_embed(dm_desc)
                    await interaction.user.send(embed=dm_embed)
                    print(f"Sent timeout notification DM to {interaction.user}")
                except Exception as dm_error:
                    print(f"Failed to DM user {interaction.user} about timeout: {dm_error}")
                return
            
            # Check if this is an ApiError
            if isinstance(error, ApiError):
                # Respond with the error message and don't send webhook
                try:
                    error_desc = f"🌐 API Error: {error.message}"
                    error_embed = self._create_error_embed(error_desc)
                    if not interaction.response.is_done():
                        await interaction.response.send_message(embed=error_embed, ephemeral=True)
                    else:
                        await interaction.followup.send(embed=error_embed, ephemeral=True)
                    return
                except Exception as response_error:
                    # If we can't respond, try to DM
                    try:
                        await interaction.user.send(embed=error_embed)
                    except:
                        pass
                    return
            
            # Get full traceback
            error_trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
            
            # Generate GitHub link
            github_link = self._get_github_link(error)
            
            # Create user-facing error message
            error_msg = str(error)
            if not error_msg:
                error_msg = f"{type(error).__name__} occurred"
            
            # Create detailed error embed for webhook
            detailed_embed = discord.Embed(
                title=f"🚫 {component_type} Error",
                color=discord.Color.brand_red(),
                timestamp=datetime.datetime.utcnow()
            )
            detailed_embed.add_field(
                name="Error Type",
                value=f"`{type(error).__name__}`",
                inline=True
            )
            detailed_embed.add_field(
                name="Error Message",
                value=f"```{error_msg[:1000]}```",
                inline=False
            )
            
            if github_link:
                detailed_embed.add_field(
                    name="Source Location",
                    value=f"[View on GitHub]({github_link})",
                    inline=False
                )
            
            # Prepare traceback field or file
            file_attachment = None
            if len(error_trace) > 950:
                detailed_embed.add_field(
                    name="Full Traceback",
                    value="*Traceback too long, attached as file*",
                    inline=False
                )
                file_attachment = discord.File(io.StringIO(error_trace), filename="traceback.txt")
            else:
                detailed_embed.add_field(
                    name="Full Traceback",
                    value=f"```py\n{error_trace}```",
                    inline=False
                )
            
            if interaction.guild:
                detailed_embed.add_field(
                    name="Server",
                    value=f"{interaction.guild.name} (`{interaction.guild.id}`)",
                    inline=True
                )
            
            detailed_embed.add_field(
                name="User",
                value=f"{interaction.user} (`{interaction.user.id}`)",
                inline=True
            )
            
            detailed_embed.add_field(
                name="Component Type",
                value=component_type,
                inline=True
            )
            
            # Create simple user response
            user_desc = f"🚫 {component_type} Error: {error_msg}\n\n🔔 The developer has quit this project, open sourcing it."
            if github_link:
                user_desc += f"\n\n🛠️ [View Error Source]({github_link})\n*You are invited to fix the code yourself and to file a PR.*"
                
            user_embed = self._create_error_embed(user_desc)
            
            # Try to respond to the interaction
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=user_embed, ephemeral=True)
            else:
                await interaction.followup.send(embed=user_embed, ephemeral=True)
                
            # Send to webhook after successful response
            await self._send_error_webhook(detailed_embed, component_type.lower(), file=file_attachment)
                
            # Also log the full error to console
            print(f"\n{'='*50}")
            print(f"{component_type} ERROR:")
            print(f"{'='*50}")
            traceback.print_exception(type(error), error, error.__traceback__)
            print(f"{'='*50}\n")
            
        except Exception as response_error:
            # If we can't respond to the interaction, handle based on error type
            if isinstance(response_error, discord.NotFound):
                # Interaction timed out - DM the user and skip webhook
                try:
                    dm_desc = "The bot failed to respond in time, please retry!"
                    dm_embed = self._create_error_embed(dm_desc)
                    await interaction.user.send(embed=dm_embed)
                    print(f"Sent timeout notification DM to {interaction.user}")
                except Exception as dm_error:
                    print(f"Failed to DM user {interaction.user} about timeout: {dm_error}")
            else:
                # Other response failure - still send webhook
                await self._send_error_webhook(detailed_embed, component_type.lower(), file=file_attachment)
                print(f"Failed to respond to {component_type.lower()} error: {response_error}")
            print(f"Original {component_type.lower()} error: {error}")
            traceback.print_exception(type(error), error, error.__traceback__)

    async def _send_error_webhook(self, embed: discord.Embed, error_source: str, file: discord.File = None):
        """Send error information to webhook"""
        try:
            # Hardcoded webhook URL
            webhook_url = "https://discord.com/api/webhooks/1397964240366731405/AeF5QNtX4ORQ1agL1U3VHHo04GiD45jguu4xfiBhHu02z2IcP9eCxnzPUQOWlWjOoh18"
            
            async with aiohttp.ClientSession() as session:
                webhook_data = {
                    "embeds": [embed.to_dict()],
                    "content": f"🚨 **{error_source.title()} Error Detected** 🚨 | @everyone"
                }
                
                # Prepare data without file for initial payload construction
                data = aiohttp.FormData()
                data.add_field('payload_json', discord.utils.to_json(webhook_data))
                
                if file:
                    data.add_field('file', file.fp, filename=file.filename, content_type='text/plain')
                
                async with session.post(webhook_url, data=data) as response:
                    if response.status not in (200, 204):
                        print(f"Failed to send error webhook: {response.status}")
                        
        except Exception as webhook_error:
            print(f"Error sending webhook notification: {webhook_error}")

    def _create_error_embed(self, description: str) -> discord.Embed:
        """Helper function to create consistent error embeds"""
        embed = discord.Embed(
            color=discord.Color.brand_red(),
            title="⚠️ An Error Occurred",
            description=description
        )
        embed.set_footer(
            text="Made by noemt", 
            icon_url="https://noemt.dev/assets/icon.webp"
        )
        return embed

    @commands.Cog.listener()
    async def on_application_command_error(self, ctx: discord.ApplicationContext, error: discord.ApplicationCommandError):
        """Handle application command errors"""
        error = getattr(error, 'original', error)
        
        try:
            if isinstance(error, commands.CommandOnCooldown):
                desc = f"⏳ Please wait {error.retry_after:.1f} seconds before using this command again."
                await ctx.respond(embed=self._create_error_embed(desc), ephemeral=True)

            elif isinstance(error, (commands.MissingPermissions, commands.BotMissingPermissions)):
                perms = ", ".join(f"`{perm}`" for perm in error.missing_permissions)
                actor = "You need" if isinstance(error, commands.MissingPermissions) else "I need"
                desc = f"🔒 {actor} these permissions: {perms}"
                await ctx.respond(embed=self._create_error_embed(desc), ephemeral=True)

            elif isinstance(error, commands.MissingRole):
                roles = ", ".join(f"`{role}`" for role in error.missing_roles)
                desc = f"🎖️ You need these roles: {roles}"
                await ctx.respond(embed=self._create_error_embed(desc), ephemeral=True)

            elif isinstance(error, commands.NotOwner):
                desc = "🔑 This command is restricted to the bot owner."
                await ctx.respond(embed=self._create_error_embed(desc), ephemeral=True)

            elif isinstance(error, commands.NoPrivateMessage):
                desc = "📨 This command only works in servers."
                await ctx.respond(embed=self._create_error_embed(desc), ephemeral=True)

            elif isinstance(error, commands.PrivateMessageOnly):
                desc = "📩 This command only works in DMs."
                await ctx.respond(embed=self._create_error_embed(desc), ephemeral=True)

            elif isinstance(error, discord.errors.CheckFailure):
                desc = "🔒 You do not have permission to use this command."
                await ctx.respond(embed=self._create_error_embed(desc), ephemeral=True)
            
            elif isinstance(error, discord.errors.Forbidden):
                desc = "🚫 I do not have permission to perform this action."
                await ctx.respond(embed=self._create_error_embed(desc), ephemeral=True)

            elif isinstance(error, discord.ApplicationCommandInvokeError):
                if isinstance(error.original, MojangError):
                    desc = f"❌ Mojang API Error: {error.original.message}"
                    await ctx.respond(embed=self._create_error_embed(desc), ephemeral=True)
                elif isinstance(error.original, ApiError):
                    desc = f"🌐 API Error: {error.original.message}"
                    await ctx.respond(embed=self._create_error_embed(desc), ephemeral=True)
                else:
                    await self._handle_unknown_error(ctx, error.original)

            elif isinstance(error, ApiError):
                desc = f"🌐 API Error: {error.message}"
                await ctx.respond(embed=self._create_error_embed(desc), ephemeral=True)

            else:
                await self._handle_unknown_error(ctx, error)

        except discord.HTTPException:
            traceback.print_exc()

    async def _handle_unknown_error(self, ctx, error):
        """Handle uncaught exceptions with webhook notification"""
        try:
            # Get full traceback
            error_trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
            
            # Generate GitHub link
            github_link = self._get_github_link(error)
            
            # Create detailed error embed for webhook
            detailed_embed = discord.Embed(
                title="🚨 Unhandled Command Error",
                color=discord.Color.dark_red(),
                timestamp=datetime.datetime.utcnow()
            )
            detailed_embed.add_field(
                name="Command",
                value=f"`/{ctx.command.qualified_name if ctx.command else 'Unknown'}`",
                inline=True
            )
            detailed_embed.add_field(
                name="Error Type",
                value=f"`{type(error).__name__}`",
                inline=True
            )
            detailed_embed.add_field(
                name="Error Message",
                value=f"```{str(error)[:1000]}```",
                inline=False
            )
            
            if github_link:
                detailed_embed.add_field(
                    name="Source Location",
                    value=f"[View on GitHub]({github_link})",
                    inline=False
                )
            
            # Prepare traceback field or file
            file_attachment = None
            if len(error_trace) > 950:
                detailed_embed.add_field(
                    name="Full Traceback",
                    value="*Traceback too long, attached as file*",
                    inline=False
                )
                file_attachment = discord.File(io.StringIO(error_trace), filename="traceback.txt")
            else:
                detailed_embed.add_field(
                    name="Full Traceback",
                    value=f"```py\n{error_trace}```",
                    inline=False
                )
            
            if ctx.guild:
                detailed_embed.add_field(
                    name="Server",
                    value=f"{ctx.guild.name} (`{ctx.guild.id}`)",
                    inline=True
                )
            
            detailed_embed.add_field(
                name="User",
                value=f"{ctx.author} (`{ctx.author.id}`)",
                inline=True
            )
            
            # Send to webhook
            await self._send_error_webhook(detailed_embed, "command", file=file_attachment)
            
            # Create user response with developer notification
            user_desc = f"❌ An unexpected error occurred.\n\n🔔 The developer has been automatically notified and will investigate this issue."
            if github_link:
                user_desc += f"\n\n🛠️ [View Error Source]({github_link})"
                
            user_embed = self._create_error_embed(user_desc)
            
            await ctx.respond(embed=user_embed, ephemeral=True)
            
            # Console logging
            print(f"\n{'='*50}")
            print(f"UNHANDLED COMMAND ERROR:")
            print(f"Command: {ctx.command.qualified_name if ctx.command else 'Unknown'}")
            print(f"{'='*50}")
            traceback.print_exception(type(error), error, error.__traceback__)
            print(f"{'='*50}\n")
            
        except Exception as handle_error:
            # Fallback if our error handling fails
            print(f"Error in error handler: {handle_error}")
            traceback.print_exception(type(error), error, error.__traceback__)
            
            # Simple fallback response
            try:
                simple_desc = "❌ An error occurred and could not be processed properly."
                await ctx.respond(embed=self._create_error_embed(simple_desc), ephemeral=True)
            except:
                pass

def setup(bot):
    bot.add_cog(ErrorHandler(bot))
