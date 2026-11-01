---
name: ijob-setup
description: Bootstrap or upgrade the resume-tailor-agent binaries (the open-ATS scorer and the Tectonic LaTeX compiler) on a new machine. Use when setting up the resume engine for the first time, when /ijob-tailor halts reporting a missing tool or tectonic binary, or when the user asks to update the resume engine toolchain.
---

# /ijob-setup — bootstrap engine binaries

Fetches `tool` (the open-ATS scorer) and `tectonic` (LaTeX compiler) into the engine repo. Idempotent — re-running upgrades to newest stable.

## Resolve the engine root

```bash
ENGINE="__ENGINE_PATH__"   # rewritten by install.sh
cd "$ENGINE" || { echo "Engine repo not found at $ENGINE"; exit 1; }
```

`install.sh` rewrites that path at install time. If it still reads `__ENGINE_PATH__`, the skill was copied by hand — resolve it yourself, in this order: `$RESUME_TAILOR_HOME`, then **the directory this `SKILL.md` is being read from** (its repo root is two levels up, and that is always the right answer when you are reading the playbook out of a clone). Never guess a conventional path such as `$HOME/soft/resume-tailor-agent`: on the author's own machine that is the live repo, so a run meant for a test copy writes into the real corpus and the real profile. If neither resolves, stop and ask — do not proceed against a guessed root.

**`cd "$ENGINE"` is required, not optional.** Every recipe in `skills/ijob-setup/SKILL.md` is written relative to the current directory (`curl -o tool`, `tar -xzf`, "keep the binary at repo root"). Run from anywhere else and you download a 110 MB binary into the user's working directory, then fail the verify step.

Both binaries are gitignored, so they must be fetched per machine.

## Bootstrap procedure

> Invoked as `/ijob-setup`. Older docs call this `/setup`; the playbook is the same.

Fetches latest stable `tool` (ATS scorer) and `tectonic` (LaTeX compiler) for the current OS+arch. Idempotent — re-running upgrades to newest stable.

No `git`, no `gh`, no package managers required. `curl` only. Windows 10+ ships `curl.exe` + `tar.exe` by default; macOS/Linux ship both.

---

## 1. Detect OS + arch

| OS | Detect | Arch detect |
|---|---|---|
| Windows | `pwsh -c '$env:OS'` → `Windows_NT` | `pwsh -c '$env:PROCESSOR_ARCHITECTURE'` → `AMD64` / `ARM64` |
| macOS | `uname -s` → `Darwin` | `uname -m` → `arm64` / `x86_64` |
| Linux | `uname -s` → `Linux` | `uname -m` → `x86_64` / `aarch64` |

## 2. Resolve latest stable tag

For each repo, call the releases API and pick the first release where `prerelease=false`, `draft=false`, and tag name does NOT match `/alpha|beta|rc/i`.

```
curl -sL -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/<owner>/<repo>/releases
```

Take `.[0]` after filtering. Use the resulting `tag_name`.

Repos + extra filters:
- `NoahMustafa/open-ATS` — no extra filter.
- `tectonic-typesetting/tectonic` — **must also filter `tag_name.startswith("tectonic@")`**. The repo publishes sub-crate releases under the same Releases page (e.g., `tectonic_xetex_layout@0.3.3`, `tectonic_bridge_core@…`) — those are first chronologically but ship no usable binaries. Only `tectonic@X.Y.Z` tags have the compiler asset.

## 3. Asset selection

### `tool` (open-ATS)

| Platform | Asset | Action |
|---|---|---|
| Windows x86_64 | `tool-windows.exe` | rename → `./tool.exe` |
| Windows arm64 | — | **halt:** not shipped; ask user to build from source: `https://github.com/NoahMustafa/open-ATS` |
| macOS arm64 | `tool-macos-arm64` | rename → `./tool`; `chmod +x ./tool` |
| macOS x86_64 (Intel) | — | **halt:** not shipped; build from source |
| Linux x86_64 | `tool-linux-x86_64` | rename → `./tool`; `chmod +x ./tool` |
| Linux arm64 | `tool-linux-arm64` | rename → `./tool`; `chmod +x ./tool` |

### `tectonic`

Asset name pattern (substitute `<VER>` with tag minus `tectonic@` prefix, e.g., `0.16.9`):

| Platform | Asset |
|---|---|
| Windows x86_64 | `tectonic-<VER>-x86_64-pc-windows-msvc.zip` |
| Windows arm64 | **halt:** not shipped |
| macOS arm64 | `tectonic-<VER>-aarch64-apple-darwin.tar.gz` |
| macOS x86_64 | `tectonic-<VER>-x86_64-apple-darwin.tar.gz` |
| Linux x86_64 | `tectonic-<VER>-x86_64-unknown-linux-musl.tar.gz` (static, prefer over `-gnu`) |
| Linux arm64 | `tectonic-<VER>-aarch64-unknown-linux-musl.tar.gz` |

## 4. Download + extract

Download URL pattern:
```
https://github.com/<owner>/<repo>/releases/download/<tag_name>/<asset>
```

Use `curl -fL -o <dest> <url>` (`-f` fails on HTTP errors, `-L` follows redirects).

