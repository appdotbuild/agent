import { createEnv } from '@t3-oss/env-core';
import { z } from 'zod';

import 'dotenv/config';

// all env variables are strings
const coercedBoolean = z.string().transform((s) => s !== 'false' && s !== '0');

export const env = createEnv({
  server: {
    APP_DATABASE_URL: z.string(),
    TELEGRAM_BOT_TOKEN: z.string(),
    APP_PORT: z.coerce.number().default(3000),
    RUN_MODE: z.enum(['telegram', 'http-server']).default('telegram'),
    LOG_RESPONSE: coercedBoolean.default('false'),
    PERPLEXITY_API_KEY: z.string().optional(),
  },
  runtimeEnv: process.env,
  emptyStringAsUndefined: true,
});
