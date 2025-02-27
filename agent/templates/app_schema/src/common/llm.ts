import AnthropicBedrock from '@anthropic-ai/bedrock-sdk';

export const client = new AnthropicBedrock({ awsRegion: 'us-west-2' });

export interface TextBlock {
  text: string;
  type: 'text';
}

export interface ImageBlockSource {
  data: string;
  media_type: 'image/jpeg' | 'image/png' | 'image/gif' | 'image/webp';
  type: 'base64';
}

export interface ImageBlock {
  source: ImageBlockSource;
  type: 'image';
}

export interface ToolUseBlock {
  id: string;
  input: unknown;
  name: string;
  type: 'tool_use';
}

export interface ToolResultBlock {
  tool_use_id: string;
  type: 'tool_result';
  content?: string | Array<TextBlock | ImageBlock>;
  is_error?: boolean;
}

export type ContentBlock =
  | TextBlock
  | ImageBlock
  | ToolUseBlock
  | ToolResultBlock;

export interface MessageParam {
  content: string | Array<ContentBlock>;
  role: 'user' | 'assistant';
}
