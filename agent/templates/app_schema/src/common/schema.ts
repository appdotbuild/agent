// {{typescript_schema_definitions}}
// TODO: REMOVE THIS PLACEHOLDER
import { z } from 'zod';

export const greetingRequestSchema = z.object({
    name: z.string(),
    greeting: z.string(),
});

export type GreetingRequest = z.infer<typeof greetingRequestSchema>;

export declare function greet(options: GreetingRequest): Promise<string>;