import { GenericHandler, Message } from "../common/handler";
import { client } from "../common/llm";

const preProcessor = async (input: Message[]): Promise<[string]> => {
    const response = await client.messages.create({
        model: 'anthropic.claude-3-5-sonnet-20241022-v2:0',
        max_tokens: 256,
        messages: input.map(({ role, content }) => ({ role, content }))
    });
    switch (response.content[0].type) {
        case "text":
            return [response.content[0].text];
        default:
            throw new Error("Unexpected response type");
    }
};

const handle = (input: string): string => {
    return input;
};

const postProcessor = (output: string): Message[] => {
    return [{ role: 'assistant', content: output }];
};

export const dummyHandler = new GenericHandler<[string], string>(handle, preProcessor, postProcessor);
