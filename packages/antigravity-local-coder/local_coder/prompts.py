"""Canonical prompt templates and extraction helpers for local_coder."""

import re

SYSTEM_CODER = (
    "You are an expert software engineer and principal architect. "
    "Output only clean, robust, production-grade code. "
    "Wrap your output in standard ```python ... ``` markdown blocks unless requested otherwise. "
    "Include type annotations and docstrings."
)

_LANGUAGE_NAME = re.compile(r"[a-z0-9_+#.\-]{1,24}")


def normalize_language(language: str | None) -> str:
    """Lower-case language name for prompts and fences; ``py``/``python3`` mean ``python``.

    Raises ValueError for anything that is not a short plain token, since the name goes into the prompt.
    """
    name = (language or "python").strip().lower()
    if not _LANGUAGE_NAME.fullmatch(name):
        raise ValueError(
            f"Invalid language {language!r}: use a short name such as python, bash, dockerfile, yaml or typescript"
        )
    return "python" if name in ("py", "python3") else name


def is_python(language: str | None) -> bool:
    return normalize_language(language) == "python"


def system_coder(language: str | None = "python") -> str:
    """System prompt for code generation in ``language`` (the Python one also asks for types and docstrings)."""
    lang = normalize_language(language)
    if lang == "python":
        return SYSTEM_CODER
    return (
        f"You are an expert software engineer. Output only clean, robust, production-grade {lang} code. "
        f"Wrap your output in a single ```{lang} ... ``` markdown block and add no explanation outside it."
    )


SYSTEM_REVIEWER = (
    "You are an expert security auditor and software architect. "
    "Audit the code thoroughly for race conditions, resource leaks, memory safety, "
    "unhandled exceptions, and edge cases. Provide clear, actionable recommendations."
)


