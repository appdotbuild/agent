import { handlers } from "./logic";
import { getRoute } from "./logic/router";
import { getHistory, putMessage } from "./common/crud";
import 'dotenv/config';
const { Context, Telegraf } = require('telegraf');
const { message } = require('telegraf/filters');

const mainHandler = async (ctx: typeof Context) => {
    console.log('mainHandler');
    await putMessage(ctx.from!.id.toString(), 'user', ctx.message.text!);
    const messages = await getHistory(ctx.from!.id.toString(), 3);
    const validMessages = messages.filter(msg => msg.role !== null && msg.content !== null) as { role: "user" | "assistant"; content: string }[];
    const route = await getRoute(validMessages);
    console.log('route', route);
    const handler = handlers[route];
    if (handler) {
        const result = await handler.execute(validMessages);
        if (result[0].role === "assistant") {
            ctx.reply(result[0].content);
            await putMessage(ctx.from!.id.toString(), 'assistant', result[0].content);
        }
    }
}

const bot = new Telegraf(process.env['TELEGRAM_BOT_TOKEN']);
bot.on(message('text'), mainHandler);
bot.launch();

// Enable graceful stop
process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
