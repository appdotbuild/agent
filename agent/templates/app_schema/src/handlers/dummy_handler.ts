import { type GreetUserParams } from "../common/schema";

export const handle = (options: GreetUserParams): string => {
    return options.name + ' is ' + options.age + ' years old';
};
