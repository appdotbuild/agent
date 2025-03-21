import { createTRPCClient, httpBatchLink } from '@trpc/client';
import type { AppRouter } from '../../../server/src';
import superjson from 'superjson';

export const trpc = createTRPCClient<AppRouter>({
  links: [httpBatchLink({ url: 'http://localhost:2022', transformer: superjson })],
});
