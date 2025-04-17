from api.fsm_tools import run_main as run_main_fsm_tools


def test_fsmtools_e2e():
    messages = run_main_fsm_tools()
    assert len(messages) > 1
