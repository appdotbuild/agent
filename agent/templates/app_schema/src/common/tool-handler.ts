import { z } from 'zod';

export interface ToolHandler<argSchema extends z.ZodObject<any>> {
    name: string;
    description: string;
    handler: (options: z.infer<argSchema>) => any;
    inputSchema: argSchema;
  }

export interface CustomToolHandler extends ToolHandler<any> {
    can_handle: () => boolean;
  }
