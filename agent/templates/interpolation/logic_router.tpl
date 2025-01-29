import { client } from "../common/llm";
import { Message } from "../common/handler";
const nunjucks = require("nunjucks");

const router_prompt: string = `{% raw %}
Based on converstation between user and assistant determine which function should
handle current message based on function description and message content.
{% for function in functions%}
<function name="{{function.name}}">
    <description>{{function.description}}</description>
    {% for example in function.examples %}
    <example>{{example}}</example>{% endfor %}
</function>
{% endfor %}
Reply with the name of the function only.

Conversation:
{% for message in messages %}
<role name="{{message.role}}">{{message.content}}</role>
{% endfor %}{% endraw %}
`;

export interface FunctionDef {
    name: string;
    description: string;
}

const functions: FunctionDef[] = [
    {% for function in functions %}{
        name: {{ function.name }},
        description: {{ function.description }},
        examples: [{% for example in function.examples %}
            "{{ example }}",{% endfor %}
        ]
    }{% endfor %}
]

export const getRoute = async (messages: Message[]): Promise<string> => {
    const request = nunjucks.renderString(router_prompt, { messages, functions });
    const response = await client.messages.create({
        model: 'anthropic.claude-3-5-sonnet-20241022-v2:0',
        max_tokens: 256,
        messages: [{ role: "user", content: request }]
    });
    switch (response.content[0].type) {
        case "text":
            return response.content[0].text;
        default:
            throw new Error("Unexpected response type");
    }
};
