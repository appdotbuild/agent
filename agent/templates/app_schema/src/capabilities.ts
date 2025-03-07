import type { CustomToolHandler } from './common/tool-handler';
import * as perplexity from './integrations/perplexity';
import * as pica from './integrations/pica';

export const capabilities = [
  ...perplexity.get_all_tools(),
  ...pica.get_all_tools()
] satisfies CustomToolHandler[];
