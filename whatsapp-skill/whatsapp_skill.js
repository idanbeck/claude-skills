#!/usr/bin/env node
/**
 * WhatsApp Skill - Send and receive WhatsApp messages via WhatsApp Web.
 *
 * Uses whatsapp-web.js to automate WhatsApp Web with persistent sessions.
 *
 * Usage:
 *   node whatsapp_skill.js auth [--session NAME]
 *   node whatsapp_skill.js send PHONE "message" [--session NAME]
 *   node whatsapp_skill.js send-group GROUP_ID "message" [--session NAME]
 *   node whatsapp_skill.js chats [--limit N] [--session NAME]
 *   node whatsapp_skill.js messages CHAT_ID [--limit N] [--session NAME]
 *   node whatsapp_skill.js contacts [--session NAME]
 *   node whatsapp_skill.js groups [--session NAME]
 *   node whatsapp_skill.js search "query" [--session NAME]
 *   node whatsapp_skill.js status [--session NAME]
 *   node whatsapp_skill.js logout [--session NAME]
 */

const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const fs = require('fs');
const path = require('path');

const SKILL_DIR = __dirname;
const SESSIONS_DIR = path.join(SKILL_DIR, 'sessions');

// Ensure sessions directory exists
if (!fs.existsSync(SESSIONS_DIR)) {
    fs.mkdirSync(SESSIONS_DIR, { recursive: true });
}

function output(data) {
    console.log(JSON.stringify(data, null, 2));
}

function error(message, details = null) {
    output({ error: true, message, details });
    process.exit(1);
}

async function getClient(sessionName = 'default', waitForReady = true) {
    const client = new Client({
        authStrategy: new LocalAuth({
            clientId: sessionName,
            dataPath: SESSIONS_DIR
        }),
        puppeteer: {
            headless: true,
            args: [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--no-first-run',
                '--no-zygote',
                '--disable-gpu'
            ]
        }
    });

    return new Promise((resolve, reject) => {
        let qrShown = false;
        const timeout = setTimeout(() => {
            if (!qrShown) {
                reject(new Error('Timeout waiting for WhatsApp connection'));
            }
        }, 60000);

        client.on('qr', (qr) => {
            qrShown = true;
            console.error('\n=== SCAN QR CODE WITH WHATSAPP ===\n');
            qrcode.generate(qr, { small: true });
            console.error('\nOpen WhatsApp > Settings > Linked Devices > Link a Device\n');
        });

        client.on('authenticated', () => {
            console.error('Authenticated successfully');
        });

        client.on('auth_failure', (msg) => {
            clearTimeout(timeout);
            reject(new Error(`Authentication failed: ${msg}`));
        });

        client.on('ready', () => {
            clearTimeout(timeout);
            resolve(client);
        });

        if (!waitForReady) {
            client.initialize();
            resolve(client);
        } else {
            client.initialize();
        }
    });
}

async function cmdAuth(args) {
    const sessionName = args.session || 'default';

    try {
        const client = await getClient(sessionName);
        const info = client.info;

        output({
            success: true,
            session: sessionName,
            phone: info.wid.user,
            name: info.pushname,
            platform: info.platform
        });

        await client.destroy();
    } catch (err) {
        error('Authentication failed', err.message);
    }
}

async function cmdSend(args) {
    const sessionName = args.session || 'default';
    const phone = args.phone.replace(/[^0-9]/g, '');
    const message = args.message;

    if (!phone || !message) {
        error('Phone number and message are required');
    }

    try {
        const client = await getClient(sessionName);

        // Format: country code + number @ c.us
        const chatId = phone.includes('@') ? phone : `${phone}@c.us`;

        const result = await client.sendMessage(chatId, message);

        output({
            success: true,
            messageId: result.id.id,
            to: phone,
            timestamp: result.timestamp
        });

        await client.destroy();
    } catch (err) {
        error('Failed to send message', err.message);
    }
}

async function cmdSendGroup(args) {
    const sessionName = args.session || 'default';
    const groupId = args.groupId;
    const message = args.message;

    try {
        const client = await getClient(sessionName);

        // Group IDs end with @g.us
        const chatId = groupId.includes('@') ? groupId : `${groupId}@g.us`;

        const result = await client.sendMessage(chatId, message);

        output({
            success: true,
            messageId: result.id.id,
            to: groupId,
            timestamp: result.timestamp
        });

        await client.destroy();
    } catch (err) {
        error('Failed to send group message', err.message);
    }
}

async function cmdChats(args) {
    const sessionName = args.session || 'default';
    const limit = args.limit || 20;

    try {
        const client = await getClient(sessionName);
        const chats = await client.getChats();

        const chatList = chats.slice(0, limit).map(chat => ({
            id: chat.id._serialized,
            name: chat.name,
            isGroup: chat.isGroup,
            unreadCount: chat.unreadCount,
            timestamp: chat.timestamp,
            lastMessage: chat.lastMessage?.body?.substring(0, 100)
        }));

        output({
            success: true,
            count: chatList.length,
            chats: chatList
        });

        await client.destroy();
    } catch (err) {
        error('Failed to get chats', err.message);
    }
}

async function cmdMessages(args) {
    const sessionName = args.session || 'default';
    const chatId = args.chatId;
    const limit = args.limit || 20;

    try {
        const client = await getClient(sessionName);
        const chat = await client.getChatById(chatId);
        const messages = await chat.fetchMessages({ limit });

        const messageList = messages.map(msg => ({
            id: msg.id.id,
            from: msg.from,
            to: msg.to,
            body: msg.body,
            timestamp: msg.timestamp,
            fromMe: msg.fromMe,
            type: msg.type
        }));

        output({
            success: true,
            chatId,
            count: messageList.length,
            messages: messageList
        });

        await client.destroy();
    } catch (err) {
        error('Failed to get messages', err.message);
    }
}

