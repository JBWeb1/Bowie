# Try Bowers on your PC

About 15 minutes. These are the things that can only be tested on a real computer, with a real mic and speakers.

## 1. Install
1. Download the newest **Bowers-Setup** from GitHub: the repo's **Actions** tab, then **Windows app**, then the latest run,
   then **Artifacts**. Unzip it and run `Bowers-Setup-1.0.0.exe`.
2. Windows may say "Windows protected your PC" (the installer isn't code-signed yet): click **More info**, then **Run anyway**.
3. Set your key once. Open PowerShell and run this (it stays on your computer, never in a chat):
   ```powershell
   setx ANTHROPIC_API_KEY "your-key-here"
   ```
   Close PowerShell, then open **Bowers** from the Start menu.

## 2. Check these
| # | Try this | You should see |
|---|----------|----------------|
| 1 | Home: "Build a landing page for a lemonade stand and test it in a browser" | Steps tick by, a live preview, "no console errors" |
| 2 | Hover your message, click the undo arrow | Your files go back |
| 3 | Integrations: **Kokoro voice**, then Install. Settings > Voice > Kokoro > **Hear Bowie** | Bowie talks, with no internet needed after the install |
| 4 | Pick the Aether model, click the mic and say "what's next?" | Bowie answers out loud |
| 5 | Labs > Math Lab: `x^2 - 5x + 6`, choose Plot | A curve with x = 2 and x = 3 marked |
| 6 | Labs > Free Resources: search "password manager" | Bitwarden and friends |
| 7 | Explore > Connect apps: search "jira", click Connect | A browser window to sign in to Atlassian |
| 8 | Bowers Care: Check my computer | Your real memory, disk and uptime |
| 9 | Close Bowers and open it again | Your project and chat are still there |

## 3. Tell me
Anything that's slow, confusing, broken or ugly. A screenshot helps most. And how Bowie's voice sounds to you.
