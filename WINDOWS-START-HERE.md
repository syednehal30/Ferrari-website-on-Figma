# Run ZanDop on Windows

1. Install **Python 3.12**. The official [Python Install Manager](https://www.python.org/downloads/windows/) can install it with `py install 3.12` in Terminal. Skip this if Python 3.12 is already installed.
2. Extract the entire ZanDop ZIP into a folder such as `Documents\ZanDop`. Do not run files from inside the ZIP preview.
3. Double-click **Start ZanDop.bat**. The first launch needs internet access to install dependencies. Keep the command window open.
4. Your browser opens automatically once the dashboard is ready. If it does not, copy the address printed after **ZanDop is ready** into Edge or Chrome.

No hosting account, Docker, API keys, or payment details are needed. The app runs only on your own computer. This launcher always uses demo mode, ignores `.env`, and removes inherited live-provider configuration from the app process. Illustrative prices are not ZanDop's approved rate card.

## Try a project

Open **CRM**, choose **Monogram**, and advance its next stage. Review the research brief and draft outreach. Simulate a booking to generate the welcome PDF, add call notes for the project plan, and continue through delivery and quality. Approval requests appear in **Approvals**. Simulated invoice payment is available only after approving its demo invoice. **Activity** shows the timestamped record of each action.

All sample businesses are fictional. Emails, bookings, invoices, and payment events are simulated. The PDFs and downloadable delivery scaffolds are real files. The integration adapters are not connected to live providers.

## Stop and restart

Press **Ctrl+C** in the command window to stop, then close it. Double-click the launcher next time. Your CRM, documents, and delivery files remain in `%LOCALAPPDATA%\ZanDop\demo`. The browser address may change each launch, so use the launcher rather than an old browser bookmark. Use one launcher window at a time.

The app installs dependencies in `.venv-local` beside the launcher. It reuses them on subsequent runs. It uses installed Edge or Chrome for delivery quality checks; otherwise it downloads Chromium using Playwright.

## If the window shows an error

- **Python 3.12 is required:** install Python 3.12, then run the launcher again.
- **Download or certificate error:** check your internet or managed network settings. Do not disable certificate verification.
- **Access denied:** extract into a folder you own, such as Documents, instead of Program Files.
- **Browser did not open:** use the address in the command window. If no ready message appeared, copy the error text for troubleshooting.

The Python bootstrap and application workflow were tested in Linux. The `.bat` launcher is provided for Windows; it has not been executed on a Windows machine in this cloud environment.
