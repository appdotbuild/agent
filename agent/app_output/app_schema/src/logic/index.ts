import { GenericHandler } from "../common/handler";
import { dummyHandler } from "./dummy_handler";

export const handlers: {[key: string]: GenericHandler<any[], any>} = {
    'dummy': dummyHandler,
};