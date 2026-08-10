# Building the real Mac `.app` via GitHub

A macOS `.app` can only be compiled **on** macOS — no tool cross-compiles one from
Windows. GitHub gives you Mac machines for free, so you push the code once and it builds
Windows, Mac (Apple Silicon) and Mac (Intel) for you.

Cost: **free** for public repositories. Time: about 15 minutes, mostly waiting.

Everything on this machine is already prepared — the code is committed, the build recipe
is written, and I checked that every package the Mac build needs has a ready-made
macOS build for both Apple Silicon and Intel. The only thing left is the part that needs
your GitHub account.

---

## Step 1 — Make a GitHub account (skip if you have one)

Go to <https://github.com/signup>. Free. Any username.

## Step 2 — Create an empty repository

1. Go to <https://github.com/new>.
2. **Repository name:** `sheet-auto-fill`
3. Leave it **Public** (free Actions minutes for public repos).
4. **Do not** tick "Add a README", ".gitignore" or "license" — this folder already has them.
5. Click **Create repository**.

Leave that page open; it shows the address you need next.

## Step 3 — Send the code up

Open **PowerShell** and run these, replacing `YOUR-USERNAME`:

```bash
cd "D:\SHEET auto FILL"
git remote add origin https://github.com/YOUR-USERNAME/sheet-auto-fill.git
git push -u origin main
```

The first push opens a browser window to sign in to GitHub. Approve it.

> **Before pushing, a sanity check:** run `git status` — it must not list
> `service_account.json`, `connection.json`, or anything in `samples/*.pdf`. Those are
> your Google key and real customer work orders; they are excluded on purpose and should
> never appear. If any of them shows up, stop and tell me.

## Step 4 — Build the apps

1. On your repository page click the **Actions** tab.
2. In the left sidebar click **Build apps**.
3. Click **Run workflow** (right-hand side) → **Run workflow**.

Four jobs run in parallel. Each one installs the packages, builds the app, and runs the
app's own self-test inside the finished bundle — so a broken build fails loudly instead of
being handed to you.

Wait for the green ticks (~15 min).

## Step 5 — Download

Open the finished run and scroll to **Artifacts** at the bottom:

| Artifact | What it is |
|---|---|
| `SHEET-auto-FILL-macOS-AppleSilicon.zip` | **the real .app** for M1/M2/M3/M4 Macs |
| `SHEET-auto-FILL-macOS-Intel.zip` | the real .app for older Intel Macs |
| `SHEET-auto-FILL-Windows.zip` | the Windows .exe |
| `SHEET-auto-FILL-macOS-Installer.zip` | the self-installing file (the simpler route) |

Not sure which Mac you have?  → **About This Mac**. If the chip line says "Apple M…",
take the Apple Silicon one.

## Step 6 — Install it on the Mac

1. Unzip the file you downloaded.
2. Drag **SHEET auto FILL.app** into your **Applications** folder.
3. **First launch only:** right-click the app → **Open** → **Open** again.
   macOS shows a warning because the app isn't signed with a paid Apple certificate.
   Doing it this way once tells macOS you trust it; after that a normal double-click works.

Your settings and Google key live in `~/Library/Application Support/SHEET auto FILL/`.

---

## Optional — publish a proper Release page

Tagging produces a permanent download page instead of build artifacts that expire:

```bash
git tag v1.0.0
git push origin v1.0.0
```

The same workflow runs and attaches all four zips to a GitHub **Release**.

## Updating later

After any code change:

```bash
cd "D:\SHEET auto FILL"
git add .
git commit -m "what changed"
git push
```

Then run the workflow again for fresh apps on both platforms.

---

## About the security warning

The Mac app is **ad-hoc signed** (free) but not **notarized**, which needs a paid Apple
Developer account (~$99/year). The only practical effect is the one-time right-click →
Open. Nothing about the app is unsafe: it's the same code as the Windows version and runs
entirely on your machine.

If you'd rather never see that warning, the self-installing file route avoids it, because
files it creates on the Mac are not quarantined.

## If a build fails

Click the failed job to see its log. The most likely causes, and what they look like:

| In the log | Meaning |
|---|---|
| `No matching distribution found` | A package has no macOS build for that Python version. Tell me which package — the fix is a version pin. |
| `SELFTEST FAIL: …` | The app built but something is missing inside the bundle. The message names it. |
| `codesign` error | The ad-hoc signing step failed on the runner; usually transient — re-run the job. |

Send me the failing lines and I'll fix them.
