import { z } from 'zod';
import * as greet from './handlers/dummy_handler';
import * as web_search from './handlers/web_search';
interface ToolHandler<argSchema extends z.ZodObject<any>> {
  name: string;
  description: string;
  handler: (options: z.infer<argSchema>) => any;
  inputSchema: argSchema;
}

export const handlers = [
  {
    name: 'greeter',
    description: 'create a greeting message',
    handler: greet.handle,
    inputSchema: greet.greetUserParamsSchema,
    },
    {
        name: "web_search",
        description: "search the web for information",
        handler: web_search.handle,
        inputSchema: web_search.webSearchParamsSchema,
    }
] satisfies ToolHandler<any>[];
