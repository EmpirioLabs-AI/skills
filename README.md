<p align="center">
  <img src="assets/icon.png" width="96" height="96" alt="EmpirioLabs AI">
</p>

# EmpirioLabs AI agent skills

Agent skills for [EmpirioLabs AI](https://empiriolabs.ai). They let an AI agent generate and edit images, make videos, turn text into speech, transcribe audio and video, and choose the right model and price from the live catalog. Each skill is a folder with a `SKILL.md` and a small Python script that uses only the standard library, so the same files work in OpenClaw, Hermes Agent, Claude Code, Codex, Cursor, and any client that supports [Agent Skills](https://agentskills.io).

EmpirioLabs AI is a specialized AI inference and integration provider. It self-hosts open-source models on GPU infrastructure it manages, runs optimized endpoints for proprietary models, and offers on-demand GPU Cloud instances and hosted AI agents. The model catalog spans text, image, video, audio, transcription, embedding, reranking, research, and 3D models.

## Skills

| Skill | What it does | API key |
|---|---|---|
| [empiriolabs-image](skills/empiriolabs-image/SKILL.md) | Generate images from a prompt, or edit and combine existing images | Required |
| [empiriolabs-video](skills/empiriolabs-video/SKILL.md) | Make a video from a prompt or a start image, wait for the job, and download the MP4 | Required |
| [empiriolabs-speech](skills/empiriolabs-speech/SKILL.md) | Turn text into speech as MP3, WAV, and other formats | Required |
| [empiriolabs-transcribe](skills/empiriolabs-transcribe/SKILL.md) | Turn an audio or video file (https URL or local file) into text | Required |
| [empiriolabs-models](skills/empiriolabs-models/SKILL.md) | Find a model for a task with its price, parameters, and limits | Not needed |

When no model is named, each script picks a featured model from the live catalog, so new models are available as soon as they launch. Pass `--model` to choose one yourself.

## Requirements

- Python 3.8 or later (`python3`, or `python` on Windows). There is nothing to install.
- For the media skills, an EmpirioLabs AI API key in the `EMPIRIOLABS_API_KEY` environment variable. Create a key at https://platform.empiriolabs.ai/dashboard/api-keys (keys start with `sk-empiriolabs-`).

```bash
export EMPIRIOLABS_API_KEY="sk-empiriolabs-..."      # macOS and Linux
```

```powershell
setx EMPIRIOLABS_API_KEY "sk-empiriolabs-..."        # Windows, then open a new terminal
```

Requests are billed to your EmpirioLabs AI account at each model's listed price (https://empiriolabs.ai/pricing). Every media script has `--list-models` to compare prices first.

## Install

### Any agent, with the skills CLI

The [skills CLI](https://skills.sh) installs into Claude Code, Codex, Cursor, OpenClaw, Hermes Agent, and dozens of other agents:

```bash
npx skills add EmpirioLabs-AI/skills                                    # pick skills and agents
npx skills add EmpirioLabs-AI/skills --skill empiriolabs-image -a claude-code -g
npx skills add EmpirioLabs-AI/skills --all                              # every skill, every detected agent
```

### OpenClaw (ClawHub)

```bash
openclaw skills install @empiriolabs/empiriolabs-image
openclaw skills install @empiriolabs/empiriolabs-models
```

With the ClawHub CLI instead: `clawhub install @empiriolabs/empiriolabs-image`. The media skills are ready once `EMPIRIOLABS_API_KEY` is set in the environment OpenClaw runs in, or stored for a skill in `~/.openclaw/openclaw.json`:

```json5
{
  skills: {
    entries: {
      "empiriolabs-image": { apiKey: "sk-empiriolabs-..." },
    },
  },
}
```

### Hermes Agent

```bash
hermes skills install EmpirioLabs-AI/skills/skills/empiriolabs-image
hermes skills install well-known:https://empiriolabs.ai/.well-known/skills/empiriolabs-image
hermes skills install clawhub/@empiriolabs/empiriolabs-image
```

Any of the three sources works. To browse every skill in this repository, run `hermes skills tap add EmpirioLabs-AI/skills`, then `hermes skills search empiriolabs`. Hermes asks for `EMPIRIOLABS_API_KEY` the first time a media skill loads.

### Claude Code

```text
/plugin marketplace add EmpirioLabs-AI/skills
/plugin install empiriolabs@empiriolabs-ai
```

From a terminal, the same steps are `claude plugin marketplace add EmpirioLabs-AI/skills` and `claude plugin install empiriolabs@empiriolabs-ai`. Claude uses a skill when a task matches it, and you can call one directly, for example `/empiriolabs:empiriolabs-image`.

### Codex

```bash
codex plugin marketplace add EmpirioLabs-AI/skills
codex plugin add empiriolabs@empiriolabs-ai
```

You can also open `/plugins` in Codex and install EmpirioLabs AI from the marketplace list. To use the skills without the plugin, copy the folders in `skills/` into `~/.agents/skills/`.

### Cursor

```bash
npx skills add EmpirioLabs-AI/skills -a cursor
```

The repository is also a Cursor plugin (`.cursor-plugin/plugin.json`), so a team marketplace can import it from GitHub.

### Any other Agent Skills client

Copy the folders in `skills/` into the client's skills directory, for example `.agents/skills/` in a project or `~/.agents/skills/` for every project. Each folder is self-contained.

## Examples

Agents run these for you once a skill is installed. You can also run them yourself from the repository root:

```bash
python3 skills/empiriolabs-models/scripts/models.py --category image
python3 skills/empiriolabs-image/scripts/image.py "a lighthouse at dawn, watercolor" --out ./images/lighthouse.webp
python3 skills/empiriolabs-video/scripts/video.py "a paper boat drifting down a rainy street" --out ./clips/boat.mp4
python3 skills/empiriolabs-speech/scripts/speech.py "Welcome to the weekly update." --out ./audio/welcome.mp3
python3 skills/empiriolabs-transcribe/scripts/transcribe.py https://example.com/interview.mp3 --out ./interview.txt
```

Each script has `--help`, prints a JSON summary on stdout, and prints progress on stderr.

## How the scripts behave

- The API key is read from `EMPIRIOLABS_API_KEY` and sent only to `api.empiriolabs.ai`. The scripts never print it or write it to disk.
- Results are saved where `--out` points. Existing files are kept and a numeric suffix is added, unless you pass `--overwrite`.
- Video and transcription jobs can be started with `--no-wait` and picked up later with `--job-id`.
- Exit codes: `0` success, `1` the request failed, `2` invalid arguments, `3` the job was still running when the wait limit ran out.

## Remote MCP server

The same models, plus GPU Cloud, hosted agents, batch jobs, and web search, are available as tools through the EmpirioLabs AI MCP server at `https://mcp.empiriolabs.ai/mcp`. Setup for Claude, ChatGPT, Cursor, and other clients: https://docs.empiriolabs.ai/mcp.

## Development

```bash
python -m unittest discover -s tests                 # offline unit tests, no network
python scripts/sync_shared.py                        # copy shared/empiriolabs_api.py into each skill
python scripts/build_well_known.py --out <site>/.well-known/skills
```

`shared/empiriolabs_api.py` is the one copy of the API client to edit; each skill carries an identical copy so it works when installed on its own, and the tests fail if a copy drifts. `scripts/build_well_known.py` writes the `/.well-known/skills/` index and files that Hermes Agent and the skills CLI install from a website. `tests/live_smoke.py` makes real, billed requests when `EMPIRIOLABS_API_KEY` is set.

## Support and license

- Website: https://empiriolabs.ai
- Documentation: https://docs.empiriolabs.ai
- Support: support@empiriolabs.ai

Released under [MIT-0](LICENSE) (MIT No Attribution). Copyright 2026 EmpirioLabs.ai LLC. Skills published on ClawHub are also released under MIT-0.
