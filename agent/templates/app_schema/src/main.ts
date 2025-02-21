import { z } from 'zod';
import { type JSONSchema7 } from "json-schema";
import { zodToJsonSchema } from "zod-to-json-schema";
import { getHistory, putMessage } from "./common/crud";
import { client, type MessageParam, type ContentBlock, type ToolUseBlock, type ToolResultBlock } from "./common/llm";
import 'dotenv/config';
const { Context, Telegraf } = require('telegraf');
const { message } = require('telegraf/filters');
import { handle as greetHandler, greetUserParamsSchema } from './handlers/dummy_handler';

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
        handler: greetHandler,
        inputSchema: greetUserParamsSchema,
    }
].map(tool => ({
    ...tool,
    toolInput: makeSchema(tool.inputSchema),
}));


async function callClaude(ctx: typeof Context, prompt: string | MessageParam[], messages: MessageParam[]) {
    if (Array.isArray(prompt)) {
        messages.push(...prompt);
    } else {
        messages.push({
            role: "user",
            content: prompt,
        });
    }


    return client.messages.create({
        model: 'anthropic.claude-3-5-sonnet-20241022-v2:0',
        max_tokens: 2048,
        messages: messages.map(message => message as MessageParam),
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
    })
        .then(async (response) => {
            // avoids pushing empty message arrays
            if (response.content.length) {
                messages.push({ role: "assistant", content: response.content });
            }
            return response;
        });
}
async function callTool(toolBlock: ToolUseBlock) {
    const { name, id, input } = toolBlock;

    const tool = handler_tools.find((tool) => tool.name === name);
    if (tool) {
        try {
            const toolInput = tool.inputSchema.parse(input);
            const toolOutput = await tool.handler(toolInput);
            return {
                role: "user",
                content: [
                    {
                        type: "tool_result",
                        tool_use_id: id,
                        content: toolOutput,
                    },
                ],
            } as MessageParam;
        } catch (error) {
            return {
                role: "user",
                content: [
                    {
                        type: "tool_result",
                        tool_use_id: id,
                        content: `Invalid input ${error}`,
                    },
                ],
            } as MessageParam;
        }
    } else {
        return {
            role: "user",
            content: [
                {
                    type: "tool_result",
                    tool_use_id: id,
                    content: `Tool ${name} does not exist`,
                },
            ],
        } as MessageParam;
    }
}
async function processResponse(ctx: typeof Context, response: Awaited<ReturnType<typeof callClaude>>, messages: MessageParam[]): Promise<string> {
    const toolUseBlocks = response.content.filter<ToolUseBlock>(
        (content) => content.type === "tool_use",
    );

    if (toolUseBlocks.length) {
        const allToolResultPromises = toolUseBlocks.map(async (toolBlock) => {
            return await callTool(toolBlock);
        });
        const allToolResults = await Promise.all(allToolResultPromises);

        return await callClaude(ctx, allToolResults, messages) //
            .then((response) => {
                return processResponse(ctx, response, messages);
            });
    } else {
        const textOutputs = response.content
            .map((content) => (content.type === "text" ? content.text : null))
            .filter(Boolean);
        return textOutputs.join("\n");
    }
}


async function main(ctx: typeof Context) {
    const WINDOW_SIZE = 100;
    const messages = await getHistory(ctx.from!.id.toString(), WINDOW_SIZE);
    let initialMessageCount = messages.length;
    let sessionMessages: MessageParam[] = [];



    while (true) {
        const userPrompt = ctx.message.text;
        const response = await callClaude(ctx, userPrompt, messages)
            .then(async (response) => {
                return processResponse(ctx, response, messages);
            });

        sessionMessages = messages.slice(initialMessageCount);

        if (response) {
            await ctx.reply(response);
        } else {
            const toolResultMesssages = sessionMessages.filter((message) =>
                Array.isArray(message.content) &&
                message.content.some(content => content.type === "tool_result")
            )

            // matches tool_use and tool_result messages
            const formattedResults = toolResultMesssages.map(toolResultMessage => {
                const toolResultContent = toolResultMessage.content[0];
                const toolUseMessage = sessionMessages.find(msg => Array.isArray(msg.content) && msg.content.some(content => content.type === "tool_use" && content.id === (toolResultContent as ToolResultBlock).tool_use_id))
                const toolUseMessageContent = Array.isArray(toolUseMessage?.content) ? toolUseMessage?.content.find(content => content.type === "tool_use") : toolUseMessage?.content;
                return `The tool '${(toolUseMessageContent as ToolUseBlock)?.name || "unknown"}' responded with: "${(toolResultContent as ToolResultBlock).content}"`;
            })

            console.log('messages', messages);
            console.log('sessionMessages', sessionMessages);
            await ctx.reply(formattedResults.join('\n') || 'No tool results');
        }
        break;
    }

    // save session messages    
    await Promise.all(sessionMessages.map(message => putMessage(ctx.from!.id.toString(), message.role, message.content)));
}

const bot = new Telegraf(process.env['TELEGRAM_BOT_TOKEN']);
bot.on(message('text'), main);
bot.launch();

// Enable graceful stop
process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
