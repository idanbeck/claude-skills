# Twilio SMS Skill - Text Message Bridge for Claude Code

Send and receive SMS/MMS messages through Twilio, with auto-response via Claude Code.

## Setup

### 1. Get Twilio Credentials

1. Sign up at https://www.twilio.com/
2. Get a phone number (or use trial number)
3. Find your Account SID and Auth Token in the console

### 2. Configure the Skill

Create `config.json`:

```json
{
  "account_sid": "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "auth_token": "your_auth_token_here",
  "phone_number": "+1234567890",
  "allowed_numbers": ["+1987654321"]
}
```

- `account_sid`: Your Twilio Account SID
- `auth_token`: Your Twilio Auth Token
- `phone_number`: Your Twilio phone number (the one that sends/receives)
- `allowed_numbers`: List of phone numbers allowed to interact (for security)

### 3. Install Dependencies

```bash
pip install twilio flask
```

### 4. Set Up Webhook (for receiving messages)

The bridge needs a public URL for Twilio webhooks. Options:

**Option A: ngrok (for local development)**
```bash
# Terminal 1: Start the bridge
python ~/.claude/skills/twilio-sms/twilio_bridge.py --auto

# Terminal 2: Expose with ngrok
ngrok http 5001
```
Then set the ngrok URL in Twilio Console -> Phone Numbers -> Your Number -> Messaging -> Webhook URL: `https://xxxx.ngrok.io/sms`

**Option B: Deploy to server**
Deploy twilio_bridge.py to a server with a public URL.

## CLI Usage

```bash
# Send an SMS
python twilio_skill.py send +1234567890 -m "Hello from Claude!"

# Send MMS (with image URL)
python twilio_skill.py send +1234567890 -m "Check this out" --media https://example.com/image.png

# Read recent inbox
python twilio_skill.py inbox

# Check conversation history with a number
python twilio_skill.py history +1234567890

# Check Twilio account status
python twilio_skill.py status
```

## Bridge Mode (Auto-Response)

```bash
# Start the bridge with auto-respond
python twilio_bridge.py --auto --workdir /path/to/workspace

# Start in background
python twilio_bridge.py --auto --daemon

# Check status
python twilio_bridge.py --status

# Stop
python twilio_bridge.py --stop

# View inbox
python twilio_bridge.py --inbox
```

## Features

- **Auto-response**: Incoming SMS triggers Claude Code, response sent back
- **Conversation tracking**: Maintains context across messages from same number
- **Progress updates**: Sends "Working on it..." for long-running tasks
- **MMS support**: Can send images (requires public URL)
- **Security**: Only responds to allowed phone numbers

## Required Twilio Permissions

- Send SMS/MMS
- Receive SMS/MMS (webhook)
- Phone number with SMS capability

## Files

- `twilio_skill.py` - CLI for sending messages
- `twilio_bridge.py` - Webhook server for auto-response
- `config.json` - Twilio credentials (create this)
- `inbox.jsonl` - Received messages log
