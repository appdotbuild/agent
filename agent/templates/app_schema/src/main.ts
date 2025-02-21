import { z } from 'zod';
import { type JSONSchema7 } from "json-schema";
import { zodToJsonSchema } from "zod-to-json-schema";
import { getHistory, putMessageBatch } from "./common/crud";
import { client, type MessageParam, type ToolUseBlock, type ToolResultBlock } from "./common/llm";
import 'dotenv/config';
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

async function main(ctx: typeof Context) {
    const WINDOW_SIZE = 100;
    const THREAD_LIMIT = 10;
    const messages = await getHistory(ctx.from!.id.toString(), WINDOW_SIZE);

    let thread: MessageParam[] = [{ role: "user", content: ctx.message.text }];
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

    await putMessageBatch(thread.map(message => ({ user_id: ctx.from!.id.toString(), ...message })));

    let toolCalls: ToolUseBlock[] = [];
    let toolResults: ToolResultBlock[] = [];
    let textContent: string[] = [];

    thread.forEach((message) => {
        if (typeof message.content === "string") {
            if (message.role === "assistant") {
                textContent.push(message.content);
            }
        } else {
            toolCalls.push(...message.content.filter((content) => content.type === "tool_use"));
            toolResults.push(...message.content.filter((content) => content.type === "tool_result"));
            if (message.role === "assistant") {
                textContent.push(...message.content.filter((content) => content.type === "text").map((content) => content.text));
            }
        }
    })

    const toolLines = toolResults.map((toolResult) => {
        const toolCall = toolCalls.find((toolCall) => toolCall.id === toolResult.tool_use_id);
        return `Handler '${toolCall!.name}' responded with: "${toolResult.content}"`;
    });

    const userReply = textContent.join("\n") + (toolLines.length ? "\n" + toolLines.join("\n") : "");
    await ctx.reply(userReply || 'No response');
}

const bot = new Telegraf(process.env['TELEGRAM_BOT_TOKEN']);
bot.on(message('text'), main);
bot.launch();

// Enable graceful stop
process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
