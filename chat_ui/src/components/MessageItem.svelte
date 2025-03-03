<script lang="ts">
    import * as llm from '../llm';

    let { message } : { message: llm.MessageParam } = $props();
    let parts: { type: 'text' | 'handler_use' | 'handler_result', content: string }[] = Array.isArray(message.content) ? [] : [{ type: 'text', content: message.content }];
    if (Array.isArray(message.content)) {
        message.content.forEach((content) => {
            if (content.type === 'text') {
                parts.push({ type: 'text', content: content.text });
            } else if (content.type === 'tool_use') {
                parts.push({ type: 'handler_use', content: JSON.stringify({name: content.name, input: content.input }, null, 2) });
            } else if (content.type === 'tool_result') {
                parts.push({ type: 'handler_result', content: JSON.stringify({result: content.content }, null, 2) });
            }
        });
    }

    let expanded: boolean[] = $state(parts.map((p) => p.type === 'text'));
</script>

<div class="message-item {message.role}">
    <div class="avatar">
        {#if message.role === 'user'}
            <div class="user-avatar">U</div>
        {:else}
            <div class="assistant-avatar">A</div>
        {/if}
    </div>
    <div class="content">
        {#each parts as part, i}
            {#if part.type === 'text'}
                <div class="message-text">
                    {part.content}
                </div>
            {:else}
                <div class="tool-container">
                    <button 
                        class="message-tool-toggle" 
                        class:expanded={expanded[i]} 
                        onclick={() => expanded[i] = !expanded[i]}
                    >
                        {expanded[i] ? '▼' : '▶'} {part.type.replace('_', ' ')}
                    </button>
                    <pre class="message-tool" class:hidden={!expanded[i]}>
                        {part.content}
                    </pre>
                </div>
            {/if}
        {/each}
    </div>
</div>

<style>
    .message-item {
        display: flex;
        margin-bottom: 8px;
        gap: 8px;
    }

    .avatar {
        flex-shrink: 0;
        width: 32px;
        height: 32px;
    }

    .user-avatar, .assistant-avatar {
        width: 100%;
        height: 100%;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: bold;
        color: white;
    }

    .user-avatar {
        background-color: #4a90e2;
    }

    .assistant-avatar {
        background-color: #50b36e;
    }

    .content {
        flex: 1;
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .message-text {
        padding: 10px 14px;
        border-radius: 18px;
        max-width: 100%;
        word-wrap: break-word;
        white-space: pre-wrap;
        line-height: 1.4;
    }

    .user .message-text {
        background-color: #4a90e2;
        color: white;
        border-top-right-radius: 4px;
    }

    .assistant .message-text {
        background-color: #f1f1f1;
        color: #333;
        border-top-left-radius: 4px;
    }

    .tool-container {
        margin-top: 4px;
    }

    .message-tool-toggle {
        background: none;
        border: none;
        color: #666;
        cursor: pointer;
        font-size: 0.85rem;
        padding: 4px 8px;
        border-radius: 4px;
        background-color: #f5f5f5;
        text-transform: capitalize;
    }

    .message-tool-toggle:hover {
        background-color: #e5e5e5;
    }

    .message-tool {
        margin: 4px 0;
        padding: 8px;
        background-color: #f8f8f8;
        border-radius: 4px;
        font-size: 0.85rem;
        overflow-x: auto;
        white-space: pre-wrap;
        border: 1px solid #eee;
    }

    .hidden {
        display: none;
    }
</style>
