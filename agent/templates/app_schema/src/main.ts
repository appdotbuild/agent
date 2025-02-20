import { z } from 'zod';
import { type JSONSchema7 } from "json-schema";
import { zodToJsonSchema } from "zod-to-json-schema";
import { getHistory, putMessage } from "./common/crud";
import { client, type MessageParam, type ContentBlock } from "./common/llm";
import 'dotenv/config';
const { Context, Telegraf } = require('telegraf');
const { message } = require('telegraf/filters');
import { greetUserParamsSchema } from './common/schema';


const makeSchema = (schema: z.ZodObject<any>) => {
    const jsonSchema = zodToJsonSchema(schema, { target: 'jsonSchema7', $refStrategy: 'root' }) as JSONSchema7;
    return {
        properties: jsonSchema.properties,
        required: jsonSchema.required,
        definitions: jsonSchema.definitions,
    }
}


const handler_tools = [
    {
        name: "greeter",
        description: "create a greeting message",
        handler: require('./handlers/dummy_handler').handle,
        input_schema: makeSchema(greetUserParamsSchema),
        parse: (input: any) => greetUserParamsSchema.parse(input),
    }
]


const mainHandler = async (ctx: typeof Context) => {
    const WINDOW_SIZE = 100;
    await putMessage(ctx.from!.id.toString(), 'user', ctx.message.text!);
    let messages = await getHistory(ctx.from!.id.toString(), WINDOW_SIZE);
    while (true) {
        const response = await client.messages.create({
            model: 'anthropic.claude-3-5-sonnet-20241022-v2:0',
            max_tokens: 2048,
            messages: messages.map(message => message as MessageParam),
            tools: handler_tools.map(tool => ({
                name: tool.name,
                description: tool.description,
                input_schema: {
                    type: "object",
                    properties: tool.input_schema.properties,
                    required: tool.input_schema.required,
                    definitions: tool.input_schema.definitions,
                }
            }))
        });
        messages.push({role: "assistant", content: response.content})
        let appendMessages: Array<MessageParam> = [];
        let toolContent: Array<ContentBlock> = [];
        for (const block of response.content) {
            switch (block.type) {
                case "tool_use":
                    const tool = handler_tools.find(tool => tool.name === block.name);
                    if (!tool) {
                        toolContent.push({type: "tool_result", tool_use_id: block.id, content: "tool not found"});
                    } else {
                        try {
                            const input = tool.parse(block.input);
                            const output = await tool.handler(input);
                            toolContent.push({type: "tool_result", tool_use_id: block.id, content: output});
                        } catch (error) {
                            toolContent.push({type: "tool_result", tool_use_id: block.id, content: String(error)});
                        }
                    }
                    break;
                case "text":
                    
                    break;
            }
        }

    }
}

const bot = new Telegraf(process.env['TELEGRAM_BOT_TOKEN']);
bot.on(message('text'), mainHandler);
bot.launch();

// Enable graceful stop
process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
