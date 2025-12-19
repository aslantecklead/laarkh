# Linguada - YouTube Subtitles Generator

FastAPI-based service for generating subtitles for YouTube videos using Whisper ASR.

---

## Whisper dependency note (important)

### Current state

The project uses **`openai-whisper` version `20250625`**, which is already installed and verified to work:

```bash
python -c "import whisper; print(whisper.__version__)"
# -> 20250625
```

This version is compatible with the current Python environment and works with **modern `triton` (3.x)**.

---

### What went wrong earlier

An attempt was made to install an older version:

```text
openai-whisper==20231106
```

That version has a **hard dependency**:

```text
triton == 2.0.0
```

However:

* `triton==2.0.0` **does not provide wheels** for modern Python versions (e.g. Python ≥ 3.12)
* As a result, `pip` fails with:

  ```
  No matching distribution found for triton==2.0.0
  ```

This caused an artificial dependency conflict.

---

### Correct conclusion

* There is **no need** to install `openai-whisper==20231106`
* The currently installed `openai-whisper==20250625`:

  * imports correctly
  * is compatible with the environment
  * should be used going forward

---

### Rules for this project

* **Do NOT pin** `openai-whisper==20231106`
* Use the installed **`openai-whisper >= 20250625`**
* If an alternative ASR engine is required, install it **separately** (e.g. `faster-whisper`) without downgrading Whisper

---

### Optional

If someone really needs `openai-whisper==20231106`, it must be done in a **separate environment** using **Python 3.10–3.11**, not in the current setup.

---

If хочешь, следующим шагом могу:

* вписать это в твой существующий README (с нужным заголовком),
* или оформить отдельный `docs/whisper.md`,
* или добавить краткий комментарий прямо в код и `requirements.txt`.
