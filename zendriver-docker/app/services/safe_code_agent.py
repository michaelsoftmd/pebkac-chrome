"""
SafeCodeAgent - Handles multiple final_answer calls and execution errors
"""

import logging
from typing import Any, Optional, Dict
from smolagents import CodeAgent

logger = logging.getLogger(__name__)


class SafeCodeAgent(CodeAgent):
    """
    CodeAgent that handles multiple final_answer calls
    and retries on missing final_answer.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.execution_log = []
        self.last_code = None

    def run(self, task: str, **kwargs) -> Any:
        """Run the agent with SmolAgents error handling"""
        try:
            result = super().run(task, **kwargs)

            # Check for missing final_answer
            if not self._has_final_answer(result):
                # Retry with instruction
                logger.warning("No final_answer detected, retrying with explicit instruction")
                enhanced_task = f"{task}\n\nIMPORTANT: End with final_answer(your_result)"
                result = super().run(enhanced_task, **kwargs)

            return result

        except Exception as e:
            # Don't create fake answers, let the error be visible
            logger.error(f"Agent execution failed: {e}")
            raise

    def execute(self, code: str, state: Optional[Dict] = None) -> Any:
        """Execute call - let errors propagate naturally"""
        self.last_code = code

        # Check for multiple final_answer calls
        if code.count('final_answer') > 1:
            logger.warning(f"Multiple final_answer calls detected, restructuring code")
            code = self._restructure_code(code)

        # Just execute - no error suppression
        try:
            result = super().execute(code, state)
            return result
        except Exception as e:
            # Log for debugging but let it bubble up
            logger.error(f"Execution failed: {e}")
            raise  # Let SmolAgents handle it

    def _restructure_code(self, code: str) -> str:
        """Restructure code to ensure single final_answer at the end."""
        lines = code.split('\n')
        final_answer_lines = []
        other_lines = []

        for line in lines:
            if 'final_answer' in line and not line.strip().startswith('#'):
                final_answer_lines.append(line)
            else:
                other_lines.append(line)

        if len(final_answer_lines) > 1:
            logger.info(f"Restructuring: keeping last of {len(final_answer_lines)} final_answer calls")
            restructured = '\n'.join(other_lines)
            if final_answer_lines:
                restructured += '\n' + final_answer_lines[-1]
            return restructured

        return code

    def _has_final_answer(self, result: Any) -> bool:
        """Check if final_answer() function was actually called successfully."""
        if result is None:
            return False

        # Check if result is the actual return value from final_answer()
        # SmolAgents returns the function result directly when successful
        if isinstance(result, (str, dict, list, int, float)):
            # If we get a concrete result, final_answer was called
            return True

        # For other types, check if it looks like an error or incomplete execution
        result_str = str(result).lower()

        # Signs that execution failed or was incomplete
        error_indicators = [
            "error", "exception", "failed", "traceback",
            "undefined", "none", "null"
        ]

        return not any(indicator in result_str for indicator in error_indicators)
