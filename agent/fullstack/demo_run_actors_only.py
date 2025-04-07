import os
import anyio
import dagger
from dagger import dag
from anthropic import AsyncAnthropicBedrock
from workspace import Workspace
from models.anthropic_bedrock import AnthropicBedrockLLM
import trpc_agent


HARD_PROMPT = """
Task tracking application with projects, tasks and users.

Entities & Properties

User

id, name, email, role (Admin, User), createdAt, updatedAt

Task

id, title, description, status (To-Do, In Progress, Done, Custom), priority (Low, Medium, High), dueDate, createdBy (User ID), assignedTo (User ID), projectId (Project ID), comments (List of Comment IDs), attachments (List of Attachment IDs), history (List of Changes), createdAt, updatedAt

Project

id, name, description, createdBy (User ID), members (List of User IDs), tasks (List of Task IDs), createdAt, updatedAt

Comment

id, taskId (Task ID), authorId (User ID), content, createdAt

Attachment

id, taskId (Task ID), filePath, uploadedBy (User ID), createdAt

Notification

id, userId (User ID), message, isRead, createdAt

Usage Scenarios

User Management

Admins manually create, update, or remove users.

Task Management

Create, update, assign, and delete tasks.

Add comments and attachments to tasks.

Track task history.

Project Management

Create projects and assign members.

Organize tasks within projects.

Workflow & Status Updates

Update task status and priority.

Move tasks between statuses.

Notifications

Notify users when assigned a task or mentioned.

Send due date reminders.

Searching & Filtering

Search and filter tasks by title, status, priority, due date, and project.
""".strip()


SIMPLE_PROMPT = "Simple todo app"


async def generate():
    user_prompt = SIMPLE_PROMPT

    m_client = AnthropicBedrockLLM(AsyncAnthropicBedrock(aws_profile="dev", aws_region="us-west-2"))

    workspace = await Workspace.create(
        base_image="oven/bun:1.2.5-alpine",
        context=dag.host().directory("./prefabs/trpc_fullstack"),
        setup_cmd=[["bun", "install"]],
    )
    backend_workspace = workspace.clone().cwd("/app/server")
    frontend_workspace = workspace.clone().cwd("/app/client")

    model_params = {
        "model": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
        "max_tokens": 8192,
    }
    draft_actor = trpc_agent.DraftActor(m_client, backend_workspace.clone(), model_params)
    handlers_actor = trpc_agent.HandlersActor(m_client, backend_workspace.clone(), model_params, beam_width=3)
    index_actor = trpc_agent.IndexActor(m_client, backend_workspace.clone(), model_params, beam_width=3)
    front_actor = trpc_agent.FrontendActor(m_client, frontend_workspace.clone(), model_params, beam_width=1, max_depth=20)

    server_files = {}

    print("Generating draft...")
    draft_res = await draft_actor.execute(user_prompt=user_prompt)
    assert draft_res is not None, "Draft solution failed"
    for node in draft_res.get_trajectory():
        server_files.update(node.data.files)
    
    print("Generating handlers...")
    handlers_res = await handlers_actor.execute(files=server_files)
    assert all(v is not None for v in handlers_res.values()), "Handlers generation failed"
    for solution in handlers_res.values():
        for node in solution.get_trajectory():
            server_files.update(node.data.files)
    
    print("Generating index...")
    index_res = await index_actor.execute(server_files)
    assert index_res is not None, "Index generation failed"
    for node in index_res.get_trajectory():
        server_files.update(node.data.files)

    frontend_files = {}

    print("Generating frontend...")
    frontend_res = await front_actor.execute(user_prompt=user_prompt, server_files=server_files)
    assert frontend_res is not None, "Frontend generation failed"
    for node in frontend_res.get_trajectory():
        frontend_files.update(node.data.files)
    print("All files generated")


async def main():
    async with dagger.connection(dagger.Config(log_output=open(os.devnull, "w"))):
        await generate()


if __name__ == "__main__":
    anyio.run(main)
