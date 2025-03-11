import type { CustomToolHandler } from './common/tool-handler';
import * as perplexity from './integrations/perplexity';
import * as pica from './integrations/pica';

export const custom_handlers = [
  {
      name: "perplexity_web_search",
      description: "search the web for information",
      handler: perplexity.web_search,
      can_handle: perplexity.can_handle,
      inputSchema: perplexity.web_search_params_schema,
  },
  {
    name: "pica_calendar",
    description: "run an agent with following integrations enabled: calendar, notion",
    handler: pica.calendar,
    can_handle: pica.can_handle,
    inputSchema: pica.calendar_params_schema,
  }
] satisfies CustomToolHandler[];
