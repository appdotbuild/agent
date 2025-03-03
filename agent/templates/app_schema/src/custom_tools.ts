import * as perplexity from './integrations/perplexity';
import type { ToolHandler } from './tools';

interface CustomToolHandler extends ToolHandler<any> {
  can_handle: () => boolean;
}

export const custom_handlers = [
  {
      name: "web_search",
      description: "search the web for information",
      handler: perplexity.handle_search_web,
      can_handle: perplexity.can_handle_search_web,
      inputSchema: perplexity.webSearchParamsSchema,
  }
] satisfies CustomToolHandler[];
