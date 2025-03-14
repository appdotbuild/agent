import fastify from 'fastify';
import {
    validatorCompiler,
    serializerCompiler,
    type ZodTypeProvider,
} from 'fastify-type-provider-zod';
import { z } from 'zod';


const reqTypeSchema = z.object({
    message: z.string(),
});

const app = fastify({
    logger: true,
});

// Add schema validator and serializer
app.setValidatorCompiler(validatorCompiler);
app.setSerializerCompiler(serializerCompiler);

app.withTypeProvider<ZodTypeProvider>().route({
    method: 'POST',
    url: '/message',
    schema: {
        body: reqTypeSchema,
    },
    handler: async ({ body }) => {
        console.log('Message:', body.message);
        return { reply: 'Hello!' };
    },
});