Extract:
- **Windows `.zip`** → `pwsh -c "Expand-Archive -Path file.zip -DestinationPath . -Force"`. (Windows' native `tar.exe` does handle zip, but agents on Windows often run inside Git Bash where `tar` is GNU tar and does NOT handle zip — use PowerShell to be unambiguous.)
- **Unix `.tar.gz`** → `tar -xzf file.tar.gz`.

After extract, keep only the binary at repo root:
- Windows: `./tectonic.exe`
- Unix: `./tectonic` (then `chmod +x ./tectonic`).

Delete the downloaded archive.

## 4a. Per-OS shell recipe

Pick exactly one block based on the §1 (Detect OS + arch) result. Substitute `<TOOL_TAG>` (e.g., `v0.2.0`), `<TECTONIC_TAG>` (e.g., `tectonic@0.16.9`), `<TECTONIC_VER>` (e.g., `0.16.9`) from §2 (Resolve latest stable tag). The two unnumbered sections above are preamble; §1–§7 are the procedure.

### Windows x86_64 (run from repo root, any shell — examples in pwsh)

```pwsh
curl.exe -fL -o tool.exe "https://github.com/NoahMustafa/open-ATS/releases/download/<TOOL_TAG>/tool-windows.exe"
curl.exe -fL -o tectonic.zip "https://github.com/tectonic-typesetting/tectonic/releases/download/<TECTONIC_TAG>/tectonic-<TECTONIC_VER>-x86_64-pc-windows-msvc.zip"
Expand-Archive -Path tectonic.zip -DestinationPath . -Force
Remove-Item tectonic.zip
```

### macOS arm64 (Apple Silicon)

```bash
curl -fL -o tool "https://github.com/NoahMustafa/open-ATS/releases/download/<TOOL_TAG>/tool-macos-arm64"
chmod +x tool
curl -fL -o tectonic.tar.gz "https://github.com/tectonic-typesetting/tectonic/releases/download/<TECTONIC_TAG>/tectonic-<TECTONIC_VER>-aarch64-apple-darwin.tar.gz"
tar -xzf tectonic.tar.gz
chmod +x tectonic
rm tectonic.tar.gz
```

### Linux x86_64

```bash
curl -fL -o tool "https://github.com/NoahMustafa/open-ATS/releases/download/<TOOL_TAG>/tool-linux-x86_64"
chmod +x tool
curl -fL -o tectonic.tar.gz "https://github.com/tectonic-typesetting/tectonic/releases/download/<TECTONIC_TAG>/tectonic-<TECTONIC_VER>-x86_64-unknown-linux-musl.tar.gz"
tar -xzf tectonic.tar.gz
chmod +x tectonic
rm tectonic.tar.gz
```

### Linux arm64 (aarch64)

```bash
curl -fL -o tool "https://github.com/NoahMustafa/open-ATS/releases/download/<TOOL_TAG>/tool-linux-arm64"
chmod +x tool
curl -fL -o tectonic.tar.gz "https://github.com/tectonic-typesetting/tectonic/releases/download/<TECTONIC_TAG>/tectonic-<TECTONIC_VER>-aarch64-unknown-linux-musl.tar.gz"
tar -xzf tectonic.tar.gz
chmod +x tectonic
rm tectonic.tar.gz
```

### Windows arm64

**Halt.** Neither `tool` nor `tectonic` ships a Windows arm64 binary. Print:
```
Windows arm64 not supported.
Build tool from source: https://github.com/NoahMustafa/open-ATS
Build tectonic from source: https://github.com/tectonic-typesetting/tectonic
```

### macOS x86_64 (Intel)

**Halt.** `tool` does not ship an Intel build. (Tectonic does, but the engine needs both.) Print:
```
macOS Intel not supported by open-ATS v0.2.x.
Build tool from source: https://github.com/NoahMustafa/open-ATS
Or run Apple's Rosetta-emulated arm64 build (not recommended).
```

### Notes on tar across shells

- Recipes above assume macOS/Linux use system `tar` (GNU on Linux, BSD on macOS — both handle `.tar.gz`).
- On Windows, **do not** use Git Bash's `tar` for `.zip` (it is GNU tar, zip not supported). Use `Expand-Archive` as shown.
- Windows' own `tar.exe` (System32, bsdtar) does handle zip — but PATH-shadowing in Git Bash makes it unreliable to assume. Stick to `Expand-Archive`.

## 5. Verify

Use the platform-specific binary names:

```bash
# macOS and Linux
"$ENGINE/tool" --version
"$ENGINE/tectonic" --version
```

```pwsh
# Windows, from the repo root ($ENGINE is a bash variable; pwsh never sees it)
& ./tool.exe --version
& ./tectonic.exe --version
```

Both must print a version string and exit 0. On failure, halt, report which binary failed, and delete only the broken binary.

## 6. Gitignore

Append (idempotent — check first):
```
tool
tool.exe
tectonic
tectonic.exe
```

## 7. Report

Print a short table:
```
tool      v0.2.0   ./tool.exe   OK
tectonic  0.16.9   ./tectonic.exe   OK
```

---

## Re-run behavior

`/ijob-setup` always queries latest stable. If a newer tag exists than the local binary's `--version`, re-download. Otherwise no-op with "already up to date".

## Failure modes

- **Network down / GitHub unreachable** → halt with clear message; do not silently leave half-downloaded files.
- **Unsupported OS+arch** → halt with build-from-source link; never silently install a wrong-arch binary.
- **`curl` not on PATH** (extremely rare on Windows 10+, macOS, Linux) → halt with one-line install instructions per OS.
