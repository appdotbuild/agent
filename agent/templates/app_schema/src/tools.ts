import type { ToolHandler } from './common/tool-handler';
import * as greet from './handlers/dummy_handler';

export const handlers = [
  {
    name: 'greeter',
    description: 'create a greeting message',
    handler: greet.handle,
    inputSchema: greet.greetUserParamsSchema,
  },
] satisfies ToolHandler<any>[];
