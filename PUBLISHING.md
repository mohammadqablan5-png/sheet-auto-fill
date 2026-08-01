# Putting this on GitHub and building the Mac app

The Mac app **cannot be built on a Windows PC** — Apple binaries have to be produced on
macOS. The free way to get one without owning a Mac build setup is GitHub Actions: you
push the code once, and GitHub compiles it on their own Windows and Mac machines.

Cost: **free** for public repositories.

---

## 1. Create the repository

1. Sign in at <https://github.com> (create a free account if needed).
2. Click **+ → New repository**.
3. Name it `sheet-auto-fill`, leave it **Public** (free Actions minutes), and **don't**
   add a README — this folder already has one. Click **Create repository**.

## 2. Push this folder

Install [Git for Windows](https://git-scm.com/download/win) if you don't have it, then in
PowerShell from `D:\SHEET auto FILL`:

```bash
git init
git add .
git commit -m "SHEET auto FILL"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/sheet-auto-fill.git
git push -u origin main
```

Git will ask you to sign in to GitHub the first time.

> **Check before pushing:** `git status` must not list `service_account.json`. It is in
> `.gitignore`, so it should never appear — that file is your private key and must stay
> off GitHub. The `App/` and `dist/` folders are ignored too (they're large build output).

## 3. Build the apps

On GitHub: **Actions** tab → **Build apps** → **Run workflow** → **Run workflow**.

It builds three things in parallel on GitHub's machines (~10–15 minutes):

| Job | Produces |
|---|---|
| Windows | `SHEET-auto-FILL-Windows.zip` |
| macOS Apple Silicon | `SHEET-auto-FILL-macOS-AppleSilicon.zip` |
| macOS Intel | `SHEET-auto-FILL-macOS-Intel.zip` |

Each build runs a **self-test** that loads the app, the OCR engine and the field mapping
inside the packaged bundle — so a broken build fails loudly instead of shipping.

When it finishes, open the run and download the file you need from **Artifacts** at the
bottom.

## 4. (Optional) Publish a proper Release

Tagging creates a permanent download page others can use:

```bash
git tag v1.0.0
git push origin v1.0.0
```

The same workflow runs and attaches all three zips to a GitHub **Release**.

---

## About Mac security warnings

The Mac app is **ad-hoc signed** (free) but not **notarized**, because notarization
requires a paid Apple Developer account (about $99/year). The practical effect is one
extra step the very first time you open it: **right-click → Open → Open**. After that it
launches normally. Nothing about the app is unsafe — it's the same code as the Windows
version, and it runs entirely on your machine.

If you'd rather avoid the warning completely, use Option B in the README (run from
source); files you clone with Git aren't quarantined by macOS at all.

## Updating later

Change the code, then:

```bash
git add .
git commit -m "what changed"
git push
```

Re-run the workflow to get fresh apps for both platforms.
