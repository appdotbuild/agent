import { Pica } from "@picahq/ai";
import { env } from "../env";
import { z } from "zod";
import { client } from "../common/llm";

export const runAgentParamsSchema = z.object({
    query: z.string(),
});

export const pica = new Pica(env.PICA_SECRET_KEY!);


async function runAgentTask(message: string): Promise<string> {
    const systemPrompt = await pica.generateSystemPrompt();
    
    // Use our existing client from llm.ts
    const response = await client.messages.create({
        model: 'anthropic.claude-3-5-sonnet-20241022-v2:0',
        max_tokens: 2048,
        messages: [
            // Use a user message with the system prompt instead of a system role
            { role: 'user', content: `${systemPrompt}\n\nUser query: ${message}` }
        ],
        // Create a simplified tool definition that works with Bedrock
        tools: [{
            name: "pica",
            description: "A tool that helps with various tasks",
            input_schema: {
                type: "object",
                properties: {
                    action: { type: "string", description: "The action to perform" },
                    parameters: { type: "object", description: "Parameters for the action" }
                },
                required: ["action"]
            }
        }]
    });

    // Extract the resulting text from the response
    let result = '';
    if (typeof response.content === 'string') {
        result = response.content;
    } else if (Array.isArray(response.content)) {
        result = response.content
            .filter(block => block.type === 'text')
            .map((block: any) => block.text)
            .join('\n');
    }

    return result;
}

interface RunAgentResponse {
    query: string;
    result: string;
}
  
export type RunAgentParams = z.infer<typeof runAgentParamsSchema>;

export const handle_run_agent = async (options: RunAgentParams): Promise<RunAgentResponse> => {
    
};

export const can_handle = (): boolean => {
    return env.PICA_SECRET_KEY !== undefined;
};

//runAgentTask("Add a slot in my calendar for this week for and time when the weather is sunny in London")
//  .then((text) => {
//    console.log(text);
//  })
//  .catch(console.error);

