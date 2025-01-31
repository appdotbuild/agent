interface Message {
    role: 'user' | 'assistant';
    content: string;
};

interface Handler<Options, Output> {
    preProcessor: (input: Message[]) => Options | Promise<Options>;
    handle: (options: Options) => Output | Promise<Output>;
    postProcessor: (output: Output, input: Message[]) => Message[] | Promise<Message[]>;
}

class GenericHandler<Options, Output> implements Handler<Options, Output> {
    constructor(
        public handle: (options: Options) => Output | Promise<Output>,
        public preProcessor: (input: Message[]) => Options | Promise<Options>,
        public postProcessor: (output: Output, input: Message[]) => Message[] | Promise<Message[]>
    ) {}

    async execute(input: Message[]): Promise<Message[] | Output> {
        const options = await this.preProcessor(input);
        const result = await this.handle(options);
        return this.postProcessor ? await this.postProcessor(result, input) : result;
    }
}

export {
    Message,
    Handler,
    GenericHandler
};