import discord
import os
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
from pathlib import Path

from discord.ext import commands
from discord import ui
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ===== CONFIGURATION =====
class Config:
    """Configuration management with validation"""
    
    def __init__(self):
        self.load_environment_variables()
        self.validate_config()
        
    def load_environment_variables(self):
        """Load and validate environment variables"""
        self.discord_token = os.getenv("DISCORD_TOKEN")
        self.moderator_channel_id = self._parse_int_env("MODERATOR_CHANNEL_ID")
        
        # Timeout durations (in seconds)
        self.warning_timeout = self._parse_int_env("WARNING_TIMEOUT", 60)      # 1 minute
        self.standard_timeout = self._parse_int_env("STANDARD_TIMEOUT", 300)   # 5 minutes
        self.long_timeout = self._parse_int_env("LONG_TIMEOUT", 3600)          # 1 hour
        
        # Logging configuration
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        self.log_to_file = os.getenv("LOG_TO_FILE", "false").lower() == "true"
        self.log_file = os.getenv("LOG_FILE", "moderation.log")
        
        # Warning system
        self.max_warnings = self._parse_int_env("MAX_WARNINGS", 3)
        self.warning_file = os.getenv("WARNING_FILE", "warnings.json")
        
        # Admin protection
        self.protect_admins = os.getenv("PROTECT_ADMINS", "true").lower() == "true"
        
    def _parse_int_env(self, key: str, default: int = 0) -> int:
        """Parse integer from environment variable with fallback"""
        try:
            value = os.getenv(key, str(default))
            return int(value)
        except (ValueError, TypeError):
            logging.warning(f"Invalid {key}, using default: {default}")
            return default
    
    def validate_config(self):
        """Validate critical configuration values"""
        if not self.discord_token:
            raise ValueError("DISCORD_TOKEN environment variable is required")
        
        if not self.moderator_channel_id:
            raise ValueError("MODERATOR_CHANNEL_ID environment variable is required")
        
        if self.max_warnings < 1:
            raise ValueError("MAX_WARNINGS must be at least 1")

# Initialize configuration
config = Config()

# ===== LOGGING SYSTEM =====
def setup_logging():
    """Setup comprehensive logging system"""
    # Create logger
    logger = logging.getLogger('discord_moderation')
    logger.setLevel(getattr(logging, config.log_level.upper()))
    
    # Clear existing handlers
    logger.handlers.clear()
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # File handler (optional)
    if config.log_to_file:
        file_handler = logging.FileHandler(config.log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    
    return logger

# Initialize logging
logger = setup_logging()

# ===== WARNING SYSTEM =====
class WarningSystem:
    """Persistent warning system for user moderation"""
    
    def __init__(self, warning_file: str):
        self.warning_file = Path(warning_file)
        self.warnings: Dict[str, Dict[str, Any]] = {}
        self.load_warnings()
    
    def load_warnings(self):
        """Load warnings from JSON file"""
        try:
            if self.warning_file.exists():
                with open(self.warning_file, 'r', encoding='utf-8') as f:
                    self.warnings = json.load(f)
                logger.info(f"Loaded {len(self.warnings)} warning records")
            else:
                self.warnings = {}
                logger.info("No existing warning file found, starting fresh")
        except Exception as e:
            logger.error(f"Error loading warnings: {e}")
            self.warnings = {}
    
    def save_warnings(self):
        """Save warnings to JSON file"""
        try:
            # Create directory if it doesn't exist
            self.warning_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.warning_file, 'w', encoding='utf-8') as f:
                json.dump(self.warnings, f, indent=2, ensure_ascii=False)
            logger.debug("Warnings saved successfully")
        except Exception as e:
            logger.error(f"Error saving warnings: {e}")
    
    def get_user_warnings(self, user_id: str, guild_id: str) -> int:
        """Get warning count for a user in a specific guild"""
        key = f"{guild_id}_{user_id}"
        user_data = self.warnings.get(key, {})
        return user_data.get('count', 0)
    
    def add_warning(self, user_id: str, guild_id: str, username: str, reason: str) -> int:
        """Add a warning to a user and return new total"""
        key = f"{guild_id}_{user_id}"
        
        if key not in self.warnings:
            self.warnings[key] = {
                'count': 0,
                'warnings': [],
                'created_at': datetime.now().isoformat()
            }
        
        # Add new warning
        self.warnings[key]['count'] += 1
        self.warnings[key]['warnings'].append({
            'timestamp': datetime.now().isoformat(),
            'reason': reason,
            'username': username
        })
        
        # Clean old warnings (keep last 10)
        if len(self.warnings[key]['warnings']) > 10:
            self.warnings[key]['warnings'] = self.warnings[key]['warnings'][-10:]
        
        self.save_warnings()
        return self.warnings[key]['count']
    
    def clear_warnings(self, user_id: str, guild_id: str):
        """Clear all warnings for a user"""
        key = f"{guild_id}_{user_id}"
        if key in self.warnings:
            del self.warnings[key]
            self.save_warnings()
            logger.info(f"Cleared warnings for user {user_id}")

