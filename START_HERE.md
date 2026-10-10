# Running Q2E on your computer (no programming needed)

Q2E runs on your own computer and opens in your web browser, like a website. Your data stays on your machine.

You install two free programs once, then double-click one file. Allow about 20 minutes the first time; after that it
starts in seconds.

---

## Step 1: Install Python and R (one time)

| Program | Where to get it | Notes |
|---|---|---|
| **Python** | https://www.python.org/downloads/ → click the big yellow **Download Python** button | **Windows:** on the first installer screen, tick **"Add python.exe to PATH"** before clicking *Install Now*. |
| **R** | https://cloud.r-project.org/ → **Download R for Windows → base**, or **Download R for macOS** (pick Apple silicon for M1/M2/M3/M4 Macs, Intel for older Macs) | Accept all the default options. |

You don't need to open either program yourself. Q2E uses them in the background.

## Step 2: Get the Q2E folder

* From GitHub: click the green **Code** button → **Download ZIP**.
* Or use the `q2e-research-copilot.zip` file you were sent.

**Unzip it** (Windows: right-click → *Extract All*; Mac: double-click the zip). Put the folder somewhere easy to find,
such as Documents. Don't run Q2E from inside the zip.

## Step 3: Start Q2E

| Windows | Mac |
|---|---|
| Open the folder and double-click **`Start-Q2E-Windows.bat`**. If a blue *"Windows protected your PC"* box appears, click **More info → Run anyway**. | Open the folder, **right-click** (or Control-click) **`Start-Q2E.command`** and choose **Open**, then **Open** again. You only need to right-click the first time; after that a double-click works. |

A black text window opens.

* **The first time** it installs what it needs. You'll see "installing R statistics packages (this is the slow part)". This takes 5–15 minutes and needs internet. Leave it running.
* Then your browser opens **http://127.0.0.1:8000** with Q2E. If it doesn't open by itself, type that address into Chrome, Edge or Safari.

**Keep the black window open while you use Q2E.** Close it when you're finished.

## Step 4: Try it (5 minutes)

1. Click one of the example questions, or type your own idea, e.g.
   *"Do a research study on the prevalence of functional iron deficiency in US adults."*
2. Under **Data**, choose **Synthetic demo** for a first test (it works offline). Choose **CDC download / local** to use real NHANES data.
3. Click **Design my study →**.
4. **Protocol**: read what the AI agents proposed. Click any text to edit it. Click **Acknowledge** on the yellow items once you've read the assumptions.
5. **Data map**: see which NHANES files and variables will be used.
6. **Analysis plan**: review the model and the sensitivity analyses, apply any reviewer fixes, type your name, tick the box, and click **Approve protocol**. Then click **Run analysis in R →**.
7. **Run & validate**: wait about 10–60 seconds, then review the quality checks.
8. **Results**: see the headline estimate, figures and tables, then click **Manuscript (JAMA Netw Open style)** to open the write-up. **Reproducibility bundle** downloads everything needed to re-run the analysis.
9. **Sign-off**: tick the attestations and sign.

## Using real NHANES data

* **Easiest:** choose **CDC download / local**. Q2E downloads the files it needs from the CDC website the first time and keeps a copy.
* **If you were given NHANES files** (they end in `.xpt`, e.g. `P_DEMO.xpt`): copy them into the folder `data` → `nhanes` inside Q2E, then choose **Local XPT folder**.

## Optional: turn on AI language models or voice

Q2E works fully without any AI keys; the built-in rule-based agents do the drafting. To add a language model or
ElevenLabs voice:

1. In the Q2E folder, make a copy of **`.env.example`** and rename the copy to **`.env`**. On Mac, files starting with a dot are hidden; press **Cmd + Shift + .** to show them. On Windows, make sure the name doesn't end up as `.env.txt`.
2. Open `.env` with Notepad (Windows) or TextEdit (Mac) and fill in the key you have. For example:
   * Claude: `Q2E_LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY=...`
   * Azure OpenAI: `Q2E_LLM_PROVIDER=azure_openai` plus the three `AZURE_OPENAI_...` lines
   * Voice: `ELEVENLABS_API_KEY=...`
3. Close the black window and start Q2E again.

## If something goes wrong

| Problem | Fix |
|---|---|
| "Python 3.10 or newer is not installed" | Install Python (Step 1). On Windows, reinstall and tick **Add python.exe to PATH**. |
| "R is not installed" | Install R (Step 1), then start Q2E again. |
| "R package install failed" or "Python install failed" | Check the internet connection (hospital networks sometimes block downloads; try home Wi-Fi or a hotspot for the first run), then start again. |
| The browser says "can't reach this page" | Wait 10 seconds and refresh. Make sure the black window is still open. |
| "Address already in use" | Q2E is already running in another window. Use that one, or close it and start again. |
| Run failed: *NHANES file not found* | Choose **Synthetic demo**, or allow CDC download, or put the `.xpt` files in `data/nhanes`. |
| Mac says the file "can't be opened" | Right-click → **Open** (Step 3). If it still won't start: open the **Terminal** app, type `bash ` (with a space), drag `Start-Q2E.command` into the window, and press Return. |
| Start fresh | Close Q2E, delete the `.venv` folder inside Q2E (Mac: Cmd + Shift + . to see it), and start again. Your projects in `workspace` are kept. |

## Alternative for IT-supported setups: Docker

If your IT team or a colleague uses **Docker Desktop**: open a terminal in the Q2E folder and run
`docker compose up --build`, then visit http://localhost:8000. Docker includes Python and R, so Step 1 isn't needed.
