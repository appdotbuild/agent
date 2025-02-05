import { GenericHandler, type Message } from "../common/handler";
import { client } from "../common/llm";
const nunjucks = require('nunjucks');
import * as TJS from "typescript-json-schema";

interface Options {
    name: string;
    age: number;
}

const handle = (options: Options): string => {
    return options.name + ' is ' + options.age + ' years old';
};

const preProcessorPrompt = `
Conversation:
{% for message in messages %}
<role name="{{message.role}}">{{message.content}}</role>
{% endfor %}
`;

const getJSONSchema = () => {
    const settings: TJS.PartialArgs = {
        required: true,
    };
    
    const compilerOptions: TJS.CompilerOptions = {
        strictNullChecks: true,
        allowJs: true,
        allowImportingTsExtensions: true,
        noEmit: true,
        strict: true,
        skipLibCheck: true,
    };
    
    const program = TJS.getProgramFromFiles(
        [__filename],
        compilerOptions,
    );
    return TJS.generateSchema(program, "Options", settings)
}

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
    const schema = getJSONSchema()!;
    const response = await client.messages.create({
        model: 'anthropic.claude-3-5-sonnet-20241022-v2:0',
        max_tokens: 2048,
        messages: [{ role: 'user', content: userPrompt }],
        tools: [
            {
                name: "handle",
                description: "Execute handler.",
                input_schema: {
                    type: "object",
                    properties: schema.properties,
                    required: schema.required,
                },
            }
        ],
        tool_choice: {type: "tool", name: "handle"},
    });
    switch (response.content[0].type) {
        case "tool_use":
            return response.content[0].input as Options;
        default:
            throw new Error("Unexpected response type");
    }
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
