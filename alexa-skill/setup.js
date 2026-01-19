#!/usr/bin/env node
/**
 * Alexa Skill Setup - Uses alexa-cookie2 for Amazon authentication
 *
 * This script starts a proxy server and opens your browser for Amazon login.
 * After successful login, it saves the cookies needed for Alexa API access.
 */

const Alexa = require('alexa-cookie2');
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const CONFIG_FILE = path.join(__dirname, 'config.json');
const PORT = 8765;

// Get email from command line
const email = process.argv[2];
const region = process.argv[3] || 'us';

if (!email) {
    console.log(JSON.stringify({
        error: "Email required",
        usage: "node setup.js <email> [region]",
        regions: ["us", "uk", "de", "jp", "ca", "au", "fr", "it", "es", "br", "mx", "in"]
    }, null, 2));
    process.exit(1);
}

// Map region to Amazon domain
const AMAZON_DOMAINS = {
    us: 'amazon.com',
    uk: 'amazon.co.uk',
    de: 'amazon.de',
    jp: 'amazon.co.jp',
    ca: 'amazon.ca',
    au: 'amazon.com.au',
    fr: 'amazon.fr',
    it: 'amazon.it',
    es: 'amazon.es',
    br: 'amazon.com.br',
    mx: 'amazon.com.mx',
    in: 'amazon.in'
};

const amazonDomain = AMAZON_DOMAINS[region] || 'amazon.com';

console.log('\n=== Alexa Skill Setup ===');
console.log(`Email: ${email}`);
console.log(`Region: ${region} (${amazonDomain})`);
console.log();

const config = {
    proxyOwnIp: '127.0.0.1',
    proxyPort: PORT,
    amazonPage: amazonDomain,
    acceptLanguage: 'en-US',
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
};

console.log('Starting authentication proxy...');
console.log();
console.log('='.repeat(50));
console.log('A browser window will open for Amazon login.');
console.log('Complete the login to authenticate.');
console.log('='.repeat(50));
console.log();

let browserOpened = false;

Alexa.generateAlexaCookie(email, '', config, (err, result) => {
    // The callback is called multiple times:
    // 1. First with err containing instructions to open browser
    // 2. Later with actual result or error

    if (err && !result) {
        const errStr = err.message || String(err);

        // Check if this is just the "open browser" instruction
        if (errStr.includes('Please open') && errStr.includes('browser')) {
            console.log('Proxy server running. Please complete login in the browser window...');
            console.log();

            // Open browser if not already done
            if (!browserOpened) {
                browserOpened = true;
                const url = `http://127.0.0.1:${PORT}/`;
                try {
                    if (process.platform === 'darwin') {
                        execSync(`open "${url}"`);
                    } else if (process.platform === 'linux') {
                        execSync(`xdg-open "${url}"`);
                    } else if (process.platform === 'win32') {
                        execSync(`start "${url}"`);
                    }
                    console.log(`Browser opened to: ${url}`);
                } catch (e) {
                    console.log(`Please open this URL in your browser: ${url}`);
                }
            }
            return; // Wait for next callback
        }

        // Actual error
        console.log(JSON.stringify({
            error: "Authentication failed",
            message: errStr
        }, null, 2));
        process.exit(1);
    }

    if (result) {
        // Success! Save the result
        const configData = {
            email: email,
            region: region,
            url: amazonDomain,
            cookies: result.cookie,
            csrf: result.csrf,
            localCookie: result.localCookie,
            deviceSerial: result.deviceSerial,
            deviceId: result.deviceId,
            refreshToken: result.refreshToken
        };

        fs.writeFileSync(CONFIG_FILE, JSON.stringify(configData, null, 2));

        console.log(JSON.stringify({
            success: true,
            message: "Authentication successful!",
            email: email,
            region: region
        }, null, 2));

        process.exit(0);
    }
});
