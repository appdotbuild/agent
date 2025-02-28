import { Telegraf } from 'telegraf';
import { message } from 'telegraf/filters';
import { env } from './env';
import { handleChat } from './common/chat';

export function launchTelegram() {
  if (!env.TELEGRAM_BOT_TOKEN) {
    throw new Error('TELEGRAM_BOT_TOKEN is not set');
  }

  const bot = new Telegraf(env.TELEGRAM_BOT_TOKEN);
  bot.on(message('text'), async (ctx) => {
    const userReply = await handleChat({
      user_id: ctx.from.id.toString(),
      message: ctx.message.text,
    });
    await ctx.reply(userReply);
  });

  bot.launch();
  process.once('SIGINT', () => bot.stop('SIGINT'));
  process.once('SIGTERM', () => bot.stop('SIGTERM'));
}
