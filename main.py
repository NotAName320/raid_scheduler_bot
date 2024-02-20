import asyncio
from datetime import date, datetime, time, timedelta
import json
import sys
import traceback

import aiosqlite
import discord
from discord.ext import commands


class DBBot(commands.Bot):
    def __init__(self, command_prefix, *, intents, **options):
        self.db: aiosqlite.Connection = options.pop('db')
        self.privileged_role: int = int(options.pop('privileged_role'))
        self.ping_role: int = int(options.pop('ping_role'))
        self.yes_emoji: str = options.pop('yes_emoji')
        self.maybe_emoji: str = options.pop('maybe_emoji')
        super().__init__(command_prefix, intents=intents, **options)


class RaidScheduler(commands.Cog):
    def __init__(self, bot: DBBot):
        self.bot = bot

    @commands.command(name='ping')
    async def ping(self, ctx: commands.Context):
        return await ctx.reply('Pong!')

    @commands.command(name='setprivilegedrole')
    @commands.has_permissions(manage_roles=True)
    async def set_privileged_role(self, ctx: commands.Context, role: discord.Role):
        self.bot.privileged_role = role.id
        with open('./settings.json') as jsonFile:
            settings = json.load(jsonFile)
            settings['privileged_role'] = str(role.id)
        with open('./settings.json', 'w') as jsonFile:
            json.dump(settings, jsonFile, indent=4)
        await ctx.reply(f'Role successfully changed to {role.name}!')

    @commands.command(name='setpingrole')
    @commands.has_permissions(manage_roles=True)
    async def set_ping_role(self, ctx: commands.Context, role: discord.Role):
        self.bot.ping_role = role.id
        with open('./settings.json') as jsonFile:
            settings = json.load(jsonFile)
            settings['ping_role'] = str(role.id)
        with open('./settings.json', 'w') as jsonFile:
            json.dump(settings, jsonFile, indent=4)
        await ctx.reply(f'Role successfully changed to {role.name}!')

    @commands.command(name='setyesemoji')
    @commands.has_permissions(manage_emojis=True)
    async def set_yes_emoji(self, ctx: commands.Context, emoji: int | str):
        pass

    @commands.command(name='setmaybeemoji')
    @commands.has_permissions(manage_emojis=True)
    async def set_maybe_emoji(self, ctx: commands.Context, emoji: int | str):
        pass

    @commands.command(name='schedule')
    async def schedule(self, ctx: commands.Context, raid_date: str, update_type: str, puppet_count: int, *,
                       extra_info: str = ''):
        raid_date, update_type = raid_date.lower(), update_type.lower()
        role = ctx.guild.get_role(self.bot.privileged_role)
        if not role:
            return await ctx.reply('The server\'s privileged role is misconfigured. Someone should probably fix that.')
        if role not in ctx.author.roles:
            return await ctx.reply('You aren not allowed to schedule tag raids. You may be missing a mask.')
        try:
            date_db = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'].index(raid_date)
        except ValueError:
            return await ctx.reply('Please write your date as a full day of the week.')
        try:
            update_type_db = ['major', 'minor'].index(update_type)
        except ValueError:
            return await ctx.reply('Please specify major or minor update.')
        if not 1 <= puppet_count <= 200:
            return await ctx.reply('Please specify a reasonable puppet amount.')

        async with self.bot.db.execute("""
            select discord_message
            from raids
            where date = ?
            and update_type = ?
        """, (date_db, update_type_db)) as cursor:
            if raid_message_id := await cursor.fetchone():
                try:
                    message = await ctx.channel.fetch_message(raid_message_id[0])
                except discord.NotFound:
                    await self.bot.db.execute("""
                        delete from raids
                        where discord_message = ?
                    """, (raid_message_id[0],))
                else:
                    return await message.reply('A raid already exists at this time.', mention_author=False)

        ping_role = getattr(ctx.guild.get_role(self.bot.ping_role), 'mention', '*Ping role not found*')

        if extra_info:
            extra_info = f'**Additional notes:** {extra_info}\n'

        yes_emoji = discord.utils.get(ctx.guild.emojis, id=self.bot.yes_emoji) or self.bot.yes_emoji
        maybe_emoji = discord.utils.get(ctx.guild.emojis, id=self.bot.maybe_emoji) or self.bot.maybe_emoji

        next_update = date.today()
        while next_update.weekday() != date_db:
            next_update += timedelta(days=1)
        update_time = time(23, 59) if update_type == 'major' else time(11, 59)
        next_update = datetime.combine(next_update, update_time)
        if next_update < datetime.now():
            next_update += timedelta(days=7)

        message = await ctx.channel.send(f"{ping_role}\n"
                                         f"**When:** {raid_date.capitalize()} {update_type.capitalize()} "
                                         f"(<t:{int(next_update.timestamp())}:R>)\n"
                                         f"**Number of puppets**: {puppet_count}\n"
                                         f"{extra_info}\n"
                                         f"React with {yes_emoji} for coming, or {maybe_emoji} for maybe")
        await message.add_reaction(yes_emoji)
        await message.add_reaction(maybe_emoji)

        await self.bot.db.execute("""
            insert into raids values(
                ?, ?, ?
            )
        """, (date_db, update_type_db, message.id))
        await self.bot.db.commit()


async def login():
    async with aiosqlite.connect('./raid_scheduler_bot.sqlite') as db:
        await db.execute("""
            create table if not exists raids
            (
                date            integer not null,
                update_type     integer not null,
                discord_message integer not null
            );
        """)
        await db.commit()

        try:
            with open('./settings.json') as jsonFile:
                settings = json.load(jsonFile)
                token = settings.pop('token')
        except (FileNotFoundError, KeyError) as e:
            default_json = {
                        'token': '',
                        'command_prefix': '!',
                        'privileged_role': '123123123',
                        'ping_role': '123123123',
                        'yes_emoji': '🟢',
                        'maybe_emoji': '🟡'
            }
            if isinstance(e, FileNotFoundError):
                with open('./settings.json', 'x') as jsonFile:
                    json.dump(default_json, jsonFile, indent=4)
            else:
                # way too complicated settings correction system
                with open('./settings.json') as jsonFile:
                    settings = json.load(jsonFile)
                    for key, value in default_json.items():
                        if key not in settings:
                            settings[key] = value
                with open('./settings.json', 'w') as jsonFile:
                    json.dump(settings, jsonFile, indent=4)
            print('Please configure your settings file.', file=sys.stderr)
            exit(1)

        intents = discord.Intents.default()
        intents.message_content = True
        bot = DBBot(**settings, intents=intents, help_command=commands.MinimalHelpCommand(), db=db)
        await bot.add_cog(RaidScheduler(bot))

        @bot.event
        async def on_ready():
            # Prints login success and bot info to console
            print('Logged in as')
            print(bot.user)
            print(bot.user.id)

        @bot.event
        async def on_command_error(ctx, exception):
            await ctx.reply(exception)
            traceback.print_exception(exception)

        try:
            await bot.start(token=token)
        except KeyboardInterrupt:
            await bot.close()

if __name__ == '__main__':
    asyncio.run(login())
