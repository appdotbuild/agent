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
import getPort from 'get-port';

const ALLOWED_ORIGINS = [
  'chatbot.build',
  'admin.chatbot.build',
  'localhost',
  '127.0.0.1',
];

export async function launchHttpServer() {
  let port = env.APP_PORT;
  if (env.NODE_ENV === 'development') {
    // get a random port if the port is already in use
    port = await getPort({ port: env.APP_PORT });
  }

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
    } else {
      console.log(`Server is running on port ${port}`);
    }
  });

  const gracefulShutdown = async () => {
    console.log('Shutting down server gracefully...');
    try {
      await app.close();
      console.log('Server shut down successfully');
      process.exit(0);
    } catch (err) {
      console.error('Error during shutdown:', err);
      process.exit(1);
    }
  };

  // Listen for termination signals
  process.on('SIGTERM', gracefulShutdown);
  process.on('SIGINT', gracefulShutdown);
}
