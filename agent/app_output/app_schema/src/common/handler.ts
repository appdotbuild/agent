interface Message {
    role: 'user' | 'assistant';
    content: string;
};

interface Handler<Args extends any[], Output> {
    preProcessor: (input: Message[]) => Args | Promise<Args>;
    handle: (...args: Args) => Output | Promise<Output>;
    postProcessor: (output: Output) => Message[] | Promise<Message[]>;
}

class GenericHandler<Args extends any[], Output> implements Handler<Args, Output> {
    constructor(
        public handle: (...args: Args) => Output | Promise<Output>,
        public preProcessor: (input: Message[]) => Args | Promise<Args>,
        public postProcessor: (output: Output) => Message[] | Promise<Message[]>
    ) {}

    async execute(input: Message[]): Promise<Message[] | Output> {
        const args = await this.preProcessor(input);
        const result = await this.handle(...args);
        return this.postProcessor ? await this.postProcessor(result) : result;
    }
}

export {
    Message,
    Handler,
    GenericHandler
};