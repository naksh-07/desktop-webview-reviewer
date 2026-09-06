"""
Standalone CLI Entrypoint for Antigravity Lifecycle Hooks.

Used by Antigravity's hooks.json to execute hook handlers:
    "command": "python scripts/antigravity_hook.py PreToolUse"

Reads context JSON from stdin, translates and sanitizes it via AntigravityHookAdapter,
ingests it into AntigravityCorrelationBridge, and prints compliant response JSON to stdout.
Guarantees zero-failure exit code 0 to keep the agent loop uninterrupted.
"""

import sys
from runtime.experience.antigravity import AntigravityCorrelationBridge, AntigravityHookAdapter


def main() -> int:
    hook_name = sys.argv[1] if len(sys.argv) > 1 else "PreToolUse"
    adapter = AntigravityHookAdapter()
    bridge = AntigravityCorrelationBridge.get_default_bridge()
    return adapter.execute_cli_hook(hook_name, in_stream=sys.stdin, out_stream=sys.stdout, bridge=bridge)


if __name__ == "__main__":
    sys.exit(main())