def extract_code_block(response_text: str, language: str = "python") -> str:
    """Extract the code from an answer.

    Order: the first ```<language> block; else the first fenced block of any language (its info string, such as
    ``bash``, is not part of the code); else, for a fence that was never closed (a cut-off answer), everything after
    the opening fence line; else the whole answer. Only one block is returned: a second block is not appended.
    """
    match = re.search(rf"```{re.escape(language)}[ \t]*\r?\n?([\s\S]*?)```", response_text, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    fenced = re.search(r"```[^\n`]*\r?\n([\s\S]*?)```", response_text)
    if fenced:
        return fenced.group(1).strip()

    opening = re.search(r"```[^\n`]*\r?\n", response_text)
    if opening:
        return response_text[opening.end() :].strip()

    return response_text.strip()


def build_code_prompt(
    task: str, context_files: dict[str, str] | None = None, language: str | None = "python"
) -> list[dict[str, str]]:
    """Build messages for code generation in ``language`` (default Python)."""
    lang = normalize_language(language)
    user_prompt = f"TASK: {task}\n\n"
    if context_files:
        user_prompt += "CONTEXT FILES:\n"
        for path, content in context_files.items():
            user_prompt += f"--- {path} ---\n{content}\n\n"
    if lang == "python":
        user_prompt += (
            "INSTRUCTIONS:\n"
            "- Write the complete implementation in Python.\n"
            "- Use proper typing and docstrings.\n"
            "- Respond with the code inside a ```python ... ``` block."
        )
    else:
        user_prompt += (
            "INSTRUCTIONS:\n"
            f"- Write the complete implementation in {lang}.\n"
            f"- Follow the idioms and conventions of {lang}.\n"
            f"- Respond with the code inside a single ```{lang} ... ``` block."
        )
    return [
        {"role": "system", "content": system_coder(lang)},
        {"role": "user", "content": user_prompt},
    ]


def build_test_prompt(
    source_code: str,
    file_path: str,
    framework: str | None = None,
    instructions: str | None = None,
    language: str | None = "python",
) -> list[dict[str, str]]:
    """Build messages for unit test authoring."""
    lang = normalize_language(language) if language else "python"
    if framework is None and lang == "python":
        framework = "pytest"
    fw_instruction = (
        f"- Write a comprehensive test suite for the code above using `{framework}`.\n"
        if framework
        else "- Write a comprehensive test suite for the code above.\n"
    )
    user_prompt = (
        f"SOURCE FILE: {file_path}\n"
        f"```{lang}\n{source_code}\n```\n\n"
        f"INSTRUCTIONS:\n"
        f"{fw_instruction}"
        f"- Cover happy paths, edge cases, error conditions, and parameter validation.\n"
        f"- Provide realistic fixtures/mocks where appropriate.\n"
        + (f"- {instructions}\n" if instructions else "")
        + f"- Respond only with the test code inside a single ```{lang} ... ``` block."
    )
    return [
        {"role": "system", "content": system_coder(lang)},
        {"role": "user", "content": user_prompt},
    ]


_EXTENSION_LANGUAGES = {
    ".py": "python", ".pyi": "python", ".sh": "bash", ".bash": "bash", ".zsh": "bash", ".js": "javascript",
    ".mjs": "javascript", ".cjs": "javascript", ".jsx": "jsx", ".ts": "typescript", ".tsx": "tsx", ".go": "go",
    ".rs": "rust", ".java": "java", ".kt": "kotlin", ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp",
    ".hpp": "cpp", ".cs": "csharp", ".rb": "ruby", ".php": "php", ".swift": "swift", ".sql": "sql",
    ".yaml": "yaml", ".yml": "yaml", ".json": "json", ".toml": "toml", ".md": "markdown", ".html": "html",
    ".css": "css", ".lua": "lua", ".ps1": "powershell", ".tf": "hcl",
}  # fmt: skip
_NAME_LANGUAGES = {"dockerfile": "dockerfile", "makefile": "makefile"}


def language_for_path(file_path: str | None) -> str | None:
    """Best guess of a file's language from its name or extension, or None when it is not recognised."""
    if not file_path:
        return None
    name = re.split(r"[\\/]", file_path)[-1].lower()
    if name in _NAME_LANGUAGES:
        return _NAME_LANGUAGES[name]
    dot = name.rfind(".")
    return _EXTENSION_LANGUAGES.get(name[dot:]) if dot != -1 else None


def build_review_prompt(
    source_code: str, file_path: str, focus: str | None = None, language: str | None = None
) -> list[dict[str, str]]:
    """Build messages for architecture and security audit.

    The code is fenced with ``language``, else the language guessed from ``file_path``, else a bare fence.
    """
    lang = normalize_language(language) if language else (language_for_path(file_path) or "")
    user_prompt = f"FILE: {file_path}\n```{lang}\n{source_code}\n```\n\n"
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
    source_code: str,
    file_path: str,
    type_hints: bool = True,
    docstrings: bool = True,
    instructions: str | None = None,
    language: str | None = "python",
) -> list[dict[str, str]]:
    """Build messages for refactoring and typing."""
    lang = normalize_language(language) if language else "python"
    directives: list[str] = []
    if lang == "python":
        if type_hints:
            directives.append("Add strict PEP 484 type annotations across all functions, methods, and variables.")
        if docstrings:
            directives.append("Add comprehensive PEP 257 docstrings with parameter descriptions and return types.")
    if instructions:
        directives.append(instructions)
    if not directives:
        directives.append("Improve readability and naming.")
    directives.append("Preserve all existing business logic and public interfaces.")
    directives.append(f"Respond only with the complete refactored code inside a single ```{lang} ... ``` block.")

    user_prompt = f"FILE: {file_path}\n```{lang}\n{source_code}\n```\n\nINSTRUCTIONS:\n- " + "\n- ".join(directives)
    return [
        {"role": "system", "content": system_coder(lang)},
        {"role": "user", "content": user_prompt},
    ]


def build_heal_prompt(invalid_code: str, error_message: str) -> list[dict[str, str]]:
    """Build messages to heal Python code that failed validation."""
    user_prompt = (
        f"The following Python code failed validation:\n\n"
        f"```python\n{invalid_code}\n```\n\n"
        f"VALIDATION ERROR:\n{error_message}\n\n"
        f"INSTRUCTIONS:\n"
        f"- Fix the error while preserving the exact intended behavior.\n"
        f"- Keep every existing function, class and test; do not remove or shorten code.\n"
        f"- Respond ONLY with the corrected code inside a ```python ... ``` block."
    )
    return [
        {"role": "system", "content": SYSTEM_CODER},
        {"role": "user", "content": user_prompt},
    ]
