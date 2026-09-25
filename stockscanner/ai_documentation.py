"""AI-powered documentation generation for functions and modules."""

import os
from typing import Optional
from stockscanner.openai_client import get_chatgpt_client


class DocumentationGenerator:
    """Generate docstrings and documentation using ChatGPT."""

    def __init__(self):
        self.client = get_chatgpt_client()
        self.enabled = os.getenv("CHATGPT_ENABLED", "true").lower() == "true"

    def generate_function_docstring(
        self, function_name: str, code_snippet: str, return_type: str = "str"
    ) -> Optional[str]:
        """
        Generate a docstring for a function.

        Args:
            function_name: Name of the function.
            code_snippet: The function code.
            return_type: Return type description.

        Returns:
            Generated docstring.
        """
        if not self.enabled:
            return None

        try:
            prompt = f"""
Generate a clear Python docstring for this function:

Function Name: {function_name}
Return Type: {return_type}

Code:
{code_snippet}

Use Google-style docstring format with:
- One-line summary
- Detailed description if needed
- Args section
- Returns section
- Raises section if applicable
"""
            return self.client.chat(prompt, max_tokens=500)
        except Exception as e:
            print(f"Docstring Generation Error: {e}")
            return None

    def generate_module_documentation(
        self, module_name: str, module_purpose: str, key_functions: list
    ) -> Optional[str]:
        """
        Generate module-level documentation.

        Args:
            module_name: Name of the module.
            module_purpose: Purpose/description of the module.
            key_functions: List of key function names in the module.

        Returns:
            Generated module documentation.
        """
        if not self.enabled:
            return None

        try:
            functions_str = "\n- ".join(key_functions)
            prompt = f"""
Generate module-level documentation for a Python module:

Module Name: {module_name}
Purpose: {module_purpose}
Key Functions:
- {functions_str}

Format as:
1. Module docstring (1-2 sentences)
2. Key capabilities (bullet points)
3. Usage example
4. Dependencies
"""
            return self.client.chat(prompt, max_tokens=400)
        except Exception as e:
            print(f"Module Documentation Error: {e}")
            return None

    def generate_readme_section(
        self, section_title: str, feature_description: str, details: list
    ) -> Optional[str]:
        """
        Generate a README section for a feature.

        Args:
            section_title: Title of the section.
            feature_description: Brief feature description.
            details: List of specific details/points to include.

        Returns:
            Generated README section.
        """
        if not self.enabled:
            return None

        try:
            details_str = "\n- ".join(details)
            prompt = f"""
Write a professional README section:

Section: {section_title}
Feature: {feature_description}
Key Points:
- {details_str}

Format as:
1. Clear heading
2. 1-2 sentence introduction
3. Feature list or steps
4. Code example if relevant

Make it beginner-friendly and actionable.
"""
            return self.client.chat(prompt, max_tokens=400)
        except Exception as e:
            print(f"README Section Error: {e}")
            return None

    def generate_changelog_entry(
        self, version: str, changes: list, improvements: list = None, fixes: list = None
    ) -> Optional[str]:
        """
        Generate a changelog entry for a release.

        Args:
            version: Version number.
            changes: List of new features/changes.
            improvements: List of improvements.
            fixes: List of bug fixes.

        Returns:
            Generated changelog entry.
        """
        if not self.enabled:
            return None

        try:
            prompt = f"Generate a changelog entry for version {version}:\n\n"
            prompt += "Added:\n- " + "\n- ".join(changes) + "\n\n"
            if improvements:
                prompt += "Improved:\n- " + "\n- ".join(improvements) + "\n\n"
            if fixes:
                prompt += "Fixed:\n- " + "\n- ".join(fixes) + "\n\n"
            prompt += "Keep it concise and professional."
            return self.client.chat(prompt, max_tokens=300)
        except Exception as e:
            print(f"Changelog Generation Error: {e}")
            return None
