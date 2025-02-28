import { z } from 'zod';

export const greetUserParamsSchema = z.object({
  name: z.string(),
  age: z.number(),
  today: z.coerce.date(),
});

export type GreetUserParams = z.infer<typeof greetUserParamsSchema>;

export const handle = (options: GreetUserParams): string => {
  return options.name + ' is ' + options.age + ' years old';
};
