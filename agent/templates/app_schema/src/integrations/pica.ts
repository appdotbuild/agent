import { anthropic } from "@ai-sdk/anthropic";
import { generateText } from "ai";
import { Pica } from "@picahq/ai";
import { env } from "../env";
import { z } from "zod";

export const runAgentParamsSchema = z.object({
    query: z.string(),
  });

// Lazy initialization - only create when needed
let picaInstance: Pica | null = null;

const getPica = (): Pica => {
    if (!picaInstance && env.PICA_SECRET_KEY) {
        try {
            picaInstance = new Pica(env.PICA_SECRET_KEY);
        } catch (error) {
            throw new Error("Failed to initialize Pica client");
        }
    }
    
    if (!picaInstance) {
        throw new Error("Pica client not initialized: Missing API key");
    }
    
    return picaInstance;
};

async function runAgentTask(message: string): Promise<string> {
    const pica = getPica();
    const system = await pica.generateSystemPrompt();

    const { text } = await generateText({
        model: anthropic("claude-3-5-sonnet-20240620"),
        system,
        prompt: message,
        tools: { ...pica.oneTool },
        maxSteps: 10,
    });

    return text;
}

interface RunAgentResponse {
    query: string;
    result: string;
  }
  
export type RunAgentParams = z.infer<typeof runAgentParamsSchema>;

export const handle_run_agent = async (options: RunAgentParams): Promise<RunAgentResponse> => {
    try {
        const result = await runAgentTask(options.query);
        return {
            query: options.query,
            result: result,
        };
    } catch (error) {
        console.error("Error running Pica agent:", error);
        return {
            query: options.query,
            result: `Error: Failed to run Pica agent. ${error instanceof Error ? error.message : 'Unknown error'}`,
        };
    }
};

export const can_handle = (): boolean => {
    try {
        return env.PICA_SECRET_KEY !== undefined;
    } catch (error) {
        console.error("Error checking Pica availability:", error);
        return false;
    }
};

//runAgentTask("Add a slot in my calendar for this week for and time when the weather is sunny in London")
//  .then((text) => {
//    console.log(text);
//  })
//  .catch(console.error);

