"""One synthetic prompt over stdin; plain text on stdout. No agent tools."""
import argparse
import subprocess
import sys
from tempfile import TemporaryDirectory


def invoke(backend: str, model: str, prompt: str) -> str:
    if not model or model.startswith("-") or not prompt.strip():
        raise ValueError("Provide a model name and a non-empty prompt.")
    if backend == "claude":
        argv = ["claude", "-p", "--model", model, "--tools", "", "--output-format", "text"]
    elif backend == "ollama":
        argv = ["ollama", "run", model]
    else:
        raise ValueError("Unknown backend.")
    with TemporaryDirectory() as workdir:
        result = subprocess.run(argv, input=prompt, text=True, capture_output=True,
                                cwd=workdir, check=True, timeout=300)
    return result.stdout.strip()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backend", choices=("claude", "ollama"))
    parser.add_argument("model")
    args = parser.parse_args()
    try:
        print(invoke(args.backend, args.model, sys.stdin.read()))
    except FileNotFoundError:
        parser.exit(1, "Selected CLI is not installed or is not on PATH.\n")
    except subprocess.CalledProcessError as exc:
        parser.exit(1, f"Backend exited with status {exc.returncode}; check the runtime configuration.\n")
    except subprocess.TimeoutExpired:
        parser.exit(1, "Backend timed out.\n")
    except ValueError as exc:
        parser.exit(2, f"{exc}\n")
