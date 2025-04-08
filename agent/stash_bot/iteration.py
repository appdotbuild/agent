from typing import Dict
from core.datatypes import ApplicationOut

def get_scenarios_message(bot: ApplicationOut) -> str:
    """
    Extracts scenario information from the bot and formats it as a message.
    """
    if bot.typespec and bot.typespec.llm_functions:
        scenarios = [f.name for f in bot.typespec.llm_functions]
        return ", ".join(scenarios)
    return "None"

def get_typespec_metadata(bot: ApplicationOut) -> Dict:
    """
    Extracts typespec information from the bot and returns it as a dictionary for metadata.
    """
    metadata = {
        "reasoning": bot.typespec.reasoning,
        "typespec": bot.typespec.typespec_definitions,
        "error_output": bot.typespec.error_output
    }
    
    # Add scenarios if available
    if bot.typespec.llm_functions:
        metadata["scenarios"] = {f.name: f.scenario for f in bot.typespec.llm_functions}
    
    return metadata