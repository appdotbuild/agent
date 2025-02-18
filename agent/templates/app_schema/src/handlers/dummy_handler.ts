import { GenericHandler, type Message } from "../common/handler";
import { client } from "../common/llm";
const nunjucks = require('nunjucks');
import { z } from "zod";
import { type JSONSchema7 } from "json-schema";
import { zodToJsonSchema } from "zod-to-json-schema";

const greetUserParamsSchema = z.object({
    name: z.string(),
    age: z.number(),
    today: z.coerce.date(),
});

type GreetUserParams = z.infer<typeof greetUserParamsSchema>;

const handle = (options: GreetUserParams): string => {
    console.log(options);
    return options.name + ' is ' + options.age + ' years old';
};

const preProcessorPrompt = `
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

const preProcessor = async (input: Message[]): Promise<GreetUserParams> => {
    const userPrompt = nunjucks.renderString(preProcessorPrompt, { messages: input });
    const schema = zodToJsonSchema(greetUserParamsSchema, { target: 'jsonSchema7', $refStrategy: 'root'}) as JSONSchema7;
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
            return greetUserParamsSchema.parse(response.content[0].input);
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

export const dummyHandler = new GenericHandler(handle, preProcessor, postProcessor);
