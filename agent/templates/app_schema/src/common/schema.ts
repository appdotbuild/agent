// {{typescript_schema_definitions}}
import { z } from 'zod';

export const greetUserParamsSchema = z.object({
    name: z.string(),
    age: z.number(),
    today: z.coerce.date(),
});

export type GreetUserParams = z.infer<typeof greetUserParamsSchema>;
