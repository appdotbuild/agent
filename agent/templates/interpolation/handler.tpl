import { Message, GenericHandler } from "../common/handler";
import { client } from "../common/llm";
{{handler}}


const preProcessorPrompt = `
Examine conversation between user and assistant and extract structured arguments for a function.

<instructions>
{{instructions}}
</instructions>

Examples:

{% for example in examples %}
Input:
{{ example[0] }}
Output:
{{ example[1] }}
{% endfor %}

Conversation:{% raw %}
{% for message in messages %}
<role name="{{message.role}}">{{message.content}}</role>
{% endfor %}{% endraw %}
`;

const preProcessor = async (input: Message[]): Promise<[string]> => {
    const response = await client.messages.create({
        model: 'anthropic.claude-3-5-sonnet-20241022-v2:0',
        max_tokens: 2048,
        messages: input.map(({ role, content }) => ({ role, content }))
    });
    switch (response.content[0].type) {
        case "text":
            return [response.content[0].text];
        default:
            throw new Error("Unexpected response type");
    }
};

export const {{handler_name}} = new GenericHandler<[string], string>(handle, preProcessor, postProcessor);