# Initialize warning system
warning_system = WarningSystem(config.warning_file)

# ===== BOT SETUP =====
# Configure intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# Initialize bot
bot = commands.Bot(command_prefix="!", intents=intents)

# ===== BANNED WORDS CONFIGURATION =====
BANNED_WORDS = [
    "admin pidor",
    "admin gandon", 
    "admin pidoras",
    "admin ueban",
    "max khyesos",
    "max pidor",
    "admin uebok",
    "adminy pidory",
    "adminy konechye",
    "adminy uebany",
    "max gadon",
    "max gandon",
    "админ лох",
    "админ уебан",
    # Add more banned words as needed
]

# ===== HELPER FUNCTIONS =====
def contains_banned_words(content: str) -> bool:
    """
    Check if message content contains banned words.
    Uses word boundary matching for more accurate detection.
    """
    content_lower = content.lower()
    
    for word in BANNED_WORDS:
        # Use regex with word boundaries for more precise matching
        pattern = rf"{re.escape(word.lower())}"
        if re.search(pattern, content_lower, re.IGNORECASE):
            return True
    
    return False

def is_protected_user(member: discord.Member) -> bool:
    """
    Check if a user is protected from moderation actions.
    Protects admins and bot owners.
    """
    if not config.protect_admins:
        return False
    
    # Check if user is administrator
    if member.guild_permissions.administrator:
        return True
    
    # Check if user is bot owner (you can add your user ID here)
    bot_owner_id = os.getenv("BOT_OWNER_ID")
    if bot_owner_id and str(member.id) == bot_owner_id:
        return True
    
    return False

async def has_bot_permissions(guild: discord.Guild) -> bool:
    """
    Check if the bot has necessary permissions in a guild.
    """
    bot_member = guild.me
    
    required_permissions = [
        bot_member.guild_permissions.send_messages,
        bot_member.guild_permissions.embed_links,
        bot_member.guild_permissions.manage_messages,
        bot_member.guild_permissions.moderate_members,
        bot_member.guild_permissions.read_message_history
    ]
    
    return all(required_permissions)

def get_timeout_duration(warning_count: int) -> int:
    """
    Get timeout duration based on warning count.
    """
    if warning_count == 1:
        return 0  # No timeout for first warning
    elif warning_count == 2:
        return config.warning_timeout
    elif warning_count >= 3:
        return config.long_timeout
    else:
        return config.standard_timeout

