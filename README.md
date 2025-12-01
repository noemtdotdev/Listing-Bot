# Listing Bot

A comprehensive multi-tenant Discord marketplace platform for selling digital items (gaming accounts, profiles, and more) with web dashboards, seller management, and integrated payment systems.

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Node.js](https://img.shields.io/badge/Node.js-16+-green.svg)
![Discord](https://img.shields.io/badge/Discord-py--cord-7289da.svg)
![React](https://img.shields.io/badge/React-18-61dafb.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
  - [Step 1: Clone the Repository](#step-1-clone-the-repository)
  - [Step 2: Set Up the Discord Bot](#step-2-set-up-the-discord-bot)
  - [Step 3: Create a Discord Application](#step-3-create-a-discord-application)
  - [Step 4: Set Up the Parent API](#step-4-set-up-the-parent-api)
  - [Step 5: Set Up the Web Dashboards](#step-5-set-up-the-web-dashboards)
- [Running the Application](#running-the-application)
- [Configuration](#configuration)
- [Project Structure](#project-structure)
- [API Documentation](#api-documentation)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

## Overview

Listing Bot is a complete solution for running a digital marketplace through Discord. It allows you to:

- List and sell digital items (gaming accounts, profiles, alts)
- Manage sellers with individual permissions
- Process payments and track transactions
- Provide customer support through a ticket system
- Collect and display customer reviews (vouches)
- Run a public-facing shop website
- Monitor everything through web dashboards

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Parent API (FastAPI)                        │
│                        Port 7000 - Main Gateway                     │
│   • Central Discord OAuth authentication                            │
│   • Routes requests to individual bot instances                     │
│   • Manages custom domains for white-label shops                    │
│   • WebSocket connections for real-time logging                     │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
            ┌───────────────────┼───────────────────┐
            │                   │                   │
            ▼                   ▼                   ▼
    ┌───────────────┐   ┌───────────────┐   ┌───────────────┐
    │   Bot #1      │   │   Bot #2      │   │   Bot #N      │
    │  (py-cord)    │   │  (py-cord)    │   │  (py-cord)    │
    │  + Quart API  │   │  + Quart API  │   │  + Quart API  │
    │  Port: Auto   │   │  Port: Auto   │   │  Port: Auto   │
    │  SQLite DB    │   │  SQLite DB    │   │  SQLite DB    │
    └───────────────┘   └───────────────┘   └───────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                        Frontend Applications                        │
├─────────────────────────────────────────────────────────────────────┤
│  listing-bot-dashboard/  │  Bot owner control panel (React)        │
│  seller_dashboard/       │  Seller management interface (React)    │
│  shop-sites/             │  Public customer shop (React)           │
└─────────────────────────────────────────────────────────────────────┘
```

## Features

| Feature | Description |
|---------|-------------|
| **Multi-Tenant Support** | Run multiple independent bot instances, each with its own database |
| **Item Listings** | List accounts, profiles, and alt accounts with rich details |
| **Ticket System** | Built-in customer support with ticket creation and transcripts |
| **Vouch System** | Customer review and rating system |
| **Seller Management** | Assign seller roles with individual payment configurations |
| **AI Features** | AI-powered features with a monthly credit system (150 free/month) |
| **Custom Domains** | White-label shop support with custom domain routing |
| **Payment Tracking** | Track hosting payments and transaction history |
| **Browser Fingerprinting** | Advanced fraud detection for user authentication |
| **Real-time Logging** | WebSocket-based live command and data fetch logging |
| **OAuth2 Authentication** | Secure Discord-based authentication for all dashboards |

## Prerequisites

Before you begin, ensure you have the following installed:

- **Python 3.8 or higher** - [Download Python](https://www.python.org/downloads/)
- **Node.js 16 or higher** - [Download Node.js](https://nodejs.org/)
- **npm** (comes with Node.js)
- **Git** - [Download Git](https://git-scm.com/downloads/)
- **A Discord Account** - [Create Discord Account](https://discord.com/)

### Verify Installation

Open a terminal and run:

```bash
python --version
node --version
npm --version
git --version
```

All commands should return version numbers without errors.

## Installation

### Step 1: Clone the Repository

```bash
git clone https://github.com/your-username/Listing-Bot.git
cd Listing-Bot
```

### Step 2: Set Up the Discord Bot

#### 2.1 Create a Python Virtual Environment

```bash
cd listing-bot

# Create virtual environment
python -m venv venv

# Activate it (choose your OS)

# Windows (Command Prompt):
venv\Scripts\activate.bat

# Windows (PowerShell):
.\venv\Scripts\Activate.ps1

# macOS/Linux:
source venv/bin/activate
```

#### 2.2 Install Python Dependencies

```bash
pip install -r requirements.txt
```

#### 2.3 Create the Environment File

Copy the example environment file and edit it with your values:

```bash
# Copy the example file
cp env.example listing-bot/.env
```

Edit the `.env` file in the `listing-bot/` directory with your settings:

```env
# Discord bot token (required)
TOKEN=your_discord_bot_token_here

# Server configuration - use your server's IP address
# For local development, use 127.0.0.1
# For production, use your server's actual IP (e.g., 192.168.1.100)
SERVER_HOST=127.0.0.1
BOT_SERVICE_HOST=127.0.0.1
PARENT_API_HOST=127.0.0.1
PARENT_API_PORT=7000

# If you have a Skyblock data API running
SKYBLOCK_API_HOST=127.0.0.1
SKYBLOCK_API_PORT=3002
```

Replace `your_discord_bot_token_here` with your actual Discord bot token (see Step 3).

### Step 3: Create a Discord Application

#### 3.1 Create Application

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **"New Application"**
3. Enter a name for your bot and click **"Create"**

#### 3.2 Create Bot User

1. In your application, go to the **"Bot"** tab on the left sidebar
2. Click **"Add Bot"** and confirm
3. Under **"Privileged Gateway Intents"**, enable:
   - **Presence Intent**
   - **Server Members Intent**
   - **Message Content Intent**
4. Click **"Reset Token"** and copy your bot token
5. Paste this token in your `.env` file

#### 3.3 Set Up OAuth2 (Required for Dashboard Authentication)

1. Go to the **"OAuth2"** tab
2. Under **"Redirects"**, add your callback URL:
   - For local development: `http://localhost:7000/auth/discord/callback`
   - For production: `https://yourdomain.com/auth/discord/callback`
3. Copy your **Client ID** and **Client Secret** (you'll need these for the Parent API)

#### 3.4 Invite the Bot to Your Server

1. Go to **"OAuth2" → "URL Generator"**
2. Select scopes: `bot`, `applications.commands`
3. Select bot permissions:
   - Manage Roles
   - Manage Channels
   - Read Messages/View Channels
   - Send Messages
   - Manage Messages
   - Embed Links
   - Attach Files
   - Read Message History
   - Add Reactions
   - Use Slash Commands
4. Copy the generated URL and open it in your browser
5. Select your server and authorize the bot

### Step 4: Set Up the Parent API

#### 4.1 Navigate to Parent API Directory

```bash
cd ../parent_api
```

#### 4.2 Install Python Dependencies

```bash
pip install fastapi uvicorn aiohttp httpx python-dotenv
```

#### 4.3 Create Environment File

Create a `.env` file in the `parent_api/` directory with the following configuration:

```env
# API Authentication
API_KEY=your_secret_api_key_here
INTERNAL_API_KEY=your_internal_api_key_here

# Server Configuration - use your server's IP address
# For local development, use 127.0.0.1
# For production, use your server's actual IP
SERVER_HOST=127.0.0.1
BOT_SERVICE_HOST=127.0.0.1
SHOP_FRONTEND_HOST=127.0.0.1
SHOP_FRONTEND_PORT=7878

# Discord OAuth2 Configuration
DISCORD_CLIENT_ID=your_discord_client_id
DISCORD_CLIENT_SECRET=your_discord_client_secret
DISCORD_REDIRECT_URI=https://yourdomain.com/auth/discord/callback

# Session Configuration
SESSION_LIFETIME_HOURS=24
```

Generate a secure API key (you can use any random string, e.g., from https://randomkeygen.com/).

**Important:** Replace `yourdomain.com` with your actual domain or use `http://127.0.0.1:7000` for local development.

#### 4.4 Create Ports Configuration

Create a `ports.json` file in the `parent_api/` directory:

```json
{}
```

This file will be automatically populated when bots start.

#### 4.5 Create Custom Domains File (Optional)

If you want to use custom domains, create `custom_domains.json`:

```json
[]
```

### Step 5: Set Up the Web Dashboards

Each dashboard is a React application that needs to be set up separately.

#### 5.1 Set Up Bot Owner Dashboard

```bash
cd ../listing-bot-dashboard

# Install dependencies
npm install

# For development:
npm start

# For production build:
npm run build
```

#### 5.2 Set Up Seller Dashboard

```bash
cd ../seller_dashboard

# Install dependencies
npm install

# For development:
npm start

# For production build:
npm run build
```

#### 5.3 Set Up Shop Frontend

```bash
cd ../shop-sites

# Install dependencies
npm install

# For development:
npm start

# For production build:
npm run build
```

## Running the Application

### Development Mode

You'll need to run multiple services. Open separate terminal windows for each:

#### Terminal 1: Discord Bot + Bot API

```bash
cd listing-bot

# Activate virtual environment
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Run the bot
python main.py
```

#### Terminal 2: Parent API

```bash
cd parent_api

# Run with uvicorn
uvicorn api:app --host 0.0.0.0 --port 7000 --reload
```

#### Terminal 3: Dashboard (optional, for development)

```bash
cd listing-bot-dashboard
npm start
```

#### Terminal 4: Shop Site (optional, for development)

```bash
cd shop-sites
npm start
```

### Windows Quick Start

Use the provided batch file:

```bash
cd listing-bot
launch.bat
```

### Production Deployment

For production, you should:

1. Build the React apps: `npm run build` in each frontend directory
2. Use a process manager like PM2 or systemd
3. Set up a reverse proxy (nginx/Caddy) for HTTPS
4. Use environment variables for sensitive data

Example with PM2:

```bash
# Install PM2 globally
npm install -g pm2

# Start the bot
cd listing-bot
pm2 start main.py --interpreter python --name "listing-bot"

# Start the parent API
cd ../parent_api
pm2 start "uvicorn api:app --host 0.0.0.0 --port 7000" --name "parent-api"

# Serve the built React apps with a static server
cd ../shop-sites
pm2 serve build 7878 --name "shop-frontend"
```

## Configuration

### Bot Configuration

The bot stores configuration in SQLite database. Key settings can be configured through Discord commands:

| Command | Description |
|---------|-------------|
| `/config` | View/edit bot configuration |
| `/setup-email` | Set owner email for payment notifications |

### Database Schema

The bot automatically creates and migrates the SQLite database (`data/bot.db`). Key tables include:

- `accounts` - Listed accounts
- `profiles` - Listed profiles
- `alts` - Listed alt accounts
- `config` - Bot configuration key-value store
- `tickets` - Support tickets
- `vouches` - Customer reviews
- `sellers` - Registered sellers
- `auth` - User authentication tokens
- `hosting` - Payment/hosting status
- `ai_config` - AI credit tracking

### Port Configuration

Ports are automatically assigned and stored in `parent_api/ports.json`. The bot name (directory name) maps to its assigned port:

```json
{
    "listing-bot": 3080,
    "another-bot": 3081
}
```

## Project Structure

```
Listing-Bot/
├── listing-bot/              # Main Discord bot
│   ├── api/                  # Quart API endpoints
│   │   ├── GET/              # GET request handlers
│   │   ├── POST/             # POST request handlers
│   │   └── templates/        # HTML templates
│   ├── bot/                  # Discord bot code
│   │   ├── cogs/             # Bot command modules
│   │   ├── util/             # Utility functions
│   │   └── trolls/           # Captcha system
│   ├── data/                 # Data files and database
│   ├── emojis/               # Custom emoji images
│   ├── main.py               # Entry point
│   └── requirements.txt      # Python dependencies
│
├── parent_api/               # Central FastAPI gateway
│   ├── api.py                # Main API application
│   ├── ports.json            # Bot port mappings
│   └── templates/            # HTML templates
│
├── listing-bot-dashboard/    # Bot owner dashboard (React)
│   ├── src/
│   │   ├── components/
│   │   └── pages/
│   └── package.json
│
├── seller_dashboard/         # Seller dashboard (React)
│   ├── src/
│   │   ├── components/
│   │   └── pages/
│   └── package.json
│
├── shop-sites/               # Public shop frontend (React)
│   ├── src/
│   │   ├── components/
│   │   └── pages/
│   └── package.json
│
├── UTILITY/                  # Development utilities
│
└── README.md                 # This file
```

## API Documentation

### Parent API Endpoints

| Endpoint | Method | Description | Auth Required |
|----------|--------|-------------|---------------|
| `/auth/discord/login` | GET | Start Discord OAuth flow | No |
| `/auth/discord/callback` | GET | OAuth callback handler | No |
| `/auth/me` | GET | Get current user info | Yes |
| `/auth/logout` | GET | Logout user | Yes |
| `/dash/{bot_name}` | GET | Get bot dashboard data | Yes (Owner) |
| `/api/bot/{bot_name}/config` | GET/POST | Get/update bot config | Yes (Owner) |
| `/api/bot/{bot_name}/listed/items` | GET | Get listed items | Yes (Owner) |
| `/api/seller/accounts` | GET | Get seller accounts | Yes (Seller) |
| `/stats/{bot_name}` | GET | Get bot statistics | No |

### Bot API Endpoints

Each bot exposes its own API on its assigned port:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/stats` | GET | Bot statistics |
| `/config` | GET/POST | Configuration |
| `/listed/items` | GET | All listed items |
| `/auth/users` | GET | Authorized users |
| `/seller/get/accounts` | GET | Seller's listed items |

## Troubleshooting

### Bot won't start

1. **Check Python version**: Ensure Python 3.8+ is installed
2. **Check virtual environment**: Make sure venv is activated
3. **Verify token**: Check that `.env` contains a valid bot token
4. **Check intents**: Ensure all privileged intents are enabled in Discord Developer Portal

### "Bot is not responding" in dashboard

1. **Check if bot is running**: Verify the bot process is active
2. **Check ports.json**: Ensure the bot's port is correctly registered
3. **Check firewall**: Ensure the port isn't blocked

### OAuth2 authentication fails

1. **Check redirect URI**: Must match exactly in Discord Developer Portal
2. **Check client credentials**: Verify Client ID and Secret in `api.py`
3. **Check cookies**: Ensure cookies are enabled in your browser

### Database errors

1. **Delete and recreate**: Remove `data/bot.db` to start fresh (data will be lost)
2. **Check permissions**: Ensure write access to the `data/` directory

### npm install fails

1. **Clear cache**: Run `npm cache clean --force`
2. **Delete node_modules**: Remove and reinstall: `rm -rf node_modules && npm install`
3. **Check Node version**: Ensure Node.js 16+ is installed

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit your changes: `git commit -m 'Add amazing feature'`
4. Push to the branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

<<<<<<< Updated upstream
Made with care by [noemt.dev](https://noemt.dev)

todo: api key information

these keys should be set to the same:
listing-bot\api\auth_utils.py
INTERNAL_API_KEY in parent_api\api.py

APP_API_KEY in parent_api\api.py (from the env)
listing-bot\bot\util\attachment_handler.py

you do require a hypixel api key from their developer dashboard
enter it here:
listing-bot\bot\util\constants.py

seperate process info:
you need to run an instance of https://github.com/noemtdotdev/skyblock-wrapper
then, enter the port (and ip if you want to test locally on the same codebase) into listing-bot\bot\util\fetch.py
(this also requires a hypixel api key)

the api key you use for authentication there needs to be entered in listing-bot\bot\util\fetch.py

replace ALL localhost with the actual servers ip that you are running on to make 100% sure that it runs (it should with localhost but you can never be sure enough)
=======
Made by [noemt.dev](https://noemt.dev), README.md by [ash](https://github.com/auradoescoding)
>>>>>>> Stashed changes
