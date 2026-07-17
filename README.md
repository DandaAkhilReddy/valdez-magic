# 🩺 Valdez Magic

**Scan your gym → get your program → ask Valdez anything.**

Record a video walking through your gym. Valdez identifies every piece of equipment
(vision AI), then builds you a complete weekly workout program — sets, reps, rest,
muscles targeted, exact form cues, and *why each exercise matters for longevity*.
An AI coach named **Valdez** answers any training question, tailored to your gym and plan.

## Features
- 📧 Passwordless email + OTP login
- 🎥 Gym video scan → equipment detection (Claude / Azure OpenAI vision; manual checklist fallback)
- ⚡ Program generator: 3–6 days/week, longevity / strength / fat-loss, 30–60 min sessions
- 🏋️ 35+ exercise database with muscles, form cues, and longevity reasoning
- 🩺 Valdez AI coach (top LLM when configured, built-in expert coach otherwise)
- ☁️ SQLite + optional Azure Blob for gym videos

## Env
| var | purpose |
|---|---|
| SMTP_HOST/PORT/USER/PASS | real OTP emails |
| ANTHROPIC_API_KEY, VALDEZ_MODEL | Valdez brain + vision detection |
| AZURE_OPENAI_ENDPOINT/KEY/DEPLOYMENT | alternative brain on Azure |
| AZURE_STORAGE_CONNECTION_STRING | gym video blob mirror |
| DATA_DIR | persistent dir (default ./data) |

## Run
```bash
pip install -r requirements.txt && uvicorn main:app --reload
```

Built by [Akhil Reddy Danda](https://dandaakhilreddy.com) — not medical advice; train smart.
