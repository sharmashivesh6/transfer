Drag-and-drop file sharing between computers on the same Wi-Fi or network. Works Windows ↔ Windows and Windows ↔ Mac.

## Install (recommended, no security prompts)

**Mac** (Apple Silicon, M1 or newer): open **Terminal**, paste this, press Return:
```
curl -fsSL https://raw.githubusercontent.com/sharmashivesh6/transfer/main/install.sh | sh
```

**Windows**: open **PowerShell** (Start menu → type "PowerShell"), paste this, press Enter, then click **Yes** when asked:
```
irm https://raw.githubusercontent.com/sharmashivesh6/transfer/main/install.ps1 | iex
```
This also adds Transfer to the Start menu and desktop, and allows it through the firewall.

## How to use
1. Open Transfer on both computers. They find each other automatically.
2. Drag files onto the other computer's card, or click the card to choose files.
3. Received files go to **Downloads → Transfer Files**.

## Manual download (instead of the commands above)
- **Windows:** `Transfer.exe`. If you see "Windows protected your PC", click **More info → Run anyway**, and click **Allow access** when the firewall asks.
- **Mac:** `Transfer-mac.zip`. If macOS says it can't verify Transfer, go to **System Settings → Privacy & Security** and click **Open Anyway**.


## Updating
Already have Transfer v1.1 or newer? It tells you when an update is out: click **Update now** and it reopens on the new version.
Older copies don't have the button, so run the install command above once more (or download again).
