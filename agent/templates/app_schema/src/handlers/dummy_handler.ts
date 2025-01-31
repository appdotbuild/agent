import { GenericHandler, Message } from "../common/handler";
import { client } from "../common/llm";
const nunjucks = require('nunjucks');

interface Options {
    name: string;
    age: number;
}

const preProcessorPrompt = `
Examine conversation between user and assistant and extract structured arguments for a function.

<instructions>
The recordUser function requires two arguments:
1. name: String identifying the exercise (case-insensitive)
2. age: number

Rules for processing input:
- All arguments are mandatory
</instructions>

Examples:

Input:
Hi I'm Alex and I'm 25 years old
Output:
{"name": "Alex", "age": 25}

Input:
My name is John and I'm 30 years old
Output:
{"name": "John", "age": 30}

Conversation:
{% for message in messages %}
<role name="{{message.role}}">{{message.content}}</role>
{% endfor %}
`;

const postProcessorPrompt = `
Generate response to user using output from recordUser function and conversation.

{{output}}

Conversation:
{% for message in messages %}
<role name="{{message.role}}">{{message.content}}</role>
{% endfor %}
`

const preProcessor = async (input: Message[]): Promise<Options> => {
    const userPrompt = nunjucks.renderString(preProcessorPrompt, { messages: input });
    const response = await client.messages.create({
        model: 'anthropic.claude-3-5-sonnet-20241022-v2:0',
        max_tokens: 2048,
        messages: [{ role: 'user', content: userPrompt }, { role: 'assistant', content: '{'}]
    });
    switch (response.content[0].type) {
        case "text":
            return JSON.parse('{' + response.content[0].text);
        default:
            throw new Error("Unexpected response type");
    }
};

const handle = (options: Options): string => {
    return options.name + ' is ' + options.age + ' years old';
};

const postProcessor = async (output: string, input: Message[]): Promise<Message[]> => {
    const assistantPrompt = nunjucks.renderString(postProcessorPrompt, { output, messages: input });
    const response = await client.messages.create({
        model: 'anthropic.claude-3-5-sonnet-20241022-v2:0',
        max_tokens: 2048,
        messages: [{ role: 'user', content: assistantPrompt }]
    });
    switch (response.content[0].type) {
        case "text":
            return [{ role: 'assistant', content: response.content[0].text }];
        default:
            throw new Error("Unexpected response type");
    }
};

export const dummyHandler = new GenericHandler<Options, string>(handle, preProcessor, postProcessor);
