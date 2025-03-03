import { z } from 'zod';
import * as greet from './handlers/dummy_handler';

export interface ToolHandler<argSchema extends z.ZodObject<any>> {
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
] satisfies ToolHandler<any>[];
