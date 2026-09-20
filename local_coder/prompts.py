"""Canonical prompt templates and extraction helpers for local_coder."""

import re

SYSTEM_CODER = (
    "You are an expert software engineer and principal architect. "
    "Output only clean, robust, production-grade code. "
    "Wrap your output in standard ```python ... ``` markdown blocks unless requested otherwise. "
    "Include type annotations and docstrings."
)

SYSTEM_REVIEWER = (
    "You are an expert security auditor and software architect. "
    "Audit the code thoroughly for race conditions, resource leaks, memory safety, "
    "unhandled exceptions, and edge cases. Provide clear, actionable recommendations."
)


def extract_code_block(response_text: str, language: str = "python") -> str:
    """Extract code from markdown code fences or return stripped raw text."""
    pattern = rf"```{language}\s*([\s\S]*?)```"
    match = re.search(pattern, response_text, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    generic_pattern = r"```\s*([\s\S]*?)```"
    generic_match = re.search(generic_pattern, response_text)
    if generic_match:
        return generic_match.group(1).strip()

    return response_text.strip()


def build_code_prompt(task: str, context_files: dict[str, str] | None = None) -> list[dict[str, str]]:
    """Build messages for code generation."""
    user_prompt = f"TASK: {task}\n\n"
    if context_files:
        user_prompt += "CONTEXT FILES:\n"
        for path, content in context_files.items():
            user_prompt += f"--- {path} ---\n{content}\n\n"
    user_prompt += (
        "INSTRUCTIONS:\n"
        "- Write the complete implementation in Python.\n"
        "- Use proper typing and docstrings.\n"
        "- Respond with the code inside a ```python ... ``` block."
    )
    return [
        {"role": "system", "content": SYSTEM_CODER},
        {"role": "user", "content": user_prompt},
    ]


def build_test_prompt(source_code: str, file_path: str, framework: str = "pytest") -> list[dict[str, str]]:
    """Build messages for unit test authoring."""
    user_prompt = (
        f"SOURCE FILE: {file_path}\n"
        f"```python\n{source_code}\n```\n\n"
        f"INSTRUCTIONS:\n"
        f"- Write a comprehensive test suite for the code above using `{framework}`.\n"
        f"- Cover happy paths, edge cases, error conditions, and parameter validation.\n"
        f"- Provide realistic fixtures/mocks where appropriate.\n"
        f"- Respond only with the test code inside a ```python ... ``` block."
    )
    return [
        {"role": "system", "content": SYSTEM_CODER},
        {"role": "user", "content": user_prompt},
    ]


def build_review_prompt(source_code: str, file_path: str, focus: str | None = None) -> list[dict[str, str]]:
    """Build messages for architecture and security audit."""
    user_prompt = f"FILE: {file_path}\n```python\n{source_code}\n```\n\n"
    if focus:
        user_prompt += f"AUDIT FOCUS: {focus}\n\n"
    user_prompt += (
        "INSTRUCTIONS:\n"
        "- Provide a structured code review.\n"
        "- Identify potential race conditions, edge-case bugs, security vulnerabilities, or performance bottlenecks.\n"
        "- Include code snippet suggestions for any recommended fixes."
    )
    return [
        {"role": "system", "content": SYSTEM_REVIEWER},
        {"role": "user", "content": user_prompt},
    ]


def build_refactor_prompt(
    source_code: str, file_path: str, type_hints: bool = True, docstrings: bool = True
) -> list[dict[str, str]]:
    """Build messages for refactoring and typing."""
    instructions = []
    if type_hints:
        instructions.append("Add strict PEP 484 type annotations across all functions, methods, and variables.")
    if docstrings:
        instructions.append("Add comprehensive PEP 257 docstrings with parameter descriptions and return types.")
    instructions.append("Preserve all existing business logic and public interfaces.")
    instructions.append("Respond only with the complete refactored code inside a ```python ... ``` block.")

    user_prompt = f"FILE: {file_path}\n```python\n{source_code}\n```\n\nINSTRUCTIONS:\n- " + "\n- ".join(instructions)
    return [
        {"role": "system", "content": SYSTEM_CODER},
        {"role": "user", "content": user_prompt},
    ]


def build_heal_prompt(invalid_code: str, error_message: str) -> list[dict[str, str]]:
    """Build messages to heal a Python syntax error."""
    user_prompt = (
        f"The following Python code produced a syntax error:\n\n"
        f"```python\n{invalid_code}\n```\n\n"
        f"SYNTAX ERROR:\n{error_message}\n\n"
        f"INSTRUCTIONS:\n"
        f"- Fix the syntax error while preserving the exact intended behavior.\n"
        f"- Respond ONLY with the corrected code inside a ```python ... ``` block."
    )
    return [
        {"role": "system", "content": SYSTEM_CODER},
        {"role": "user", "content": user_prompt},
    ]
