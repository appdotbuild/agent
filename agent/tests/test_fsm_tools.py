from api.fsm_tools import run_main as run_main_fsm_tools
from api.agent_server.agent_api_client import DEFAULT_APP_REQUEST


def test_fsmtools_e2e():
    messages = run_main_fsm_tools(DEFAULT_APP_REQUEST)
    assert len(messages) > 1
