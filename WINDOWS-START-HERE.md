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

Use a dedicated agency Gmail inbox if possible. This connection handles expected client correspondence. Cold outreach still requires your separate warmed domain and Instantly/Smartlead setup; those optional services may cost money.

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