async def apply_timeout_safely(member: discord.Member, duration: int, reason: str) -> bool:
    """
    Safely apply timeout to a member with error handling.
    Returns True if successful, False otherwise.
    """
    if duration <= 0:
        return True  # No timeout needed
    
    try:
        # Check if user is already timed out
        if member.is_timed_out():
            logger.info(f"User {member} is already timed out, skipping")
            return True
        
        # Apply timeout
        until_time = discord.utils.utcnow() + timedelta(seconds=duration)
        await member.timeout(until_time, reason=reason)
        
        logger.info(
            f"Timed out {member} ({member.id}) for {duration} seconds. "
            f"Reason: {reason}"
        )
        return True
        
    except discord.Forbidden:
        logger.error(f"No permission to timeout {member} in guild {member.guild}")
        return False
    except discord.HTTPException as e:
        logger.error(f"HTTP error when timing out {member}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error when timing out {member}: {e}")
        return False

# ===== MODERATION UI =====
class ModerationView(ui.View):
    """Interactive moderation interface with buttons"""
    
    def __init__(self, message: discord.Message, warning_count: int):
        super().__init__(timeout=None)
        self.message = message
        self.warning_count = warning_count

    @ui.button(label="Delete Message", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def delete_message(self, interaction: discord.Interaction, button: ui.Button):
        """Delete the flagged message"""
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message(
                "You don't have permission to use this button.", 
                ephemeral=True
            )
            return

        try:
            await self.message.delete()
            
            # Disable all buttons
            for child in self.children:
                child.disabled = True
            
            await interaction.response.edit_message(
                content=f"Message deleted by {interaction.user.mention}",
                view=self
            )
            
            logger.info(f"Message {self.message.id} deleted by {interaction.user}")
            
        except discord.NotFound:
            await interaction.response.send_message(
                "Message was already deleted.", 
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I don't have permission to delete that message.", 
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
            await interaction.response.send_message(
                "An error occurred while deleting the message.", 
                ephemeral=True
            )

    @ui.button(label="Ignore", style=discord.ButtonStyle.secondary, emoji="❌")
    async def ignore_warning(self, interaction: discord.Interaction, button: ui.Button):
        """Ignore the warning and keep the message"""
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message(
                "You don't have permission to use this button.", 
                ephemeral=True
            )
            return

        # Disable all buttons
        for child in self.children:
            child.disabled = True
        
        await interaction.response.edit_message(
            content=f"Warning ignored by {interaction.user.mention}",
            view=self
        )
        
        logger.info(f"Warning ignored by {interaction.user} for message {self.message.id}")

    @ui.button(label="Clear Warnings", style=discord.ButtonStyle.success, emoji="🧹")
    async def clear_user_warnings(self, interaction: discord.Interaction, button: ui.Button):
        """Clear all warnings for this user"""
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message(
                "You don't have permission to use this button.", 
                ephemeral=True
            )
            return

        try:
            warning_system.clear_warnings(str(self.message.author.id), str(self.message.guild.id))
            
            # Disable all buttons
            for child in self.children:
                child.disabled = True
            
            await interaction.response.edit_message(
                content=f"Warnings cleared for {self.message.author.mention} by {interaction.user.mention}",
                view=self
            )
            
            logger.info(f"Warnings cleared for {self.message.author} by {interaction.user}")
            
        except Exception as e:
            logger.error(f"Error clearing warnings: {e}")
            await interaction.response.send_message(
                "An error occurred while clearing warnings.", 
                ephemeral=True
            )

async def send_moderation_request(message: discord.Message, warning_count: int):
    """
    Send a detailed moderation request to the moderator channel.
    """
    try:
        # Get moderator channel
        moderator_channel = bot.get_channel(config.moderator_channel_id)
        if not moderator_channel:
            logger.error(f"Moderator channel {config.moderator_channel_id} not found")
            return
        
        # Create embed with moderation details
        embed = discord.Embed(
            title=" Moderation Request",
            color=discord.Color.orange(),
            description="A message has been flagged for inappropriate content."
        )
        
        # Add user information
        embed.add_field(name="User", value=message.author.mention, inline=True)
        embed.add_field(name="User ID", value=f"`{message.author.id}`", inline=True)
        embed.add_field(name="Warning Count", value=f"**{warning_count}**", inline=True)
        
        # Add message information
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        embed.add_field(name="Message ID", value=f"`{message.id}`", inline=True)
        
        # Add message content (truncated if too long)
        content_preview = message.content[:500] + ("..." if len(message.content) > 500 else "")
        embed.add_field(
            name="Message Content",
            value=f"```{content_preview}```",
            inline=False
        )
        
        # Add jump link
        embed.add_field(
            name="Jump to Message",
            value=f"[View Message]({message.jump_url})",
            inline=False
        )
        
        # Add warning level information
        timeout_duration = get_timeout_duration(warning_count)
        if timeout_duration > 0:
            embed.add_field(
                name="Action Taken",
                value=f"User timed out for {timeout_duration} seconds",
                inline=False
            )
        
        # Set footer and thumbnail
        embed.set_footer(text=f"Detected at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        embed.set_thumbnail(url=message.author.display_avatar.url)
        
        # Create and send view with buttons
        view = ModerationView(message, warning_count)
        await moderator_channel.send(embed=embed, view=view)
        
        logger.info(f"Moderation request sent for message {message.id} (Warning #{warning_count})")
        
    except discord.Forbidden:
        logger.error("No permission to send messages in moderator channel")
    except discord.HTTPException as e:
        logger.error(f"HTTP error sending moderation request: {e}")
    except Exception as e:
        logger.error(f"Unexpected error sending moderation request: {e}")

# ===== BOT EVENTS =====
@bot.event
async def on_ready():
    """Event handler for when bot is ready"""
    logger.info(f"Bot logged in as {bot.user} (ID: {bot.user.id})")
    logger.info(f"Connected to {len(bot.guilds)} guilds")
    
    # Validate bot permissions in each guild
    for guild in bot.guilds:
        if not await has_bot_permissions(guild):
            logger.warning(f"Bot lacks necessary permissions in guild: {guild.name}")
        else:
            logger.info(f"Bot has all required permissions in guild: {guild.name}")
    
    # Set bot presence
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="for inappropriate content"
        )
    )

@bot.event
async def on_message(message: discord.Message):
    """Main message handler for content moderation"""
    # Ignore bot messages
    if message.author.bot:
        return
    
    # Only process messages in guild text channels
    if not isinstance(message.channel, discord.TextChannel):
        return
    
    # Skip empty messages
    if not message.content.strip():
        return
    
    try:
        # Check if user is protected
        if is_protected_user(message.author):
            return
        
        # Skip if user is already timed out
        if message.author.is_timed_out():
            return
        
        # Check for banned words
        if contains_banned_words(message.content):
            # Get current warning count
            warning_count = warning_system.get_user_warnings(
                str(message.author.id), 
                str(message.guild.id)
            )
            
            # Add new warning
            warning_count = warning_system.add_warning(
                str(message.author.id),
                str(message.guild.id),
                str(message.author),
                "Banned words detected"
            )
            
            # Log the detection
            logger.info(
                f"Banned words detected from {message.author} ({message.author.id}) "
                f"in #{message.channel.name}. Warning count: {warning_count}. "
                f"Message: {message.content[:100]}..."
            )
            
            # Apply timeout based on warning count
            timeout_duration = get_timeout_duration(warning_count)
            if timeout_duration > 0:
                reason = f"Automatic moderation - Warning #{warning_count}"
                await apply_timeout_safely(message.author, timeout_duration, reason)
            
            # Send moderation request
            await send_moderation_request(message, warning_count)
    
    except Exception as e:
        logger.error(f"Error processing message {message.id}: {e}")
    
    # Process commands
    await bot.process_commands(message)

# ===== ADMIN COMMANDS =====
@bot.command()
@commands.has_permissions(administrator=True)
async def warnings(ctx, member: discord.Member = None):
    """Check warning count for a user"""
    if member is None:
        member = ctx.author
    
    warning_count = warning_system.get_user_warnings(str(member.id), str(ctx.guild.id))
    
    embed = discord.Embed(
        title=" Warning Information",
        color=discord.Color.blue()
    )
    
    embed.add_field(name="User", value=member.mention, inline=True)
    embed.add_field(name="Warning Count", value=f"**{warning_count}**", inline=True)
    
    if warning_count >= 2:
        embed.description = "This user is at maximum warning level!"
        embed.color = discord.Color.red()
    elif warning_count >= 1:
        embed.description = "This user has multiple warnings."
        embed.color = discord.Color.orange()
    else:
        embed.description = "This user has few or no warnings."
    
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def clearwarnings(ctx, member: discord.Member):
    """Clear all warnings for a user"""
    warning_system.clear_warnings(str(member.id), str(ctx.guild.id))
    
    embed = discord.Embed(
        title=" Warnings Cleared",
        description=f"All warnings have been cleared for {member.mention}",
        color=discord.Color.green()
    )
    
    await ctx.send(embed=embed)
    logger.info(f"Warnings cleared for {member} by {ctx.author}")

@bot.command()
@commands.has_permissions(administrator=True)
async def botstatus(ctx):
    """Display bot status and configuration"""
    embed = discord.Embed(
        title=" Bot Status",
        color=discord.Color.blue()
    )
    
    # Basic info
    embed.add_field(name="Bot User", value=bot.user.mention, inline=True)
    embed.add_field(name="Guilds", value=str(len(bot.guilds)), inline=True)
    embed.add_field(name="Uptime", value=f"<t:{int(bot.user.created_at.timestamp())}:R>", inline=True)
    
    # Configuration
    embed.add_field(
        name="Moderator Channel", 
        value=f"<#{config.moderator_channel_id}>", 
        inline=True
    )
    embed.add_field(name="Max Warnings", value=str(config.max_warnings), inline=True)
    embed.add_field(name="Admin Protection", value="Enabled" if config.protect_admins else "Disabled", inline=True)
    
    # Timeout durations
    embed.add_field(
        name="Timeout Durations",
        value=f"Warning: {config.warning_timeout}s\nStandard: {config.standard_timeout}s\nLong: {config.long_timeout}s",
        inline=False
    )
    
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def bannedwords(ctx):
    """Display current banned words list"""
    if not BANNED_WORDS:
        await ctx.send("No banned words are currently configured.")
        return
    
    embed = discord.Embed(
        title=" Banned Words",
        color=discord.Color.red()
    )
    
    # Split words into chunks to avoid embed limits
    words_per_field = 20
    for i in range(0, len(BANNED_WORDS), words_per_field):
        chunk = BANNED_WORDS[i:i + words_per_field]
        words_text = "\n".join(f" `{word}`" for word in chunk)
        embed.add_field(
            name=f"Words {i+1}-{min(i+words_per_field, len(BANNED_WORDS))}",
            value=words_text,
            inline=False
        )
    
    embed.set_footer(text=f"Total: {len(BANNED_WORDS)} banned words")
    await ctx.send(embed=embed)

# ===== ERROR HANDLING =====
@bot.event
async def on_command_error(ctx, error):
    """Global command error handler"""
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(" You need administrator permissions to use this command.")
    elif isinstance(error, commands.CommandNotFound):
        pass  # Ignore unknown commands
    else:
        logger.error(f"Command error: {error}")
        await ctx.send(f" An error occurred: {str(error)}")

# ===== START BOT =====
if __name__ == "__main__":
    try:
        logger.info("Starting Discord moderation bot...")
        bot.run(config.discord_token)
    except discord.LoginFailure:
        logger.error("Invalid Discord token. Please check your DISCORD_TOKEN environment variable.")
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
    finally:
        logger.info("Bot shutdown complete")
