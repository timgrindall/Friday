"""
Friday Setup Script
Installs dependencies and configures API keys for first-time users.

Usage:
    python setup.py

Assumes Python, Ollama, and the Mistral model are already installed.
See README.md for instructions on those prerequisites.
"""

import subprocess
import sys
import os

# ── Colors ────────────────────────────────────────────────────────

def _enable_windows_ansi():
    if sys.platform == 'win32':
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)

_enable_windows_ansi()

class C:
    GREEN   = "\033[92m"
    CYAN    = "\033[96m"
    YELLOW  = "\033[93m"
    RESET   = "\033[0m"

# ── Helpers ───────────────────────────────────────────────────────

def header(text):
    print(f"\n{C.GREEN}" + "="*50)
    print(f"  {text}")
    print("="*50 + f"{C.RESET}")

def step(text):
    print(f"\n  {C.CYAN}→ {text}{C.RESET}")

def success(text):
    print(f"  {C.GREEN}✓ {text}{C.RESET}")

def warn(text):
    print(f"  {C.YELLOW}! {text}{C.RESET}")

def ask(prompt, secret=False):
    if secret:
        import getpass
        return getpass.getpass(f"    {prompt}: ").strip()
    return input(f"    {prompt}: ").strip()

def confirm(prompt):
    answer = input(f"    {prompt} [y/N]: ").strip().lower()
    return answer in ("y", "yes")

# ── Steps ─────────────────────────────────────────────────────────

def check_ollama():
    header("Checking Ollama")
    step("Looking for Ollama...")

    result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
    if result.returncode != 0:
        warn("Ollama doesn't appear to be running or installed.")
        warn("Install it from https://ollama.ai and run: ollama pull mistral")
        warn("Then re-run this script.")
        if not confirm("Continue anyway?"):
            sys.exit(1)
        return

    if "mistral" in result.stdout.lower():
        success("Ollama is running and Mistral model is available.")
    else:
        warn("Ollama is running but the Mistral model wasn't found.")
        warn("Run: ollama pull mistral")
        if not confirm("Continue anyway?"):
            sys.exit(1)


def install_dependencies():
    header("Installing Dependencies")
    step("Installing packages from requirements.txt...")

    if not os.path.exists("requirements.txt"):
        warn("requirements.txt not found. Are you running this from the Friday folder?")
        sys.exit(1)

    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
        capture_output=False
    )

    if result.returncode == 0:
        success("All dependencies installed.")
    else:
        warn("Some packages failed to install. Check the output above.")
        if not confirm("Continue anyway?"):
            sys.exit(1)


def configure_env():
    header("API Key Configuration")
    print(f"""
  Friday works without any API keys, but optional services
  improve the experience:

    {C.CYAN}ElevenLabs{C.RESET}  — High-quality voice output (free tier available)
                  https://elevenlabs.io

    {C.CYAN}SerpAPI{C.RESET}     — Real-time web search (free tier available)
                  https://serpapi.com

  Keys are saved to a local .env file and never leave your machine.
    """)

    env_lines = []
    env_exists = os.path.exists(".env")

    if env_exists:
        warn(".env file already exists.")
        if not confirm("Overwrite it?"):
            success("Keeping existing .env file.")
            return

    # ElevenLabs
    if confirm("Do you have an ElevenLabs API key?"):
        key = ask("ElevenLabs API key", secret=True)
        if key:
            env_lines.append(f"ELEVENLABS_API_KEY={key}")
            voice_id = ask("ElevenLabs Voice ID (press Enter for default 'George')")
            env_lines.append(f"ELEVENLABS_VOICE_ID={voice_id if voice_id else 'JBFqnCBsd6RMkjVDRZzb'}")
            success("ElevenLabs configured.")
        else:
            warn("No key entered, skipping ElevenLabs.")
    else:
        warn("Skipping ElevenLabs — Friday will use local TTS (Piper or pyttsx3).")

    print()

    # SerpAPI
    if confirm("Do you have a SerpAPI key?"):
        key = ask("SerpAPI key", secret=True)
        if key:
            env_lines.append(f"SERPAPI_KEY={key}")
            success("SerpAPI configured.")
        else:
            warn("No key entered, skipping SerpAPI.")
    else:
        warn("Skipping SerpAPI — Friday will rely on Mistral's training data for answers.")

    # Write .env
    if env_lines:
        with open(".env", "w") as f:
            f.write("\n".join(env_lines) + "\n")
        success(".env file written.")
    else:
        success("No API keys configured — Friday will run fully locally.")


def done():
    header("Setup Complete")
    print(f"""
  Friday is ready. Start it with:

      {C.GREEN}python friday.py{C.RESET}

  Optional flags:

      {C.CYAN}--dev{C.RESET}          Verbose logging + text input mode
      {C.CYAN}--local-tts{C.RESET}    Force local TTS, skip ElevenLabs
      {C.CYAN}--no-search{C.RESET}    Disable web search
      {C.CYAN}--voice{C.RESET}        Play audio responses in text mode

  See README.md for full documentation.
    """)


# ── Main ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"""
{C.GREEN}  ███████╗██████╗ ██╗██████╗  █████╗ ██╗   ██╗
  ██╔════╝██╔══██╗██║██╔══██╗██╔══██╗╚██╗ ██╔╝
  █████╗  ██████╔╝██║██║  ██║███████║ ╚████╔╝ 
  ██╔══╝  ██╔══██╗██║██║  ██║██╔══██║  ╚██╔╝  
  ██║     ██║  ██║██║██████╔╝██║  ██║   ██║   
  ╚═╝     ╚═╝  ╚═╝╚═╝╚═════╝ ╚═╝  ╚═╝   ╚═╝  {C.RESET}
    """)
    print(f"  {C.GREEN}First-time setup{C.RESET} — Friday v0.68")
    print(f"  {'─'*40}")
    print(f"  Assumes: Python, Ollama, and Mistral are already installed.")
    print(f"  See README.md if you haven't set those up yet.\n")

    try:
        check_ollama()
        install_dependencies()
        configure_env()
        done()
    except KeyboardInterrupt:
        print(f"\n\n  {C.YELLOW}Setup cancelled.{C.RESET}")
        sys.exit(0)
