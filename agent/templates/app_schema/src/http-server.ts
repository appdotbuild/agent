import fastify from 'fastify';
import cors from '@fastify/cors';
import {
  validatorCompiler,
  serializerCompiler,
  type ZodTypeProvider,
} from 'fastify-type-provider-zod';
import { z } from 'zod';
import { handlers } from './tools';
import { env } from './env';
import { handleChat } from './common/chat';

const ALLOWED_ORIGINS = ['chatbot.build', 'localhost', 'admin.chatbot.build'];

export function launchHttpServer() {
  const port = env.APP_PORT;
  const reqTypeSchema = z.object({
    user_id: z.string(),
    message: z.string(),
  });

  const app = fastify({
    logger: true,
  });

  // Add schema validator and serializer
  app.setValidatorCompiler(validatorCompiler);
  app.setSerializerCompiler(serializerCompiler);

  // cors
  app.register(cors, {
    origin: (origin, callback) => {
      if (!origin) {
        callback(null, true);
        return;
      }

      const hostname = new URL(origin).hostname;
      if (ALLOWED_ORIGINS.includes(hostname)) {
        callback(null, true);
        return;
      }

      callback(new Error('Not allowed by CORS'), false);
    },
  });

  // routes
  app.withTypeProvider<ZodTypeProvider>().route({
    method: 'GET',
    url: '/health',
    handler: async () => {
      return { status: 'ok' };
    },
  });

  app.withTypeProvider<ZodTypeProvider>().route({
    method: 'POST',
    url: '/chat',
    schema: {
      body: reqTypeSchema,
    },
    handler: async ({ body }) => {
      const userReply = await handleChat({
        user_id: body.user_id,
        message: body.message,
      });
      return { reply: userReply };
    },
  });

  for (const handler of handlers) {
    app.withTypeProvider<ZodTypeProvider>().route({
      method: 'POST',
      url: `/handler/${handler.name}`,
      schema: {
        body: handler.inputSchema,
      },
      handler: async ({ body }) => {
        const result = await handler.handler(body);
        return { response: result };
      },
    });
  }

  app.listen({ port, host: '0.0.0.0' }, function (err) {
    if (err) {
      app.log.error(err);
      process.exit(1);
    }
  });
}
