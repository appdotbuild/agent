<script lang="ts">
    import * as llm from '../llm';
    import MessageItem from './MessageItem.svelte';

    let { userId = 'test_user' } = $props();

    let messages: llm.MessageParam[] = $state([]);
    let isLoading = $state(false);
    let input = $state('');
    let messagesContainer: HTMLElement;

    // Scroll to bottom when messages change
    $effect(() => {
        if (messagesContainer) {
            setTimeout(() => {
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
            }, 0);
        }
    });

    async function sendMessage() {
        if (input.trim() === '') {
            return;
        }
        
        const userInput = input;
        input = '';
        isLoading = true;
        
        try {
            const response = await llm.sendMessage(userId, userInput);
            messages = [...messages, ...response];
        } catch (error) {
            console.error('Error sending message:', error);
            messages = [...messages, {
                role: 'assistant',
                content: 'Sorry, there was an error processing your request.'
            }];
        } finally {
            isLoading = false;
        }
    }

    function handleKeyDown(e: KeyboardEvent) {
        if (e.key === 'Enter' && !isLoading) {
            sendMessage();
        }
    }
</script>

<div class="chat-box">
    <div class="messages-container" bind:this={messagesContainer}>
        {#each messages as message, i}
            <div class="message-wrapper {message.role}">
                <MessageItem message={message} />
            </div>
        {/each}
        {#if isLoading}
            <div class="loading-indicator">
                <div class="dot"></div>
                <div class="dot"></div>
                <div class="dot"></div>
            </div>
        {/if}
    </div>
    
    <div class="input-container">
        <input 
            type="text" 
            placeholder="Type your message here..." 
            bind:value={input} 
            onkeydown={handleKeyDown}
            disabled={isLoading}
        />
        <button 
            class="send-button" 
            aria-label="Send message"
            onclick={sendMessage} 
            disabled={isLoading || input.trim() === ''}
        >
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <line x1="22" y1="2" x2="11" y2="13"></line>
                <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
            </svg>
        </button>
    </div>
</div>

<style>
    .chat-box {
        display: flex;
        flex-direction: column;
        height: 100%;
        flex: 1;
        overflow: hidden;
    }

    .messages-container {
        flex: 1;
        overflow-y: auto;
        padding: 1rem;
        display: flex;
        flex-direction: column;
        gap: 1rem;
    }

    .message-wrapper {
        display: flex;
        max-width: 80%;
    }

    .message-wrapper.user {
        align-self: flex-end;
    }

    .message-wrapper.assistant {
        align-self: flex-start;
    }

    .input-container {
        display: flex;
        padding: 1rem;
        border-top: 1px solid #eee;
        background-color: white;
    }

    input {
        flex: 1;
        padding: 0.75rem 1rem;
        border: 1px solid #ddd;
        border-radius: 24px;
        font-size: 1rem;
        outline: none;
        transition: border-color 0.2s;
    }

    input:focus {
        border-color: #4a90e2;
    }

    .send-button {
        background-color: #4a90e2;
        color: white;
        border: none;
        border-radius: 50%;
        width: 40px;
        height: 40px;
        margin-left: 0.5rem;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        transition: background-color 0.2s;
    }

    .send-button:hover {
        background-color: #3a7bc8;
    }

    .send-button:disabled {
        background-color: #ccc;
        cursor: not-allowed;
    }

    .send-button svg {
        width: 18px;
        height: 18px;
    }

    .loading-indicator {
        display: flex;
        gap: 4px;
        padding: 10px;
        align-self: flex-start;
    }

    .dot {
        width: 8px;
        height: 8px;
        background-color: #aaa;
        border-radius: 50%;
        animation: bounce 1.4s infinite ease-in-out both;
    }

    .dot:nth-child(1) {
        animation-delay: -0.32s;
    }

    .dot:nth-child(2) {
        animation-delay: -0.16s;
    }

    @keyframes bounce {
        0%, 80%, 100% {
            transform: scale(0);
        }
        40% {
            transform: scale(1);
        }
    }
</style>
