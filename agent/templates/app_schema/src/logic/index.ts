import { GenericHandler } from "../common/handler";
import { dummyHandler } from "../handlers/dummy_handler";
import { perplexityHandler } from "../handlers/perplexity_handler";
export const handlers: {[key: string]: GenericHandler<any, any>} = {
    'dummy': dummyHandler,
    'perplexity': perplexityHandler,
};