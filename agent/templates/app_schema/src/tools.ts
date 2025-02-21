import * as schema from './common/schema';
import * as greet from './handlers/dummy_handler';

export const handlers = [
    {
        name: "greeter",
        description: "create a greeting message",
        handler: greet.handle,
        inputSchema: greet.greetUserParamsSchema,
    }
]
