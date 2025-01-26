import { GenericHandler, Message } from "../common/handler";
import { client } from "../common/llm";

const preProcessor = async (input: Message[]): Promise<[string]> => {
    return [''];
};

const handle = (input: string): string => {
    return '';
};

const postProcessor = (output: string): Message[] => {
    const content = 'handler {{handler.name}} executed';
    return [{ role: 'assistant', content: content }];
};

export const {{handler.name}} = new GenericHandler<[string], string>(handle, preProcessor, postProcessor);