async function cmdContacts(args) {
    const sessionName = args.session || 'default';

    try {
        const client = await getClient(sessionName);
        const contacts = await client.getContacts();

        const contactList = contacts
            .filter(c => c.isMyContact && !c.isGroup)
            .map(contact => ({
                id: contact.id._serialized,
                name: contact.name || contact.pushname,
                number: contact.number,
                isMyContact: contact.isMyContact
            }));

        output({
            success: true,
            count: contactList.length,
            contacts: contactList
        });

        await client.destroy();
    } catch (err) {
        error('Failed to get contacts', err.message);
    }
}

async function cmdGroups(args) {
    const sessionName = args.session || 'default';

    try {
        const client = await getClient(sessionName);
        const chats = await client.getChats();

        const groups = chats
            .filter(chat => chat.isGroup)
            .map(group => ({
                id: group.id._serialized,
                name: group.name,
                participantCount: group.participants?.length,
                unreadCount: group.unreadCount
            }));

        output({
            success: true,
            count: groups.length,
            groups
        });

        await client.destroy();
    } catch (err) {
        error('Failed to get groups', err.message);
    }
}

async function cmdSearch(args) {
    const sessionName = args.session || 'default';
    const query = args.query;

    try {
        const client = await getClient(sessionName);
        const messages = await client.searchMessages(query);

        const results = messages.slice(0, 20).map(msg => ({
            id: msg.id.id,
            chatId: msg.from,
            body: msg.body,
            timestamp: msg.timestamp,
            fromMe: msg.fromMe
        }));

        output({
            success: true,
            query,
            count: results.length,
            messages: results
        });

        await client.destroy();
    } catch (err) {
        error('Failed to search messages', err.message);
    }
}

async function cmdStatus(args) {
    const sessionName = args.session || 'default';
    const sessionPath = path.join(SESSIONS_DIR, `session-${sessionName}`);

    const exists = fs.existsSync(sessionPath);

    if (!exists) {
        output({
            success: true,
            session: sessionName,
            authenticated: false,
            message: 'No session found. Run auth command to authenticate.'
        });
        return;
    }

    try {
        const client = await getClient(sessionName);
        const info = client.info;

        output({
            success: true,
            session: sessionName,
            authenticated: true,
            phone: info.wid.user,
            name: info.pushname,
            platform: info.platform
        });

        await client.destroy();
    } catch (err) {
        output({
            success: true,
            session: sessionName,
            authenticated: false,
            message: 'Session exists but connection failed. May need to re-authenticate.'
        });
    }
}

async function cmdLogout(args) {
    const sessionName = args.session || 'default';

    try {
        const client = await getClient(sessionName);
        await client.logout();
        await client.destroy();

        output({
            success: true,
            session: sessionName,
            message: 'Logged out successfully'
        });
    } catch (err) {
        // Try to delete session files anyway
        const sessionPath = path.join(SESSIONS_DIR, `session-${sessionName}`);
        if (fs.existsSync(sessionPath)) {
            fs.rmSync(sessionPath, { recursive: true });
        }

        output({
            success: true,
            session: sessionName,
            message: 'Session cleared'
        });
    }
}

// Parse command line arguments
function parseArgs() {
    const args = process.argv.slice(2);
    const command = args[0];
    const parsed = { command };

    let i = 1;
    while (i < args.length) {
        if (args[i] === '--session' || args[i] === '-s') {
            parsed.session = args[++i];
        } else if (args[i] === '--limit' || args[i] === '-l') {
            parsed.limit = parseInt(args[++i]);
        } else if (!parsed.positional1) {
            parsed.positional1 = args[i];
        } else if (!parsed.positional2) {
            parsed.positional2 = args[i];
        }
        i++;
    }

    return parsed;
}

async function main() {
    const args = parseArgs();

    switch (args.command) {
        case 'auth':
            await cmdAuth(args);
            break;
        case 'send':
            args.phone = args.positional1;
            args.message = args.positional2;
            await cmdSend(args);
            break;
        case 'send-group':
            args.groupId = args.positional1;
            args.message = args.positional2;
            await cmdSendGroup(args);
            break;
        case 'chats':
            await cmdChats(args);
            break;
        case 'messages':
            args.chatId = args.positional1;
            await cmdMessages(args);
            break;
        case 'contacts':
            await cmdContacts(args);
            break;
        case 'groups':
            await cmdGroups(args);
            break;
        case 'search':
            args.query = args.positional1;
            await cmdSearch(args);
            break;
        case 'status':
            await cmdStatus(args);
            break;
        case 'logout':
            await cmdLogout(args);
            break;
        default:
            console.log(`
WhatsApp Skill - Send and receive WhatsApp messages

Commands:
  auth                    Authenticate with WhatsApp (scan QR code)
  send PHONE "msg"        Send message to phone number
  send-group ID "msg"     Send message to group
  chats                   List recent chats
  messages CHAT_ID        Get messages from a chat
  contacts                List contacts
  groups                  List groups
  search "query"          Search messages
  status                  Check authentication status
  logout                  Log out and clear session

Options:
  --session, -s NAME      Use named session (default: 'default')
  --limit, -l N           Limit results (default: 20)

Examples:
  node whatsapp_skill.js auth
  node whatsapp_skill.js send 14155551234 "Hello!"
  node whatsapp_skill.js chats --limit 10
            `);
    }
}

main().catch(err => {
    error('Unexpected error', err.message);
});
