import * as perplexity from './integrations/perplexity';
import * as pica from './integrations/pica';
import type { ToolHandler } from './tools';

interface CustomToolHandler extends ToolHandler<any> {
  can_handle: () => boolean;
}

export const custom_handlers = [
  {
      name: "web_search",
      description: "search the web for information",
      handler: perplexity.handle_search_web,
      can_handle: perplexity.can_handle,
      inputSchema: perplexity.webSearchParamsSchema,
  },
  {
    name: "run_agent",
    description: "run an agent with following integrations enabled: calendar, notion",
    handler: pica.handle_run_agent,
    can_handle: pica.can_handle,
    inputSchema: pica.pica.oneTool,
  }
] satisfies CustomToolHandler[];
