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

const BASE_URL = 'http://localhost:3000/chat/json';

export async function sendMessage(userId: string, message: string): Promise<MessageParam[]> {
    const response = await fetch(BASE_URL, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ user_id: userId, message }),
    });
    return await response.json();
}

export const MOCK_MESSAGES: MessageParam[] = [
    {
      "role": "user",
      "content": "Hello, I'm John Doe!"
    },
    {
      "role": "assistant",
      "content": [
        {
          "type": "text",
          "text": "Hello! I can help create a greeting message for you. Since you provided your name \"John Doe\", I'll need just a couple more pieces of information to use the greeter function - your age and today's date/time. Could you please provide:\n1. Your age\n2. The current date and time\n\nOnce you provide these details, I can create a proper greeting message for you."
        }
      ]
    },
    {
      "role": "user",
      "content": "Today is February 25 2025"
    },
    {
      "role": "assistant",
      "content": [
        {
          "type": "text",
          "text": "Thank you for providing the date. I can include that, but I still need one more piece of information before I can create a proper greeting for you - your age. Could you please let me know your age? Once you provide that, I'll be able to create a complete greeting message using the greeter function."
        }
      ]
    },
    {
      "role": "user",
      "content": "999 y.o."
    },
    {
      "role": "assistant",
      "content": [
        {
          "type": "text",
          "text": "Now I have all the required information to create a greeting message for you! I'll use the greeter function with:\n- Name: \"John Doe\"\n- Age: 999\n- Today: \"2025-02-25T00:00:00Z\""
        },
        {
          "type": "tool_use",
          "id": "toolu_bdrk_017wozcdtvzAJ6KJMK2Z4JHC",
          "name": "greeter",
          "input": {
            "name": "John Doe",
            "age": 999,
            "today": "2025-02-25T00:00:00Z"
          }
        }
      ]
    },
    {
      "role": "user",
      "content": [
        {
          "type": "tool_result",
          "tool_use_id": "toolu_bdrk_017wozcdtvzAJ6KJMK2Z4JHC",
          "content": "\"John Doe is 999 years old\""
        }
      ]
    }
  ];