<script lang="ts">
  import ChatBox from './components/ChatBox.svelte';
</script>

<main>
  <div class="chat-container">
    <h1>Chat Application</h1>
    <ChatBox userId="test_user" />
  </div>
</main>

<style>
  :global(body) {
    margin: 0;
    padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif;
    background-color: #f5f5f5;
    color: #333;
  }

  main {
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 100vh;
    padding: 1rem;
  }

  .chat-container {
    width: 100%;
    max-width: 800px;
    height: 90vh;
    background-color: white;
    border-radius: 12px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  h1 {
    text-align: center;
    padding: 1rem;
    margin: 0;
    border-bottom: 1px solid #eee;
    font-size: 1.5rem;
    color: #2c3e50;
  }
</style>
