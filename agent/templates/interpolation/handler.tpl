import { type Message, GenericHandler } from "../common/handler";
import { client } from "../common/llm";
const nunjucks = require("nunjucks");
import * as TJS from "typescript-json-schema";

{{handler}}

type HandleOptArg = Parameters<typeof handle>[0];

const preProcessorPrompt = `
Conversation:{% raw %}
{% for message in messages %}
<role name="{{message.role}}">{{message.content}}</role>
{% endfor %}{% endraw %}
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
    return TJS.generateSchema(program, "HandleOptArg", settings)
}

const preProcessor = async (input: Message[]): Promise<HandleOptArg> => {
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
                    definitions: schema.definitions,
                },
            }
        ],
        tool_choice: {type: "tool", name: "handle"},
    });
    switch (response.content[0].type) {
        case "tool_use":
            return response.content[0].input as HandleOptArg;
        default:
            throw new Error("Unexpected response type");
    }
};

const postProcessorPrompt = `
Generate response to user using output from {{handler_name}} function and conversation.

{% raw %}{{output}}{% endraw %}

Conversation:{% raw %}
{% for message in messages %}
<role name="{{message.role}}">{{message.content}}</role>
{% endfor %}{% endraw %}
`

const postProcessor = async (output: object, input: Message[]): Promise<Message[]> => {
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

export const {{handler_name}} = new GenericHandler(handle, preProcessor, postProcessor);
