import { z } from 'zod';
import { type JSONSchema7 } from "json-schema";
import { zodToJsonSchema } from "zod-to-json-schema";
import { getHistory, putMessageBatch } from "./common/crud";
import { client, type MessageParam, type ToolUseBlock, type ToolResultBlock } from "./common/llm";
import 'dotenv/config';
import Fastify from 'fastify';
const { Context, Telegraf } = require('telegraf');
const { message } = require('telegraf/filters');
import { handlers } from './tools';

const makeSchema = (schema: z.ZodObject<any>) => {
    const jsonSchema = zodToJsonSchema(schema, { target: 'jsonSchema7', $refStrategy: 'root' }) as JSONSchema7;
    return {
        properties: jsonSchema.properties,
        required: jsonSchema.required,
        definitions: jsonSchema.definitions,
    }
}

const handler_tools = handlers.map(tool => ({
    ...tool,
    toolInput: makeSchema(tool.inputSchema),
}));


async function callClaude(prompt: string | MessageParam[]) {
    const messages: MessageParam[] = Array.isArray(prompt) ? prompt : [{ role: "user", content: prompt }];
    return await client.messages.create({
        model: 'anthropic.claude-3-5-sonnet-20241022-v2:0',
        max_tokens: 2048,
        messages: messages,
        tools: handler_tools.map(tool => ({
            name: tool.name,
            description: tool.description,
            input_schema: {
                type: "object",
                properties: tool.toolInput.properties,
                required: tool.toolInput.required,
                definitions: tool.toolInput.definitions,
            }
        }))
    });
}

async function callTool(toolBlock: ToolUseBlock) {
    const { name, id, input } = toolBlock;
    const tool = handler_tools.find((tool) => tool.name === name);
    if (tool) {
        try {
            const content = await tool.handler(tool.inputSchema.parse(input));
            return {
                type: "tool_result",
                tool_use_id: id,
                content: JSON.stringify(content),
            } as ToolResultBlock;
        } catch (error) {
            return {
                type: "tool_result",
                tool_use_id: id,
                content: `${error}`,
                is_error: true,
            } as ToolResultBlock;
        }
    } else {
        return {
            type: "tool_result",
            tool_use_id: id,
            content: `Tool ${name} does not exist`,
        } as ToolResultBlock;
    }
}

async function handle_chat(user_id: string, message: string) {
    const THREAD_LIMIT = 10;
    const WINDOW_SIZE = 100;
    const LOG_RESPONSE = process.env['LOG_RESPONSE'] ?? false;

    const messages = await getHistory(user_id, WINDOW_SIZE);
    let thread: MessageParam[] = [{ role: "user", content: message }];
    while (thread.length < THREAD_LIMIT) {
        const response = await callClaude([...messages, ...thread]);

        if (!response.content.length) {
            break;
        }

        thread.push({ role: response.role, content: response.content });

        const toolUseBlocks = response.content.filter<ToolUseBlock>(
            (content) => content.type === "tool_use",
        );
        const allToolResultPromises = toolUseBlocks.map(async (toolBlock) => {
            return await callTool(toolBlock);
        });
        const allToolResults = await Promise.all(allToolResultPromises);

        if (allToolResults.length) {
            thread.push({ role: "user", content: allToolResults });
            continue;
        }

        break;
    }

    await putMessageBatch(thread.map(message => ({ user_id: user_id, ...message })));

    let toolCalls: ToolUseBlock[] = [];
    let toolResults: ToolResultBlock[] = [];
    let textContent: string[] = [];

    thread.forEach(({ role, content }) => {
        if (role === "assistant" && typeof content === "string") {
            textContent.push(content);
        } else if (Array.isArray(content)) {
            content.forEach((block) => {
                if (block.type === "tool_use") {
                    toolCalls.push(block);
                } else if (block.type === "tool_result") {
                    toolResults.push(block);
                } else if (block.type === "text" && role === "assistant") {
                    textContent.push(block.text);
                }
            })
        }
    });

    const toolLines = toolResults.map((toolResult) => {
        const toolCall = toolCalls.find((toolCall) => toolCall.id === toolResult.tool_use_id);
        return `Handler '${toolCall!.name}' responded with: "${toolResult.content}"`;
    });

    let userReply = textContent.join("\n");
    if (LOG_RESPONSE && toolLines.length) {
        userReply += "\n" + toolLines.join("\n");
    }
    return userReply || 'No response';
}

function run_telegram() {
    const bot = new Telegraf(process.env['TELEGRAM_BOT_TOKEN']!);
    bot.on(message('text'), async (ctx: typeof Context) => {
        const userReply = await handle_chat(ctx.from!.id.toString(), ctx.message.text);
        await ctx.reply(userReply);
    });
    bot.launch();
    process.once('SIGINT', () => bot.stop('SIGINT'));
    process.once('SIGTERM', () => bot.stop('SIGTERM'));
}

function run_server() {
    const port = parseInt(process.env['PORT'] ?? '3000', 10);
    const reqTypeSchema = z.object({
        user_id: z.string(),
        message: z.string(),
    });

    const app = Fastify({
        logger: true
    });

    app.post('/chat', async (req, res) => {
        const data = reqTypeSchema.parse(req.body);
        const userReply = await handle_chat(data.user_id, data.message);
        return { reply: userReply };
    });

    for (const handler of handlers) {
        app.post(`/handler/${handler.name}`, async (req, res) => {
            const data = handler.inputSchema.parse(req.body);
            const result = await handler.handler(data);
            return { response: result };
        });
    }

    app.listen({ port, host: '0.0.0.0' }, function (err, address) {
        if (err) {
            app.log.error(err)
            process.exit(1)
        }
    })
}

switch (process.env['RUN_MODE'] ?? 'telegram') {
    case 'server':
        run_server();
        break;
    case 'telegram':
        run_telegram();
        break;
    default:
        throw new Error('Invalid RUN_MODE');
}
