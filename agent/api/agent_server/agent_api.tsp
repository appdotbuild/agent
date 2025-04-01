import "@typespec/http";
import "@typespec/rest";

using TypeSpec.Http;
using TypeSpec.Rest;

@service({
  title: "Agent Server API",
  version: "1.0.0",
})
@doc("API for communication between the Platform (Backend) and the Agent Server.")
namespace AgentServerApi;

// --- Enums ---

@doc("Defines the status of the Agent Server during processing.")
enum AgentStatus {
  @doc("Agent is actively processing the request.")
  running,

  @doc("Agent has completed its current task or requires user feedback.")
  idle,
}

@doc("Defines the type of message being sent from the Agent Server.")
enum MessageKind {
  @doc("An intermediate result/update while the agent is still running. The platform should not typically send this state back unless restoring after a failure.")
  StageResult,

  @doc("The agent has paused and requires feedback or input from the user.")
  FeedbackResponse,

  @doc("The agent encountered an error it couldn't recover from. Retrying likely requires user intervention or infrastructure changes.")
  RuntimeError,
}

// --- Models ---

@doc("The detailed message payload from the agent.")
model AgentMessage {
  @doc("The type of message being sent.")
  kind: MessageKind;

  @doc("Formatted content of the message. Can be long and contain formatting, including custom URLs for CLI handling.")
  content: string;

  @doc("Updated state of the Agent Server that should be presented in the next request to continue the conversation.")
  agentState: Record<string, unknown> | null;

  @doc("A unified diff format string representing code changes made by the agent, if any. Null if no diff is available.")
  unifiedDiff: string | null;
}

@doc("Structure of the data payload within each Server-Sent Event (SSE).")
model AgentSseEvent {
  @doc("Current status of the agent (running or idle).")
  status: AgentStatus;

  @doc("The trace ID corresponding to the POST request that initiated this stream of events.")
  traceId: string;

  @doc("The detailed message payload from the agent.")
  message: AgentMessage;
}

@doc("Request body for initiating or continuing interaction with the Agent Server.")
model AgentRequest {
  @doc("History of all user messages in the current conversation thread.")
  allMessages: string[];

  @doc("Unique identifier for the chatbot instance. Used for tracing and context.")
  chatbotId: string;

  @doc("Unique identifier for this specific request/response cycle. Used to correlate SSE events back to the originating POST request.")
  traceId: string;

  @doc("The full state of the Agent Server to restore from. This is an opaque object from the platform's perspective and should not be modified.")
  agentState?: Record<string, unknown> | null;

  @doc("Settings for the agent execution, such as maximum number of iterations.")
  settings?: Record<string, unknown>;
}

// --- Operations ---

@doc("Main endpoint for sending user messages and receiving agent responses via Server-Sent Events.")
@route("/message")
interface MessageOperations {
  @post
  @summary("Send a message to the agent and stream responses.")
  @doc("""
  Sends user input and conversation context to the Agent Server.
  The server responds with a stream of Server-Sent Events (SSE) of type `text/event-stream`.
  Each event in the stream will have a `data` field containing a JSON payload conforming to the `AgentSseEvent` model.
  The connection remains open until the agent reaches an 'idle' state or a 'RuntimeError' occurs.

  **SSE Event Format:**
  event: message
  data: {"status": "...", "traceId": "...", "message": {...}}
  """)
  sendMessage(
    @body body: AgentRequest
  ): OkResponse<string> | BadRequestResponse | InternalServerErrorResponse;
}

@doc("Standard Bad Request response.")
model BadRequestResponse {
  @statusCode _: 400;
  @body body: {
    error: string;
  };
}

@doc("Standard Internal Server Error response.")
model InternalServerErrorResponse {
  @statusCode _: 500;
  @body body: {
    error: string;
    details?: string;
  };
}