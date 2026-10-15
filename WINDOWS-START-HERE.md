# Run ZanDop on your Windows computer

## Install and open

1. Install **Python 3.12**. The official [Python Install Manager](https://www.python.org/downloads/windows/) can install it using `py install 3.12` in Terminal. Skip this if Python 3.12 is already installed.
2. Download the updated repository ZIP and choose **Extract All**. Keep the entire extracted folder, for example in `Documents\ZanDop`. Do not launch files inside the ZIP preview.
3. Double-click **Start ZanDop Workspace.bat** for your real agency. It installs dependencies the first time and opens the local dashboard. Keep the command window open.
4. To try fictional clients instead, double-click **Start ZanDop.bat**. Demo data and real client data are separate.

No hosting account, Docker, Stripe account or paid AI subscription is needed. The software is open source under the MIT license. Payoneer and optional external services can still charge their own fees.

## Connect Gmail on this computer

1. In Gmail, create a label named **ZanDop**. Under Gmail's label settings, enable **Show in IMAP** for that label.
2. Set up Gmail filters so current and future client messages receive that label. Do not route newsletters or unrelated personal messages to it.
3. Enable **2-Step Verification** in your Google account and create a **Google app password**. Some managed accounts do not allow app passwords; the app currently needs this authentication method.
4. In ZanDop → **Local setup**, enter your Gmail address, label and app password. Never send your password in chat. Windows encrypts it for your user account.
5. Click **Save Gmail settings**, then **Test connection**. This checks IMAP/SMTP login without sending an email. It establishes a starting point; existing old mail is not automatically answered.
6. Click **Enable automatic replies**. New client messages arriving in the label are checked every 60 seconds. Watch **Client inbox** for conversations, delivery issues and owner decisions.

Your **personal Gmail** handles both reviewed first emails and client conversations. No Instantly, Smartlead or extra domain is needed. Replies from prospects contacted through ZanDop are also read from INBOX automatically. Other personal email bodies are not imported.

## Start personal outreach

1. Install [Ollama for Windows](https://ollama.com/download/windows). In Terminal run `ollama pull qwen2.5:7b` (or choose a suitable installed model for your PC). Keep Ollama running. The model is free to download; it requires several GB of disk space and enough memory.
2. In **Local setup**, save the installed model name, for example `qwen2.5:7b`.
3. Open **Lead finder**. Choose a business niche and location. Set your daily first-email limit, normally 8–10 and never above 12.
4. Use the Google Search/Maps links to identify suitable businesses. Paste up to twelve website URLs into **Inspect public websites**. The app finds published contacts; missing contacts require manual review. CSV imports and optional public directory feeds also work.
5. With automation and a local model enabled, the agent prepares one prospect per cycle. You can also click **Research & draft** for a prospect. Check the business contact, the concrete observation and the individual email. Click **Allow this first email** when it is ready.
6. Click **Enable personal Gmail outreach**. With automatic replies also enabled, the next cycle sends reviewed emails within the daily limit. No financial content is allowed in these first emails.
7. A permanent bounce or uncertain send pauses new outreach. Check Gmail and resolve uncertain sends in **Client inbox** before resuming. Opted-out or bounced recipients remain suppressed.

Aim for **8–12 qualified prospects per day and two new projects per week**, each starting at **$500 USD**. Accepted quotes reserve project slots; new outreach waits when two weekly starts or two active projects are filled. These limits do not guarantee sales. Existing client replies continue while new outreach is disabled.

Free discovery depends on your selected sites and public feeds. ZanDop does not scrape Google results, bypass directory login pages, or invent business contacts.

## Run a project

1. An incoming inquiry creates a client record and gets a tailored questionnaire. You can also add an existing client and check that they expect contact.
2. The agent records their answers. Open the client → **Edit quote · $500+**. Enter your own scope and price, starting at $500 USD.
3. Review the quote email and PDF in **Approvals**. Approve it to send. The client confirms the specific quote reference by email before the project advances.
4. The agent prepares the welcome guide, project plan and delivery starter. Routine updates send automatically; scope changes and financial/legal requests appear for your review.
5. Review quality and approve final delivery. For content drafting, optionally install Ollama and select an installed local model in **Local setup**.
6. In your Payoneer account, create a payment request for the exact approved amount. Open the client → **Payoneer link**, paste that request's official link, then approve its outgoing message when Finance requests review.
7. When paid, inspect your Payoneer dashboard yourself. Click **Verify Payoneer payment**, enter the matching amount and transaction reference, and confirm you checked it. A client email claiming payment is not sufficient.

The owner hosts video calls and adds calendar events/video links. Email-only discovery works without a video call or calendar subscription. The agent handles common email conversations, not WhatsApp or social DMs. Complex requests may still need your answer. Generated sites are starters requiring platform integration and final review, not automatically published production sites.

## Keep it running

- Keep the server command window open, the computer awake and internet connected. The reply target is five minutes, not a delivery guarantee.
- Optionally double-click **Enable Windows Auto-start.bat**. It adds a shortcut for your Windows sign-in. Keep the extracted folder in the same location afterward.
- Use **Disable Windows Auto-start.bat** to remove that shortcut.
- Press **Ctrl+C** in the server window to stop. Restart with the same launcher; saved clients and documents remain.
- Real data lives in `%LOCALAPPDATA%\ZanDop\workspace`; demo data is in `%LOCALAPPDATA%\ZanDop\demo`. Back up the complete folder while the app is stopped. Reconnect Gmail if moving to a different Windows account/computer.

## Troubleshooting

- **No browser opens:** open `Open ZanDop.html` in the workspace data folder, or launch the workspace again. Do not bookmark the temporary browser port.
- **Python 3.12 is required:** install that version and restart the launcher.
- **Gmail login fails:** use an app password, not your ordinary Google password; check the selected label is visible through IMAP and your account permits this access.
- **Message status is uncertain:** inspect Gmail Sent first, then use **Client inbox → Resolve send status**. Do not blindly retry.
- **A financial request is waiting:** open **Approvals**; the agent will not bypass your decision.
- **Windows sleeps or goes offline:** processing stops and catches up after restart/reconnection. Configure Windows power settings to suit your needs.
- **Download/certificate error:** check internet and managed network settings. Do not disable certificate checks.

The application and launcher bootstrap are tested in Linux in the cloud. Windows-specific batch files, DPAPI credential encryption and your real Gmail/Payoneer account must still be checked on your own Windows PC.
