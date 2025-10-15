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
        """Execute call with automatic code repair"""
        self.last_code = code

        # Auto-repair common formatting issues before execution
        code = self._auto_repair_code(code)

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

    def _auto_repair_code(self, code: str) -> str:
        """Automatically fix common code formatting issues that break execution"""
        import re

        original_code = code

        # 1. Remove text before opening code (common error: "Let me... <code>")
        # Pattern: any text followed by <code>
        code = re.sub(r'^.*?<code>\s*', '', code, flags=re.DOTALL)

        # 2. Remove explanation text BEFORE tool calls or final_answer
        # Pattern: "The website has... \n\nfinal_answer(...)" -> just keep "final_answer(...)"
        # Look for lines that are plain English followed by code
        if 'final_answer(' in code or any(tool in code for tool in ['web_search(', 'visit_webpage(', 'extract_content(']):
            lines = code.split('\n')
            code_start_idx = -1

            # Find first line that looks like actual Python code (not explanation)
            for i, line in enumerate(lines):
                stripped = line.strip()
                # Code indicators: starts with tool call, import, or assignment
                if stripped and (
                    'final_answer(' in stripped or
                    stripped.startswith(('import ', 'from ', 'web_search(', 'visit_webpage(', 'extract_content(',
                                        'navigate_browser(', 'click_element(', 'type_text(')) or
                    '=' in stripped and not stripped.startswith('#')
                ):
                    code_start_idx = i
                    break

            # If we found code start and it's not the first line, remove preceding explanation
            if code_start_idx > 0:
                code = '\n'.join(lines[code_start_idx:])

        # 3. Remove backtick artifacts that cause unterminated strings
        # Pattern: "` tags and ensure..." -> just remove it
        code = re.sub(r'`\s+tags\s+and\s+\w+', '', code, flags=re.IGNORECASE)
        code = re.sub(r'`\s+tags', '', code)

        # 4. Remove text after final_answer that's not valid code
        # This handles: final_answer("answer")</code> [explanation text]
        if 'final_answer' in code:
            lines = code.split('\n')
            final_answer_idx = -1

            # Find the last final_answer call
            for i, line in enumerate(lines):
                if 'final_answer(' in line and not line.strip().startswith('#'):
                    final_answer_idx = i

            # If found, check lines after it for non-code text
            if final_answer_idx >= 0 and final_answer_idx < len(lines) - 1:
                # Keep only lines that look like valid code after final_answer
                valid_lines = lines[:final_answer_idx + 1]

                # Check subsequent lines - keep if they're blank or closing tags
                for line in lines[final_answer_idx + 1:]:
                    stripped = line.strip()
                    if not stripped or stripped.startswith('#') or stripped == '</code>':
                        valid_lines.append(line)
                    else:
                        # Stop at first line that looks like explanation text
                        break

                code = '\n'.join(valid_lines)

        # 5. Strip markdown code block markers
        code = code.replace('```python', '').replace('```', '')

        # 6. Remove </code> closing tags that might be inside the code
        code = code.replace('</code>', '')

        # 7. Clean up leading/trailing whitespace
        code = code.strip()

        # Log repairs if significant changes were made
        if code != original_code:
            logger.info(f"Auto-repaired code (removed {len(original_code) - len(code)} chars)")
            logger.debug(f"Original: {original_code[:200]}...")
            logger.debug(f"Repaired: {code[:200]}...")

        return code

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
        """Check if result.output is present (return_full_result=True behavior)"""
        if result is None:
            return False

        if hasattr(result, 'output') and result.output is not None:
            return True

        return False
