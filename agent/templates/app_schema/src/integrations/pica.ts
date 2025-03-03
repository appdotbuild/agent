import { anthropic } from "@ai-sdk/anthropic";
import { generateText } from "ai";
import { Pica } from "@picahq/ai";
import { env } from "../env";

const pica = new Pica(env.PICA_SECRET_KEY!);

async function runAgentTask(message: string): Promise<string> {
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

runAgentTask("Add a slot in my calendar for this week for and time when the weather is sunny in London")
  .then((text) => {
    console.log(text);
  })
  .catch(console.error);