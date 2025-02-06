// {{typescript_schema_definitions}}
// Model definition
export interface Greeting {
    greeting: string;
    userName?: string;
}

// Bot interface as a type
export type GreetingBot = {
    respond: (greeting: Greeting) => string;
}

// Optional: Type for LLM function (if needed in implementation)
export type LLMFunction = (input: Greeting) => string;