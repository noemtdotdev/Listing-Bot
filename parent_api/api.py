from fastapi import FastAPI, HTTPException, Request, Query, WebSocket, WebSocketDisconnect, Response, Depends
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import os
import aiohttp
import json
from dotenv import load_dotenv
import base64
from typing import Optional, Dict, List, Any, Set, Tuple
from datetime import datetime, timedelta
import time
import asyncio
from functools import lru_cache, wraps
import logging
import uuid
import httpx

load_dotenv()
APP_API_KEY = os.getenv("API_KEY")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")

SERVER_HOST = os.getenv("SERVER_HOST", "127.0.0.1")
BOT_SERVICE_HOST = os.getenv("BOT_SERVICE_HOST", SERVER_HOST)
SHOP_FRONTEND_HOST = os.getenv("SHOP_FRONTEND_HOST", SERVER_HOST)
SHOP_FRONTEND_PORT = os.getenv("SHOP_FRONTEND_PORT", "7878")

DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "1394403872809816125")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "https://v2.noemt.dev/auth/discord/callback")
DISCORD_AUTHORIZE_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_USER_URL = "https://discord.com/api/users/@me"

SESSION_LIFETIME = timedelta(hours=int(os.getenv("SESSION_LIFETIME_HOURS", "24")))

DISALLOWED_FILES = {"parent_api"}

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Domain approval cache
approved_domains_cache: Set[str] = set()
last_cache_update: Optional[datetime] = None
CACHE_TTL_SECONDS = 20

def load_approved_domains() -> Set[str]:
    """
    Loads the list of approved domains from custom_domains.json.
    This is the definitive list of customers with an 'active service'.
    """
    global last_cache_update, approved_domains_cache
    now = datetime.now()

    if last_cache_update and (now - last_cache_update).total_seconds() < CACHE_TTL_SECONDS:
        return approved_domains_cache

    try:
        with open("custom_domains.json", "r") as f:
            domains = json.load(f)
            if not isinstance(domains, list):
                logger.error("custom_domains.json should contain a list of domains.")
                return set()
            
            # Update cache
            approved_domains_cache = {str(domain).lower() for domain in domains}
            last_cache_update = now
            
            logger.info(f"Successfully loaded {len(approved_domains_cache)} custom domains.")
            return approved_domains_cache
            
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Could not load or parse custom_domains.json: {e}")
        # In case of error, return an empty set to prevent unauthorized access
        return set()

class AppCache:
    """Centralized cache for application data"""
    def __init__(self):
        self._ports: Optional[Dict] = None
        self._bots: Optional[List[str]] = None
        self._last_ports_update: Optional[datetime] = None
        self._last_bots_update: Optional[datetime] = None
        self._cache_ttl = timedelta(minutes=5)  # 5-minute cache TTL
    
    def is_cache_valid(self, last_update: Optional[datetime]) -> bool:
        if last_update is None:
            return False
        return datetime.now() - last_update < self._cache_ttl
    
    def get_ports(self) -> Optional[Dict]:
        if self.is_cache_valid(self._last_ports_update):
            return self._ports
        return None
    
    def set_ports(self, ports: Dict):
        self._ports = ports
        self._last_ports_update = datetime.now()
    
    def get_bots(self) -> Optional[List[str]]:
        if self.is_cache_valid(self._last_bots_update):
            return self._bots
        return None
    
    def set_bots(self, bots: List[str]):
        self._bots = bots
        self._last_bots_update = datetime.now()

class SessionStorage:
    """In-memory session storage with automatic cleanup"""
    def __init__(self):
        self._sessions: Dict[str, Dict] = {}
        self._lock = asyncio.Lock()
    
    async def create_session(self, discord_id: str, user_info: Dict) -> str:
        """Create a new session and return session ID"""
        session_id = str(uuid.uuid4())
        expires_at = datetime.now() + SESSION_LIFETIME
        
        async with self._lock:
            self._sessions[session_id] = {
                "discord_id": discord_id,
                "user_info": user_info,
                "expires_at": expires_at,
                "created_at": datetime.now()
            }
        
        logger.info(f"Created session {session_id} for Discord user {discord_id}")
        return session_id
    
    async def get_session(self, session_id: str) -> Optional[Dict]:
        """Get session data if it exists and is valid"""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session and session["expires_at"] > datetime.now():
                return session
            elif session:
                # Session expired, remove it
                del self._sessions[session_id]
        return None
    
    async def delete_session(self, session_id: str) -> bool:
        """Delete a session"""
        async with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                logger.info(f"Deleted session {session_id}")
                return True
        return False
    
    async def cleanup_expired_sessions(self):
        """Remove expired sessions"""
        now = datetime.now()
        async with self._lock:
            expired_sessions = [
                session_id for session_id, session in self._sessions.items()
                if session["expires_at"] <= now
            ]
            for session_id in expired_sessions:
                del self._sessions[session_id]
        
        if expired_sessions:
            logger.info(f"Cleaned up {len(expired_sessions)} expired sessions")
    
    async def get_active_sessions_count(self) -> int:
        """Get the number of active sessions"""
        await self.cleanup_expired_sessions()
        return len(self._sessions)

class App(FastAPI):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache = AppCache()
        self.sessions = SessionStorage()

app = App(
    title="Listing Bot API",
    description="API for managing listing bots.",
    version="1.0.0",
    docs_url=None,
    redoc_url="/docs"
)

templates = Jinja2Templates(directory="templates")

# Dynamic CORS configuration
def get_dynamic_cors_origins() -> List[str]:
    """Get dynamically updated CORS origins including approved custom domains"""
    base_origins = [
        "https://v2.noemt.dev",
        "https://noemt.dev", 
        "https://shop.noemt.dev",
        "https://sellers.noemt.dev",
        "https://dashboard.noemt.dev",
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001"
    ]
    
    # Add approved custom domains
    try:
        approved_domains = load_approved_domains()
        custom_origins = [f"https://{domain}" for domain in approved_domains]
        return base_origins + custom_origins
    except Exception as e:
        logger.error(f"Error loading approved domains for CORS: {e}")
        return base_origins

class DynamicCORSMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, allow_credentials: bool = True):
        super().__init__(app)
        self.allow_credentials = allow_credentials
        self.allow_methods = ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"]
        self.allow_headers = [
            "accept",
            "accept-encoding",
            "authorization",
            "content-type",
            "dnt",
            "origin",
            "user-agent",
            "x-csrftoken",
            "x-requested-with",
        ]
        self.expose_headers = ["*"]
    
    async def dispatch(self, request, call_next):
        # Get dynamic origins
        allowed_origins = get_dynamic_cors_origins()
        
        # Handle preflight requests
        if request.method == "OPTIONS":
            origin = request.headers.get("origin")
            
            headers = {
                "Access-Control-Allow-Methods": ", ".join(self.allow_methods),
                "Access-Control-Allow-Headers": ", ".join(self.allow_headers),
                "Access-Control-Expose-Headers": "*",
                "Access-Control-Max-Age": "86400",  # Cache preflight for 24 hours
            }
            
            if origin and origin in allowed_origins:
                headers["Access-Control-Allow-Origin"] = origin
                if self.allow_credentials:
                    headers["Access-Control-Allow-Credentials"] = "true"
            
            return StarletteResponse(status_code=200, headers=headers)
        
        # Process the request
        response = await call_next(request)
        
        # Add CORS headers to response
        origin = request.headers.get("origin")
        if origin and origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            if self.allow_credentials:
                response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Expose-Headers"] = "*"
        
        return response

# Add the dynamic CORS middleware
app.add_middleware(DynamicCORSMiddleware, allow_credentials=True)

# Create static directory for local files if needed
import os
os.makedirs("static", exist_ok=True)

@app.on_event("startup")
async def startup_event():
    # Create session with optimized connector settings
    connector = aiohttp.TCPConnector(
        limit=100,  # Total connection pool size
        limit_per_host=30,  # Max connections per host
        ttl_dns_cache=300,  # DNS cache TTL
        use_dns_cache=True,
        keepalive_timeout=30,
        enable_cleanup_closed=True
    )
    
    # Configure session with timeout and connection settings
    timeout = aiohttp.ClientTimeout(total=30, connect=5)
    app.session = aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers={"User-Agent": "ListingBot-Parent-API/1.0"}
    )
    
    # Start background task for session cleanup
    asyncio.create_task(session_cleanup_task())
    
    logger.info("Application started with optimized HTTP session and session management")

async def session_cleanup_task():
    """Background task to clean up expired sessions every hour"""
    while True:
        try:
            await asyncio.sleep(3600)  # Run every hour
            await app.sessions.cleanup_expired_sessions()
        except Exception as e:
            logger.error(f"Error in session cleanup task: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources on shutdown"""
    if app.session:
        await app.session.close()
    logger.info("Application shutdown complete")

async def get_listing_bots() -> List[str]:
    """Get listing bots with caching"""
    cached_bots = app.cache.get_bots()
    if cached_bots is not None:
        return cached_bots
    
    try:
        bots = [file for file in os.listdir("../") if file not in DISALLOWED_FILES]
        app.cache.set_bots(bots)
        return bots
    except OSError as e:
        logger.error(f"Error reading bot directories: {e}")
        return []

def get_ports() -> Dict:
    """Get ports configuration with caching and error handling"""
    cached_ports = app.cache.get_ports()
    if cached_ports is not None:
        return cached_ports
    
    try:
        with open("./ports.json") as f:
            ports = json.load(f)
            app.cache.set_ports(ports)
            return ports
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Error loading ports configuration: {e}")
        raise HTTPException(status_code=500, detail="Error loading ports configuration")

async def make_bot_request(port: int, endpoint: str, timeout: int = 10, data: Any = None) -> Tuple[bool, Dict]:
    """
    Make an optimized request to a bot endpoint
    Returns: (success, response_data)
    """
    url = f"http://{BOT_SERVICE_HOST}:{port}{endpoint}"
    if "?" in url:
        url += f"&api_key={INTERNAL_API_KEY}"
    else:
        url += f"?api_key={INTERNAL_API_KEY}"
    
    try:
        if data is not None:
            # Make POST request with JSON data
            async with app.session.post(
                url, 
                json=data,
                timeout=aiohttp.ClientTimeout(total=timeout),
                headers={'Content-Type': 'application/json'}
            ) as response:
                if response.status == 200:
                    response_data = await response.json()
                    return True, response_data
                else:
                    error_data = await response.json() if response.content_type == 'application/json' else {"error": "Unknown error"}
                    return False, error_data
        else:
            # Make GET request
            async with app.session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                if response.status == 200:
                    response_data = await response.json()
                    return True, response_data
                else:
                    error_data = await response.json() if response.content_type == 'application/json' else {"error": "Unknown error"}
                    return False, error_data
    except aiohttp.ClientConnectorError:
        logger.warning(f"Bot on port {port} is not responding")
        return False, {"error": "Bot is not responding"}
    except asyncio.TimeoutError:
        logger.warning(f"Request to bot on port {port} timed out")
        return False, {"error": "Request timed out"}
    except Exception as e:
        logger.error(f"Error making request to bot on port {port}: {e}")
        return False, {"error": f"Request failed: {str(e)}"}

async def find_bot_by_email(email: str) -> Tuple[Optional[str], Optional[int]]:
    """
    Find a bot by email address efficiently using concurrent requests
    Returns: (bot_name, port) or (None, None) if not found
    """
    bots = await get_listing_bots()
    ports = get_ports()
    
    # Create concurrent tasks for all bots
    tasks = []
    bot_port_pairs = []
    
    for bot_name in bots:
        port = ports.get(bot_name)
        if port:
            task = make_bot_request(port, "/get/email", timeout=5)
            tasks.append(task)
            bot_port_pairs.append((bot_name, port))
    
    if not tasks:
        return None, None
    
    # Execute all requests concurrently
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Check results for matching email
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            continue
            
        success, data = result
        if success:
            bot_email = data.get("email")
            if bot_email and bot_email.lower() == email.lower():
                bot_name, port = bot_port_pairs[i]
                return bot_name, port
    
    return None, None

async def get_token(bot_name: str) -> Dict:
    """Get token for a bot with better error handling"""
    bot_dir = os.path.join("../", bot_name)
    env_file = os.path.join(bot_dir, ".env")

    if not os.path.exists(env_file):
        return {"error": "No .env file found"}
    
    try:
        with open(env_file) as f:
            lines = f.readlines()
            tokens = [line.split("=")[1].strip() for line in lines if "=" in line]
            return tokens[0] if tokens else {"error": "No token found in .env file"}
    except (IOError, IndexError) as e:
        logger.error(f"Error reading token for bot {bot_name}: {e}")
        return {"error": "Error reading token file"}

async def get_current_user(request: Request) -> Optional[Dict]:
    """Dependency to get the current user from session with improved logging"""
    session_id = request.cookies.get('session_id')
    if not session_id:
        logger.debug("No session_id cookie found in request")
        return None
    
    logger.debug(f"Found session_id cookie: {session_id[:8]}...")
    
    session_data = await app.sessions.get_session(session_id)
    if session_data:
        logger.debug(f"Valid session found for user {session_data['discord_id']}")
        return {
            "discord_id": session_data["discord_id"],
            "user_info": session_data["user_info"],
            "session_id": session_id
        }
    else:
        logger.debug(f"No valid session found for session_id: {session_id[:8]}...")
    return None

def require_login(f):
    @wraps(f)
    async def decorated_function(*args, **kwargs):
        request = None
        for arg in args:
            if isinstance(arg, Request):
                request = arg
                break
        
        if not request:
            request = kwargs.get('request')
        
        if not request:
            raise HTTPException(status_code=500, detail="Request object not found")
        
        current_user = await get_current_user(request)
        if not current_user:
            raise HTTPException(
                status_code=401, 
                detail="Authentication required. Please login with Discord first.",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        bot_name = kwargs.get('bot_name')
        if not bot_name:
            path_info = request.path_info if hasattr(request, 'path_info') else request.url.path
            path_parts = path_info.split('/')
            for i, part in enumerate(path_parts):
                if part == 'bot' and i + 1 < len(path_parts):
                    bot_name = path_parts[i + 1]
                    break
        
        if not bot_name:
            raise HTTPException(status_code=400, detail="Bot name not found in request")
        
        if not validate_bot_name(bot_name):
            raise HTTPException(status_code=404, detail=f"Bot '{bot_name}' not found")
        
        ports = get_ports()
        port = ports.get(bot_name)
        
        success, response = await make_bot_request(
            port, 
            f"/bot/owner", 
            timeout=10
        )
        
        if not success:
            logger.warning(f"Failed to check ownership for bot {bot_name}: {response.get('error', 'Unknown error')}")
            raise HTTPException(
                status_code=503, 
                detail=f"Unable to verify bot ownership: {response.get('error', 'Bot not responding')}"
            )
                
        is_owner = response.get('id', 0) == int(current_user['discord_id'])
        if not is_owner:
            logger.info(f"Access denied: Discord user {current_user['discord_id']} is not owner of bot {bot_name}")
            raise HTTPException(
                status_code=403, 
                detail=f"Access denied. You are not the owner of bot '{bot_name}'"
            )
        
        logger.info(f"Bot {bot_name} accessed by owner {current_user['discord_id']} ({current_user['user_info'].get('username', 'Unknown')})")
        
        return await f(*args, **kwargs)
    
    return decorated_function

def require_seller_login(f):
    @wraps(f)
    async def decorated_function(*args, **kwargs):
        request = None
        for arg in args:
            if isinstance(arg, Request):
                request = arg
                break
        
        if not request:
            request = kwargs.get('request')
        
        if not request:
            raise HTTPException(status_code=500, detail="Request object not found")
        
        current_user = await get_current_user(request)
        if not current_user:
            raise HTTPException(
                status_code=401, 
                detail="Authentication required. Please login with Discord first.",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        # Check if user is a seller in any bot server
        is_seller_anywhere = await check_seller_status(current_user['discord_id'])
        
        if not is_seller_anywhere:
            logger.info(f"Access denied: Discord user {current_user['discord_id']} is not a seller in any server")
            raise HTTPException(
                status_code=403, 
                detail="Access denied. You are not a seller in any server."
            )
        
        logger.info(f"Seller access granted to {current_user['discord_id']} ({current_user['user_info'].get('username', 'Unknown')})")
        
        return await f(*args, **kwargs)
    
    return decorated_function

async def check_seller_status(discord_id: str) -> bool:
    """Check if a user is a seller in any bot server"""
    bots = await get_listing_bots()
    ports = get_ports()
    
    # Create concurrent tasks for all bots
    tasks = []
    
    for bot_name in bots:
        port = ports.get(bot_name)
        if port:
            task = make_bot_request(port, f"/seller/get/accounts?user_id={discord_id}", timeout=5)
            tasks.append(task)
    
    if not tasks:
        return False
    
    # Execute all requests concurrently
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Check if user is a seller in any server
    for result in results:
        if isinstance(result, Exception):
            continue
            
        success, data = result
        if success and data.get("seller") is True:
            return True
    
    return False

async def make_seller_requests(endpoint: str, method: str = "GET", data: Any = None) -> Dict:
    """Make requests to all bot servers for seller endpoints"""
    bots = await get_listing_bots()
    ports = get_ports()
    
    # Create concurrent tasks for all bots
    tasks = []
    bot_names = []
    
    for bot_name in bots:
        port = ports.get(bot_name)
        if port:
            if method == "POST":
                task = make_bot_request(port, endpoint, data=data, timeout=10)
            else:
                task = make_bot_request(port, endpoint, timeout=10)
            tasks.append(task)
            bot_names.append(bot_name)
    
    if not tasks:
        return {"success": False, "error": "No bots available", "results": {}}
    
    # Execute all requests concurrently
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Collect results from all servers
    server_results = {}
    successful_requests = 0
    
    for i, result in enumerate(results):
        bot_name = bot_names[i]
        
        if isinstance(result, Exception):
            server_results[bot_name] = {
                "success": False,
                "error": f"Request failed: {str(result)}"
            }
            continue
            
        success, response_data = result
        if success:
            successful_requests += 1
            server_results[bot_name] = {
                "success": True,
                "data": response_data
            }
        else:
            server_results[bot_name] = {
                "success": False,
                "error": response_data.get("error", "Unknown error")
            }
    
    return {
        "success": successful_requests > 0,
        "total_servers": len(bot_names),
        "successful_requests": successful_requests,
        "results": server_results
    }

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("authorized.html", {"request": request})

@app.get("/auth/discord/login")
async def discord_login(redirect_url: Optional[str] = None):
    """Start the Discord OAuth2 login flow"""
    # Use redirect_url directly as state parameter (or empty string if None)
    state = redirect_url or ""
    
    oauth_url = (
        f"{DISCORD_AUTHORIZE_URL}?"
        f"client_id={DISCORD_CLIENT_ID}&"
        f"response_type=code&"
        f"redirect_uri={DISCORD_REDIRECT_URI}&"
        f"scope=identify&"
        f"state={state}"
    )
    
    return RedirectResponse(oauth_url)

@app.get("/auth/discord/callback")
async def discord_callback(
    code: str, 
    state: Optional[str] = None
):
    """Handle the OAuth2 callback from Discord"""
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")
    
    try:
        # Exchange code for access token
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                DISCORD_TOKEN_URL,
                data={
                    'client_id': DISCORD_CLIENT_ID,
                    'client_secret': DISCORD_CLIENT_SECRET,
                    'grant_type': 'authorization_code',
                    'code': code,
                    'redirect_uri': DISCORD_REDIRECT_URI,
                    'scope': 'identify'
                },
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            
            if token_response.status_code != 200:
                logger.error(f"Discord token exchange failed: {token_response.text}")
                raise HTTPException(status_code=400, detail="Failed to retrieve access token")
            
            token_data = token_response.json()
            access_token = token_data['access_token']
            
            # Get user information
            user_response = await client.get(
                DISCORD_USER_URL,
                headers={'Authorization': f"Bearer {access_token}"}
            )
            
            if user_response.status_code != 200:
                logger.error(f"Discord user info fetch failed: {user_response.text}")
                raise HTTPException(status_code=400, detail="Failed to retrieve user information")
            
            user_info = user_response.json()
            discord_id = user_info['id']
            
            # Create session
            session_id = await app.sessions.create_session(discord_id, user_info)
            
            # Use state parameter as redirect URL (or default to "/")
            final_redirect_url = state if state else "/"
            redirect_response = RedirectResponse(url=final_redirect_url)
            
            # Set secure cookie with improved cross-domain support
            is_localhost = "localhost" in (state or "") or "127.0.0.1" in (state or "")
            is_noemt_domain = "noemt.dev" in (state or "")
            
            redirect_response.set_cookie(
                key="session_id",
                value=session_id,
                max_age=int(SESSION_LIFETIME.total_seconds()),
                httponly=True,
                samesite="none" if not is_localhost else "lax",
                secure=not is_localhost,  # Only secure for non-localhost
                domain=".noemt.dev" if is_noemt_domain and not is_localhost else None
            )
            
            logger.info(f"Set session cookie for user {discord_id} with domain: {'.noemt.dev' if is_noemt_domain and not is_localhost else 'None'}")
            
            return redirect_response
            
    except Exception as e:
        logger.error(f"Discord OAuth callback error: {e}")
        raise HTTPException(status_code=500, detail="Authentication failed")

@app.get("/auth/logout")
async def logout(request: Request, response: Response):
    """Log out the user by deleting their session"""
    session_id = request.cookies.get('session_id')
    if session_id:
        await app.sessions.delete_session(session_id)
    
    logout_response = RedirectResponse(url="/")
    logout_response.delete_cookie(key="session_id")
    return logout_response

@app.get("/auth/me")
async def get_current_user_info(current_user: Optional[Dict] = Depends(get_current_user)):
    """Get current user information"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    return {
        "discord_id": current_user["discord_id"],
        "user_info": current_user["user_info"],
        "authenticated": True
    }

@app.get("/auth/token")
async def get_cache_token(current_user: Optional[Dict] = Depends(get_current_user)):
    """Get cache token for authenticated user"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Generate cache token
    cache_token_data = {
        "session_id": current_user["session_id"],
        "discord_id": current_user["discord_id"],
        "expires_at": (datetime.now() + SESSION_LIFETIME).isoformat()
    }
    cache_token = base64.b64encode(json.dumps(cache_token_data).encode()).decode()
    
    return {
        "cache_token": cache_token,
        "discord_id": current_user["discord_id"],
        "expires_at": cache_token_data["expires_at"]
    }

@app.get("/auth/sessions/stats")
async def session_stats():
    """Get session statistics (for debugging/monitoring)"""
    active_sessions = await app.sessions.get_active_sessions_count()
    return {
        "active_sessions": active_sessions,
        "session_lifetime_hours": SESSION_LIFETIME.total_seconds() / 3600
    }

@app.get("/authorize")
async def auth(request: Request):
    """Handle OAuth authorization with improved error handling"""
    code = request.query_params.get('code')
    state = request.query_params.get('state')

    if not code or not state:
        return templates.TemplateResponse("error.html", {
            "request": request, 
            "error_message": "Missing required parameters"
        })

    try:
        application_id, bot_name = base64.b64decode(state).decode("utf-8").split(",")
    except (ValueError, UnicodeDecodeError):
        return templates.TemplateResponse("error.html", {
            "request": request, 
            "error_message": "Invalid state parameter"
        })
    
    ports = get_ports()
    port = ports.get(bot_name)
    if not port:
        return templates.TemplateResponse("error.html", {
            "request": request, 
            "error_message": "Bot server not found"
        })

    # Return the authorization template with the data needed for fingerprinting
    return templates.TemplateResponse("authorization.html", {
        "request": request,
        "code": code,
        "application_id": application_id,
        "bot_name": bot_name,
        "port": port
    })

@app.post("/authorize/callback")
async def auth_callback(request: Request):
    """Handle the POST callback with fingerprint data"""
    try:
        form_data = await request.form()
        code = form_data.get('code')
        application_id = form_data.get('application_id') 
        bot_name = form_data.get('bot_name')
        fingerprint = form_data.get('fingerprint')
        
        if not all([code, application_id, bot_name, fingerprint]):
            return templates.TemplateResponse("error.html", {
                "request": request,
                "error_message": "Missing required data"
            })
        
        ports = get_ports()
        port = ports.get(bot_name)
        if not port:
            return templates.TemplateResponse("error.html", {
                "request": request,
                "error_message": "Bot server not found"
            })

        ip_address = request.headers.get("CF-Connecting-IP", request.client.host)
        endpoint = f"/callback?code={code}&ip={ip_address}&app_id={application_id}"
        
        # Send fingerprint as POST data to the bot
        success, response = await make_bot_request(port, endpoint, data=fingerprint)
        
        if success and not response.get("error"):
            return templates.TemplateResponse("authorized.html", {"request": request})
        
        error_message = response.get("error", "An error occurred during authorization.")
        return templates.TemplateResponse("error.html", {
            "request": request, 
            "error_message": error_message
        })
        
    except Exception as e:
        logger.error(f"Authorization callback error: {e}")
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error_message": "Authorization processing failed"
        })

@app.get("/transcript/{bot_name}/{identifier}")
async def get_transcript(request: Request, bot_name: str, identifier: str):
    """Get transcript with seller authentication required"""
    current_user = await get_current_user(request)
    if not current_user:
        return RedirectResponse(url=f"/auth/discord/login?redirect_url=/transcript/{bot_name}/{identifier}")

    session_id = current_user.get("session_id")
    
    try:
        ports = get_ports()
        port = ports.get(bot_name)
        if not port:
            if session_id:
                await app.sessions.delete_session(session_id)
            return RedirectResponse(url="https://www.youtube.com/shorts/cU060_vSuf0")

        user_id = current_user["discord_id"]
        success, seller_check = await make_bot_request(port, f"/seller?user_id={user_id}", timeout=5)
        
        if not success:
            if session_id:
                await app.sessions.delete_session(session_id)
            return RedirectResponse(url="https://www.youtube.com/shorts/cU060_vSuf0")
        
        if not seller_check.get("response"):
            logger.info(f"Access denied: Discord user {user_id} is not a seller in bot {bot_name}")
            if session_id:
                await app.sessions.delete_session(session_id)
            return RedirectResponse(url="https://www.youtube.com/shorts/cU060_vSuf0")

        success, response = await make_bot_request(port, f"/transcript/{identifier}.html")
        
        if not success:
            if session_id:
                await app.sessions.delete_session(session_id)
            return RedirectResponse(url="https://www.youtube.com/shorts/cU060_vSuf0")
        
        if not response.get("response"):
            if session_id:
                await app.sessions.delete_session(session_id)
            return RedirectResponse(url="https://www.youtube.com/shorts/cU060_vSuf0")
            
        transcript_html = response.get("response")
        logger.info(f"Transcript {identifier} accessed by seller {user_id} in bot {bot_name}")
        return HTMLResponse(content=transcript_html)
        
    except Exception as e:
        logger.error(f"Transcript access error: {e}")
        if session_id:
            await app.sessions.delete_session(session_id)
        return RedirectResponse(url="https://www.youtube.com/shorts/cU060_vSuf0")

@app.get("/bot/extend")
async def extend_bot(
    email: str,
    days: int = Query(..., gt=0, description="Number of days to extend"),
    api_key: str = None
):
    """Extend a bot's usage by a specified number of days, identifying the bot by its email address."""
    # Verify API key for security
    if api_key != APP_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")
    
    if days <= 0:
        raise HTTPException(status_code=400, detail="Days must be a positive number")
    
    # Find bot by email efficiently
    target_bot, target_port = await find_bot_by_email(email)
    
    if not target_bot or not target_port:
        raise HTTPException(status_code=404, detail=f"No bot found with email: {email}")
    
    # Call the extension endpoint on the found bot
    success, response = await make_bot_request(target_port, f"/bot/extend?days={days}")
    
    if not success:
        error_detail = response.get("detail", response.get("error", "Unknown error"))
        raise HTTPException(status_code=500, detail=f"Failed to extend bot: {error_detail}")
    
    return {
        "success": True,
        "bot_name": target_bot,
        "days_extended": days,
        "result": response
    }
    

@app.get("/ai/credits/add")
async def ai_credits_add(
    email: str,
    credits: int = Query(..., gt=0, description="Number of queries to add"),
    api_key: str = None
):
    """Add AI credits to a bot, identifying the bot by its email address."""
    # Verify API key for security
    if api_key != APP_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")
    
    if credits <= 0:
        raise HTTPException(status_code=400, detail="Credits must be a positive number")
    
    # Find bot by email efficiently
    target_bot, target_port = await find_bot_by_email(email)
    
    if not target_bot or not target_port:
        raise HTTPException(status_code=404, detail=f"No bot found with email: {email}")
    
    # Call the credits endpoint on the found bot
    success, response = await make_bot_request(target_port, f"/ai/credits/add?credits={credits}")
    
    if not success:
        error_detail = response.get("detail", response.get("error", "Unknown error"))
        raise HTTPException(status_code=500, detail=f"Failed to add credits: {error_detail}")
    
    return {
        "success": True,
        "bot_name": target_bot,
        "applied_credits": credits,
        "result": response
    }


@app.get("/stats/{bot_name}")
async def get_bot_stats(bot_name: str, api_key: Optional[str] = None):
    """Get comprehensive statistics for a specific bot."""
    # Validate the bot name exists
    ports = get_ports()
    port = ports.get(bot_name)
    
    if not port:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_name}' not found")
    
    # Build the endpoint with optional API key
    endpoint = "/stats"
    if api_key:
        endpoint += f"?key={api_key}"
    
    success, response = await make_bot_request(port, endpoint)
    
    if not success:
        if "not responding" in response.get("error", ""):
            raise HTTPException(status_code=503, detail=f"Bot '{bot_name}' is not responding")
        else:
            error_detail = response.get("error", "Unknown error")
            raise HTTPException(status_code=500, detail=f"Failed to fetch stats: {error_detail}")
    
    return {
        "bot_name": bot_name,
        "stats": response
    }
    
# Optimized log storage with better memory management
class LogStorage:
    def __init__(self, max_entries: int = 1000):
        self._data_fetch_logs: List[Dict] = []
        self._command_logs: List[Dict] = []
        self.max_entries = max_entries
        self._lock = asyncio.Lock()
        
    async def add_data_fetch(self, log_entry: Dict) -> Dict:
        async with self._lock:
            self._data_fetch_logs.append(log_entry)
            if len(self._data_fetch_logs) > self.max_entries:
                # Remove oldest entries more efficiently
                excess = len(self._data_fetch_logs) - self.max_entries
                self._data_fetch_logs = self._data_fetch_logs[excess:]
        return log_entry
        
    async def add_command(self, log_entry: Dict) -> Dict:
        async with self._lock:
            self._command_logs.append(log_entry)
            if len(self._command_logs) > self.max_entries:
                # Remove oldest entries more efficiently
                excess = len(self._command_logs) - self.max_entries
                self._command_logs = self._command_logs[excess:]
        return log_entry
    
    def get_recent_data_fetches(self, limit: int = 50) -> List[Dict]:
        return self._data_fetch_logs[-limit:] if self._data_fetch_logs else []
    
    def get_recent_commands(self, limit: int = 50) -> List[Dict]:
        return self._command_logs[-limit:] if self._command_logs else []

# Optimized connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            self.active_connections.discard(websocket)

    async def broadcast(self, message: Dict):
        if not self.active_connections:
            return
            
        # Create a copy of connections to avoid modification during iteration
        connections = self.active_connections.copy()
        
        # Send to all connections concurrently
        tasks = []
        for connection in connections:
            tasks.append(self._safe_send(connection, message))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _safe_send(self, websocket: WebSocket, message: Dict):
        try:
            await websocket.send_json(message)
        except Exception:
            # Remove disconnected websockets
            await self.disconnect(websocket)

# Initialize the storage and connection manager
log_storage = LogStorage()
manager = ConnectionManager()

# Add the POST endpoints for logging data
@app.post("/live/data-fetch")
async def log_data_fetch(data: dict):
    """Log Minecraft data fetch operations with optimized processing."""
    timestamp = datetime.now().isoformat()
    log_entry = {
        "timestamp": timestamp,
        "type": "data_fetch",
        "uuid": data.get("uuid"),
        "username": data.get("username")
    }
    
    # Use async method for thread-safe logging
    await log_storage.add_data_fetch(log_entry)
    
    # Broadcast to all connected WebSocket clients
    await manager.broadcast({
        "event": "new_data_fetch",
        "data": log_entry
    })
    
    return {"success": True, "timestamp": timestamp}

@app.post("/live/command-execution")
async def log_command_execution(data: dict):
    """Log Discord bot command executions with optimized processing."""
    timestamp = datetime.now().isoformat()
    log_entry = {
        "timestamp": timestamp,
        "type": "command",
        "command": data.get("command"),
        "guild_id": data.get("guild_id"),
        "user": data.get("user")
    }
    
    # Use async method for thread-safe logging
    await log_storage.add_command(log_entry)
    
    # Broadcast to all connected WebSocket clients
    await manager.broadcast({
        "event": "new_command",
        "data": log_entry
    })
    
    return {"success": True, "timestamp": timestamp}

@app.websocket("/ws/logs")
async def websocket_endpoint(websocket: WebSocket):
    """Optimized WebSocket endpoint for real-time logs"""
    await manager.connect(websocket)
    try:
        while True:
            try:
                message = await asyncio.wait_for(websocket.receive_json(), timeout=60.0)
            except asyncio.TimeoutError:
                # Send heartbeat
                await websocket.send_json({"event": "heartbeat", "timestamp": time.time()})
                continue
            
            if message.get("type") == "get_recent":
                log_type = message.get("log_type", "all")
                limit = min(int(message.get("limit", 50)), 1000)
                
                if log_type == "data_fetch" or log_type == "all":
                    await websocket.send_json({
                        "event": "recent_data_fetches",
                        "data": log_storage.get_recent_data_fetches(limit)
                    })
                
                if log_type == "command" or log_type == "all":
                    await websocket.send_json({
                        "event": "recent_commands",
                        "data": log_storage.get_recent_commands(limit)
                    })
            
            elif message.get("type") == "ping":
                await websocket.send_json({"event": "pong", "timestamp": time.time()})
            
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await manager.disconnect(websocket)

@lru_cache(maxsize=1)
def xor_data(data: str) -> bytearray:
    key = ""
    if isinstance(data, str):
        data = data.encode('utf-8')
    key_bytes = key.encode() if isinstance(key, str) else key
    
    xored_bytes = bytearray(len(data))
    for i in range(len(data)):
        xored_bytes[i] = data[i] ^ key_bytes[i % len(key_bytes)]
    
    return xored_bytes

@app.get("/dash/{bot_name}")
@require_login
async def dashboard(request: Request, bot_name: str):
    """Dashboard endpoint with improved error handling and validation"""

    bots = await get_listing_bots()
    if bot_name not in bots:
        raise HTTPException(status_code=404, detail="Bot not found")
    
    ports = get_ports()
    port = ports.get(bot_name)
    if not port:
        raise HTTPException(status_code=404, detail="Port not found for the bot")
    
    success, response = await make_bot_request(port, "/stats")
    
    if not success:
        if "not responding" in response.get("error", ""):
            raise HTTPException(status_code=503, detail="Bot is not responding")
        else:
            error_detail = response.get("error", "Unknown error")
            raise HTTPException(status_code=500, detail=f"Error fetching stats: {error_detail}")
    
    return response

@app.get("/redirect")
async def redirect_to_url(request: Request, url: str):
    """Redirect to a specified URL with improved validation."""
    if not url:
        raise HTTPException(status_code=400, detail="URL parameter is required")
    
    try:
        decoded_url = base64.b64decode(url).decode('utf-8')
        return RedirectResponse(url=decoded_url)
    except Exception as e:
        logger.error(f"URL decoding error: {e}")
        raise HTTPException(status_code=400, detail="Invalid URL encoding")

@app.get("/mint")
async def mint(request: Request):
    return templates.TemplateResponse("mint.html", {"request": request})

def validate_bot_name(bot_name: str) -> bool:
    """Helper function to validate if a bot name exists"""
    try:
        ports = get_ports()
        return bot_name in ports
    except Exception:
        return False

@app.get("/api/bot/{bot_name}/auth/bots")
@require_login
async def get_auth_bots(
    request: Request, 
    bot_name: str
):
    ports = get_ports()
    port = ports.get(bot_name)
    
    if not port:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_name}' not found")

    success, response = await make_bot_request(port, "/auth/bots")

    if not success:
        if "not responding" in response.get("error", ""):
            raise HTTPException(status_code=503, detail=f"Bot '{bot_name}' is not responding")
        else:
            error_detail = response.get("error", "Unknown error")
            raise HTTPException(status_code=500, detail=f"Failed to fetch stats: {error_detail}")
        
    return response

@app.get("/api/bot/{bot_name}/auth/users")
@require_login
async def get_auth_users(
    request: Request,
    bot_name: str
):
    ports = get_ports()
    port = ports.get(bot_name)

    if not port:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_name}' not found")

    success, response = await make_bot_request(port, "/auth/users")

    if not success:
        if "not responding" in response.get("error", ""):
            raise HTTPException(status_code=503, detail=f"Bot '{bot_name}' is not responding")
        else:
            error_detail = response.get("error", "Unknown error")
            raise HTTPException(status_code=500, detail=f"Failed to fetch stats: {error_detail}")

    return response

@app.get("/api/bot/{bot_name}/listed/items")
@require_login
async def get_listed_items(
    request: Request,
    bot_name: str
):
    ports = get_ports()
    port = ports.get(bot_name)

    if not port:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_name}' not found")

    success, response = await make_bot_request(port, "/listed/items")

    if not success:
        if "not responding" in response.get("error", ""):
            raise HTTPException(status_code=503, detail=f"Bot '{bot_name}' is not responding")
        else:
            error_detail = response.get("error", "Unknown error")
            raise HTTPException(status_code=500, detail=f"Failed to fetch stats: {error_detail}")

    return response

@app.get("/api/bot/{bot_name}/auth/actions")
@require_login
async def get_auth_actions(
    request: Request,
    bot_name: str
):
    ports = get_ports()
    port = ports.get(bot_name)

    if not port:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_name}' not found")

    success, response = await make_bot_request(port, "/auth/actions")

    if not success:
        if "not responding" in response.get("error", ""):
            raise HTTPException(status_code=503, detail=f"Bot '{bot_name}' is not responding")
        else:
            error_detail = response.get("error", "Unknown error")
            raise HTTPException(status_code=500, detail=f"Failed to fetch stats: {error_detail}")

    return response

@app.get("/api/bot/{bot_name}/shop/info")
async def get_shop_info(
    request: Request,
    bot_name: str
):
    ports = get_ports()
    port = ports.get(bot_name)

    if not port:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_name}' not found")

    success, response = await make_bot_request(port, "/shop/info")

    if not success:
        if "not responding" in response.get("error", ""):
            raise HTTPException(status_code=503, detail=f"Bot '{bot_name}' is not responding")
        else:
            error_detail = response.get("error", "Unknown error")
            raise HTTPException(status_code=500, detail=f"Failed to fetch shop info: {error_detail}")

    return response

@app.get("/api/{bot_name}/initialize/website/ticket/open")
async def open_ticket(
    request: Request,
    bot_name: str
):
    ports = get_ports()
    port = ports.get(bot_name)

    if not port:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_name}' not found")

    success, response = await make_bot_request(port, "/initialize/website/ticket/open")

    if not success:
        if "not responding" in response.get("error", ""):
            raise HTTPException(status_code=503, detail=f"Bot '{bot_name}' is not responding")
        else:
            error_detail = response.get("error", "Unknown error")
            raise HTTPException(status_code=500, detail=f"Failed to fetch shop info: {error_detail}")

    return response

@app.post("/api/bot/{bot_name}/verify/user")
@require_login
async def verify_user(
    request: Request,
    bot_name: str
):
    ports = get_ports()
    port = ports.get(bot_name)

    if not port:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_name}' not found")

    # Get request body with user verification data
    try:
        request_data = await request.json()
        
        action_id = request_data.get("action_id")
        
        if not action_id:
            raise HTTPException(
                status_code=400, 
                detail="action_id is required"
            )
        
        # Validate that action_id can be converted to integer
        try:
            int(action_id)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="action_id must be a valid integer"
            )
    
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON in request body")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error processing request: {str(e)}")

    # Forward the request to the bot with POST data
    success, response = await make_bot_request(port, "/verify/user", data=request_data)

    if not success:
        if "not responding" in response.get("error", ""):
            raise HTTPException(status_code=503, detail=f"Bot '{bot_name}' is not responding")
        else:
            error_detail = response.get("error", "Unknown error")
            raise HTTPException(status_code=500, detail=f"Failed to verify user: {error_detail}")

    return response


@app.post("/api/bot/{bot_name}/unlist/item")
@require_login
async def unlist_item(
    request: Request,
    bot_name: str
):
    ports = get_ports()
    port = ports.get(bot_name)

    if not port:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_name}' not found")

    # Get request body with channel_id and message_id
    try:
        request_data = await request.json()
        
        channel_id = request_data.get("channel_id")
        message_id = request_data.get("message_id")
        
        if not channel_id or not message_id:
            raise HTTPException(
                status_code=400, 
                detail="Both channel_id and message_id are required"
            )
        
        # Validate that they can be converted to integers
        try:
            int(channel_id)
            int(message_id)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="channel_id and message_id must be valid integers"
            )
    
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON in request body")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error processing request: {str(e)}")

    # Forward the request to the bot with POST data
    success, response = await make_bot_request(port, "/unlist/item", data=request_data)

    if not success:
        if "not responding" in response.get("error", ""):
            raise HTTPException(status_code=503, detail=f"Bot '{bot_name}' is not responding")
        else:
            error_detail = response.get("error", "Unknown error")
            raise HTTPException(status_code=500, detail=f"Failed to unlist item: {error_detail}")

    return response

@app.post("/api/bot/{bot_name}/users/info")
async def get_users_info(
    request: Request,
    bot_name: str
):
    ports = get_ports()
    port = ports.get(bot_name)

    if not port:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_name}' not found")

    # Get request body with user IDs
    try:
        request_data = await request.json()
        
        # Support both direct list format and object format with 'users' key
        if isinstance(request_data, list):
            user_ids = request_data
        elif isinstance(request_data, dict) and 'users' in request_data:
            user_ids = request_data['users']
        else:
            raise HTTPException(
                status_code=400, 
                detail="Request body must be a list of user IDs or an object with a 'users' field containing a list"
            )
        
        if not user_ids or not isinstance(user_ids, list):
            raise HTTPException(
                status_code=400, 
                detail="User IDs must be provided as a non-empty list"
            )
        
        # Validate user IDs are strings or integers
        for user_id in user_ids:
            if not isinstance(user_id, (str, int)):
                raise HTTPException(
                    status_code=400,
                    detail="All user IDs must be strings or integers"
                )
    
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON in request body")
    except HTTPException:
        raise  # Re-raise our custom HTTP exceptions
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error processing request: {str(e)}")

    # Forward the request to the bot with POST data (send as list directly to match bot's expected format)
    success, response = await make_bot_request(port, "/users/info", data=user_ids)
    
    if not success:
        if "not responding" in response.get("error", ""):
            raise HTTPException(status_code=503, detail=f"Bot '{bot_name}' is not responding")
        else:
            error_detail = response.get("error", "Unknown error")
            raise HTTPException(status_code=500, detail=f"Failed to fetch user info: {error_detail}")

    return response

@app.get("/api/bot/{bot_name}/config")
@require_login
async def get_bot_config(
    request: Request,
    bot_name: str
):
    """Get bot configuration settings"""
    ports = get_ports()
    port = ports.get(bot_name)

    if not port:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_name}' not found")

    success, response = await make_bot_request(port, "/config")

    if not success:
        if "not responding" in response.get("error", ""):
            raise HTTPException(status_code=503, detail=f"Bot '{bot_name}' is not responding")
        else:
            error_detail = response.get("error", "Unknown error")
            raise HTTPException(status_code=500, detail=f"Failed to fetch configuration: {error_detail}")

    return response

@app.post("/api/bot/{bot_name}/config")
@require_login
async def update_bot_config(
    request: Request,
    bot_name: str
):
    """Update bot configuration settings"""
    ports = get_ports()
    port = ports.get(bot_name)

    if not port:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_name}' not found")

    # Get request body with configuration updates
    try:
        request_data = await request.json()
        
        if not request_data or not isinstance(request_data, dict):
            raise HTTPException(
                status_code=400, 
                detail="Request body must be a JSON object with configuration updates"
            )
        
        # Validate the structure of each config item
        for config_key, config_data in request_data.items():
            if not isinstance(config_data, dict):
                raise HTTPException(
                    status_code=400,
                    detail=f"Configuration data for '{config_key}' must be an object"
                )
            
            if config_data.get("value") is not None and "type" not in config_data:
                raise HTTPException(
                    status_code=400,
                    detail=f"Configuration item '{config_key}' must include 'type' field when value is provided"
                )
    
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON in request body")
    except HTTPException:
        raise  # Re-raise our custom HTTP exceptions
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error processing request: {str(e)}")

    # Forward the request to the bot with POST data
    success, response = await make_bot_request(port, "/config", data=request_data)

    if not success:
        if "not responding" in response.get("error", ""):
            raise HTTPException(status_code=503, detail=f"Bot '{bot_name}' is not responding")
        else:
            error_detail = response.get("error", "Unknown error")
            raise HTTPException(status_code=500, detail=f"Failed to update configuration: {error_detail}")

    return response

@app.get("/api/bot/{bot_name}/channels")
@require_login
async def get_bot_channels(
    request: Request,
    bot_name: str
):
    """Get guild channels and categories"""
    ports = get_ports()
    port = ports.get(bot_name)

    if not port:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_name}' not found")

    success, response = await make_bot_request(port, "/channels")

    if not success:
        if "not responding" in response.get("error", ""):
            raise HTTPException(status_code=503, detail=f"Bot '{bot_name}' is not responding")
        else:
            error_detail = response.get("error", "Unknown error")
            raise HTTPException(status_code=500, detail=f"Failed to fetch channels: {error_detail}")

    return response

@app.get("/api/bot/{bot_name}/roles")
@require_login
async def get_bot_roles(
    request: Request,
    bot_name: str
):
    """Get guild roles"""
    ports = get_ports()
    port = ports.get(bot_name)

    if not port:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_name}' not found")

    success, response = await make_bot_request(port, "/roles")

    if not success:
        if "not responding" in response.get("error", ""):
            raise HTTPException(status_code=503, detail=f"Bot '{bot_name}' is not responding")
        else:
            error_detail = response.get("error", "Unknown error")
            raise HTTPException(status_code=500, detail=f"Failed to fetch channels: {error_detail}")

    return response

async def make_seller_requests(endpoint: str, method: str = "GET", data: dict = None):
    """Make requests to all bot servers for seller operations"""
    ports = get_ports()
    
    if not ports:
        return {"error": "No bot servers configured", "results": {}}
    
    # Create tasks for all bot requests
    tasks = []
    bot_names = []
    
    for bot_name, port in ports.items():
        if method == "POST":
            task = make_bot_request(port, endpoint, timeout=10, data=data)
        else:
            task = make_bot_request(port, endpoint, timeout=10)
        tasks.append(task)
        bot_names.append(bot_name)
    
    responses = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Process results
    results = {
        "total_servers": len(ports),
        "successful_requests": 0,
        "failed_requests": 0,
        "servers": {}
    }
    
    for i, (bot_name, response) in enumerate(zip(bot_names, responses)):
        if isinstance(response, Exception):
            results["servers"][bot_name] = {
                "success": False,
                "error": f"Request failed: {str(response)}"
            }
            results["failed_requests"] += 1
        else:
            success, data = response
            if success:
                results["servers"][bot_name] = {
                    "success": True,
                    "data": data
                }
                results["successful_requests"] += 1
            else:
                results["servers"][bot_name] = {
                    "success": False,
                    "error": data.get("error", "Unknown error")
                }
                results["failed_requests"] += 1
    
    return results

# Seller endpoints - these send requests to all servers
@app.get("/api/seller/accounts")
@require_seller_login
async def get_seller_accounts(request: Request):
    """Get seller accounts from all servers"""
    current_user = await get_current_user(request)
    user_id = current_user["discord_id"]
    
    endpoint = f"/seller/get/accounts?user_id={user_id}"
    results = await make_seller_requests(endpoint)
    
    return results

@app.get("/api/accounts/all")
async def get_all_accounts(request: Request, api_key: str = None):
    """Get all accounts from all servers"""
    if not api_key or api_key != APP_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")
    
    data = {}
    
    ports = get_ports()
    bots = await get_listing_bots()
    for bot in bots:
        port = ports.get(bot)
        results_bot = await make_bot_request(port, "/api/accounts/all")
        data[bot] = results_bot

    return data

@app.get("/api/seller/configuration")
@require_seller_login
async def get_seller_configuration(request: Request):
    """Get seller configuration from all servers"""
    current_user = await get_current_user(request)
    user_id = current_user["discord_id"]
    
    endpoint = f"/seller/get/configuration?user_id={user_id}"
    results = await make_seller_requests(endpoint)
    
    return results

@app.post("/api/seller/configuration")
@require_seller_login
async def update_seller_configuration(request: Request):
    """Update seller configuration on all servers"""
    current_user = await get_current_user(request)
    user_id = current_user["discord_id"]
    
    # Get request body
    try:
        request_data = await request.json()
        
        if not request_data or not isinstance(request_data, dict):
            raise HTTPException(
                status_code=400, 
                detail="Request body must be a JSON object with configuration updates"
            )
        
        # Add user_id to the request data
        request_data["user_id"] = user_id
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON in request body")
    except HTTPException:
        raise  # Re-raise our custom HTTP exceptions
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error processing request: {str(e)}")
    
    # Send update request to all servers
    endpoint = "/seller/update/configuration"
    results = await make_seller_requests(endpoint, method="POST", data=request_data)
    
    return results

@app.post("/api/seller/list")
@require_seller_login
async def list_seller_item(request: Request):
    """List an item on all servers"""
    current_user = await get_current_user(request)
    user_id = current_user["discord_id"]
    
    # Get request body
    try:
        request_data = await request.json()
        
        if not request_data or not isinstance(request_data, dict):
            raise HTTPException(
                status_code=400, 
                detail="Request body must be a JSON object with item data"
            )
        
        # Validate required fields
        item_type = request_data.get("type")
        item_data = request_data.get("item")
        
        if not item_type:
            raise HTTPException(
                status_code=400,
                detail="type is required (account, profile, or alt)"
            )
            
        if not item_data or not isinstance(item_data, dict):
            raise HTTPException(
                status_code=400,
                detail="item data is required and must be an object"
            )
        
        # Validate item_type
        if item_type not in ["account", "profile", "alt"]:
            raise HTTPException(
                status_code=400,
                detail="type must be 'account', 'profile', or 'alt'"
            )
        
        # Validate required item fields
        username = item_data.get("username")
        price = item_data.get("price")
        
        if not username:
            raise HTTPException(
                status_code=400,
                detail="username is required in item data"
            )
            
        if price is None or not isinstance(price, (int, float)) or price < 0:
            raise HTTPException(
                status_code=400,
                detail="price must be a non-negative number"
            )
        
        # Add user_id to the request data
        request_data["user_id"] = user_id
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON in request body")
    except HTTPException:
        raise  # Re-raise our custom HTTP exceptions
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error processing request: {str(e)}")
    
    # Send list request to all servers
    endpoint = "/seller/list/item"
    results = await make_seller_requests(endpoint, method="POST", data=request_data)
    
    return results

@app.post("/api/upload/attachment")
async def upload_attachment(request: Request):
    """Upload attachment and return URL - API key protected"""
    # Check API key
    api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    if api_key != APP_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")
    
    try:
        # Get the uploaded file data
        form_data = await request.form()
        file = form_data.get("file")
        filename = form_data.get("filename")
        attachment_id = form_data.get("attachment_id")
        
        if not file:
            raise HTTPException(status_code=400, detail="No file provided")
        
        if not filename:
            raise HTTPException(status_code=400, detail="No filename provided")
        
        if not attachment_id:
            raise HTTPException(status_code=400, detail="No attachment_id provided")
        
        # Read file content
        file_content = await file.read()
        
        if not file_content:
            raise HTTPException(status_code=400, detail="File is empty")
        
        # Create filename with attachment ID
        safe_filename = f"{attachment_id}_{filename}"
        
        # Create uploads directory if it doesn't exist
        uploads_dir = os.path.join("static", "uploads")
        os.makedirs(uploads_dir, exist_ok=True)
        
        # Save file to static/uploads directory
        file_path = os.path.join(uploads_dir, safe_filename)
        
        with open(file_path, "wb") as f:
            f.write(file_content)
        
        # Determine content type based on file extension
        content_type = "application/octet-stream"  # Default
        if safe_filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
            content_type = f"image/{safe_filename.split('.')[-1].lower()}"
        elif safe_filename.lower().endswith('.txt'):
            content_type = "text/plain"
        elif safe_filename.lower().endswith('.pdf'):
            content_type = "application/pdf"
        elif safe_filename.lower().endswith(('.mp4', '.mov', '.avi')):
            content_type = f"video/{safe_filename.split('.')[-1].lower()}"
        elif safe_filename.lower().endswith(('.mp3', '.wav', '.ogg')):
            content_type = f"audio/{safe_filename.split('.')[-1].lower()}"
        
        logger.info(f"Uploaded attachment: {safe_filename} ({len(file_content)} bytes)")
        
        return Response(
            content=file_content,
            media_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(file_content))
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading attachment: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to upload attachment: {str(e)}")
    

@app.get("/api/check-domain")
async def check_domain(domain: str = Query(...)):
    """
    This endpoint is called by Caddy to ask for permission before
    issuing an SSL certificate for a custom domain.
    """
    if not domain:
        raise HTTPException(status_code=400, detail="Domain parameter is required.")

    approved_domains = load_approved_domains()
    
    if domain.lower() in approved_domains:
        logger.info(f"Domain check PASSED for: {domain}")
        return Response(status_code=200, content="Domain is approved.")
    else:
        logger.warning(f"Domain check FAILED for unauthorized domain: {domain}")
        raise HTTPException(status_code=403, detail="Domain is not authorized for this service.")
    
async def find_bot_by_domain(domain: str) -> Tuple[Optional[str], Optional[int]]:
    """
    Find a bot by domain efficiently using concurrent requests
    Returns: (bot_name, port) or (None, None) if not found
    """
    bots = await get_listing_bots()
    ports = get_ports()
    
    tasks = []
    bot_port_pairs = []
    
    for bot_name in bots:
        port = ports.get(bot_name)
        if port:
            task = make_bot_request(port, "/api/domain", timeout=5)
            tasks.append(task)
            bot_port_pairs.append((bot_name, port))
    
    if not tasks:
        return None, None
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            continue
            
        success, data = result
        if success:
            bot_domain = data.get("domain")
            if bot_domain and bot_domain.lower() == domain.lower():
                bot_name, port = bot_port_pairs[i]
                return bot_name, port
    
    return None, None


@app.get("/custom/bot/name")
async def get_bot_name_for_domain(request: Request):
    """
    Returns the bot name associated with the current custom domain.
    Only works for custom domains - automatically detects bot from domain.
    """
    host = request.headers.get("origin", "v2.noemt.dev")
    if host.startswith("http://"):
        host = host[len("http://"):]
    elif host.startswith("https://"):
        host = host[len("https://"):]
    
    if not host or host in ["v2.noemt.dev", "noemt.dev", "localhost:7000", "localhost:3000"]:
        raise HTTPException(status_code=404, detail="This endpoint is only available for custom domains.")
    
    bot_name, _ = await find_bot_by_domain(host)
    
    if not bot_name:
        raise HTTPException(status_code=404, detail=f"No bot found for domain '{host}'.")
    
    return {"name": bot_name}


@app.get("/static/{full_path:path}")
async def flexible_static_endpoint(request: Request, full_path: str):
    """
    Serves static files from local directory if they exist, otherwise proxies to React server.
    This works for both main domains and custom domains.
    """
    local_file_path = os.path.join("static", full_path)
    
    if os.path.isfile(local_file_path):
        try:
            content_type = "application/octet-stream"
            if full_path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                ext = full_path.split('.')[-1].lower()
                content_type = f"image/{ext}"
            elif full_path.lower().endswith('.css'):
                content_type = "text/css"
            elif full_path.lower().endswith('.js'):
                content_type = "application/javascript"
            elif full_path.lower().endswith('.txt'):
                content_type = "text/plain"
            elif full_path.lower().endswith('.json'):
                content_type = "application/json"
            elif full_path.lower().endswith('.pdf'):
                content_type = "application/pdf"
            
            with open(local_file_path, "rb") as f:
                content = f.read()
            
            return Response(
                content=content,
                media_type=content_type,
                headers={
                    "Content-Length": str(len(content)),
                    "Cache-Control": "public, max-age=3600"
                }
            )
        except Exception as e:
            logger.error(f"Error serving local static file {full_path}: {e}")
    
    host = request.headers.get("host")
    
    if host and host not in ["v2.noemt.dev", "noemt.dev", "localhost:7000"]:
        bot_name, _ = await find_bot_by_domain(host)
        if not bot_name:
            raise HTTPException(status_code=404, detail=f"Domain '{host}' is not configured for our service.")
    
    target_url = f"http://{SHOP_FRONTEND_HOST}:{SHOP_FRONTEND_PORT}/static/{full_path}"
    
    try:
        url = httpx.URL(target_url, params=request.query_params)
        headers = dict(request.headers)
        headers["host"] = f"{SHOP_FRONTEND_HOST}:{SHOP_FRONTEND_PORT}"
        
        async with httpx.AsyncClient() as client:
            req = client.build_request(
                method=request.method,
                url=url,
                headers=headers,
                content=await request.body()
            )
            
            resp = await client.send(req, stream=True)
            
            content_type = resp.headers.get("content-type", "application/octet-stream")
            
            excluded_headers = ["content-encoding", "transfer-encoding"]
            response_headers = {}
            
            for key, value in resp.headers.items():
                if key.lower() not in excluded_headers:
                    response_headers[key] = value
            
            response_headers["Access-Control-Allow-Origin"] = "*"
            
            content = await resp.aread()
            response_headers["Content-Length"] = str(len(content))
            
            return Response(
                content=content,
                status_code=resp.status_code,
                headers=response_headers,
                media_type=content_type
            )
    
    except httpx.RequestError as e:
        logger.error(f"Failed to proxy static file {full_path}: {e}")
        raise HTTPException(status_code=502, detail="Could not contact the backend service.")
    except Exception as e:
        logger.error(f"Unexpected error serving static file {full_path}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error.")


proxy_client = httpx.AsyncClient()

@app.api_route("/static/{full_path:path}", include_in_schema=False)
async def custom_domain_static_proxy(request: Request, full_path: str):
    """
    Handles static asset requests for custom domains by proxying directly to the shop frontend
    without the bot name prefix since static assets are served at the root level.
    """
    host = request.headers.get("host")

    if not host or host in ["v2.noemt.dev", "noemt.dev"]:
        raise HTTPException(
            status_code=404, 
            detail="Endpoint not found."
        )

    bot_name, _ = await find_bot_by_domain(host)
    if not bot_name:
        return Response(
            content=f"Domain '{host}' is not configured for our service.", 
            status_code=404
        )

    target_url = f"http://{SHOP_FRONTEND_HOST}:{SHOP_FRONTEND_PORT}/static/{full_path}"
    
    print(f"Static asset request: /static/{full_path}")
    print(f"Target URL: {target_url}")

    try:
        url = httpx.URL(target_url, params=request.query_params)
        headers = dict(request.headers)
        
        headers["host"] = f"{SHOP_FRONTEND_HOST}:{SHOP_FRONTEND_PORT}"
        
        req = proxy_client.build_request(
            method=request.method,
            url=url,
            headers=headers,
            content=await request.body()
        )
        
        print(f"Proxying static asset {request.method} {target_url}")
        resp = await proxy_client.send(req, stream=True)
        
        content_type = resp.headers.get("content-type", "application/octet-stream")
        print(f"Static asset response: {resp.status_code}, Content-Type: {content_type}")
        
        excluded_headers = ["content-encoding", "transfer-encoding"]
        response_headers = {}
        
        for key, value in resp.headers.items():
            if key.lower() not in excluded_headers:
                response_headers[key] = value
        
        response_headers["Access-Control-Allow-Origin"] = "*"
        
        content = await resp.aread()
        response_headers["Content-Length"] = str(len(content))
        
        return Response(
            content=content,
            status_code=resp.status_code,
            headers=response_headers,
            media_type=content_type
        )

    except httpx.RequestError as e:
        logger.error(f"Failed to proxy static asset request for '{host}' to '{target_url}': {e}")
        raise HTTPException(status_code=502, detail="Could not contact the backend shop service.")
    except Exception as e:
        logger.error(f"Unexpected error proxying static asset request for '{host}': {e}")
        raise HTTPException(status_code=500, detail="Internal server error during proxying.")

@app.api_route("/assets/{full_path:path}", include_in_schema=False)
async def custom_domain_assets_proxy(request: Request, full_path: str):
    """
    Handles /assets/ requests for custom domains.
    """
    host = request.headers.get("host")

    if not host or host in ["v2.noemt.dev", "noemt.dev"]:
        raise HTTPException(status_code=404, detail="Endpoint not found.")

    bot_name, _ = await find_bot_by_domain(host)
    if not bot_name:
        return Response(
            content=f"Domain '{host}' is not configured for our service.", 
            status_code=404
        )

    target_url = f"http://{SHOP_FRONTEND_HOST}:{SHOP_FRONTEND_PORT}/assets/{full_path}"
    
    print(f"Assets request: /assets/{full_path}")
    print(f"Target URL: {target_url}")

    try:
        url = httpx.URL(target_url, params=request.query_params)
        headers = dict(request.headers)
        headers["host"] = f"{SHOP_FRONTEND_HOST}:{SHOP_FRONTEND_PORT}"
        
        req = proxy_client.build_request(
            method=request.method,
            url=url,
            headers=headers,
            content=await request.body()
        )
        
        resp = await proxy_client.send(req, stream=True)
        
        content_type = resp.headers.get("content-type", "application/octet-stream")
        print(f"Assets response: {resp.status_code}, Content-Type: {content_type}")
        
        excluded_headers = ["content-encoding", "transfer-encoding"]
        response_headers = {}
        
        for key, value in resp.headers.items():
            if key.lower() not in excluded_headers:
                response_headers[key] = value
        
        response_headers["Access-Control-Allow-Origin"] = "*"
        
        content = await resp.aread()
        response_headers["Content-Length"] = str(len(content))
        
        return Response(
            content=content,
            status_code=resp.status_code,
            headers=response_headers,
            media_type=content_type
        )

    except httpx.RequestError as e:
        logger.error(f"Failed to proxy assets request for '{host}' to '{target_url}': {e}")
        raise HTTPException(status_code=502, detail="Could not contact the backend shop service.")
    except Exception as e:
        logger.error(f"Unexpected error proxying assets request for '{host}': {e}")
        raise HTTPException(status_code=500, detail="Internal server error during proxying.")

@app.api_route("/shop/{full_path:path}", include_in_schema=False)
async def custom_domain_shop_proxy(request: Request, full_path: str):
    """
    Handles requests for custom domains by finding the associated bot
    and proxying to the correct shop frontend service.
    """
    host = request.headers.get("host")

    if not host or host in ["v2.noemt.dev", "noemt.dev"]:
        raise HTTPException(
            status_code=404, 
            detail="Endpoint not found."
        )

    bot_name, _ = await find_bot_by_domain(host)
    print(f"Bot found for domain {host}: {bot_name}")

    if not bot_name:
        return Response(
            content=f"Domain '{host}' is not configured for our service.", 
            status_code=404
        )

    target_url = f"http://{SHOP_FRONTEND_HOST}:{SHOP_FRONTEND_PORT}/"
    
    print(f"Original request path: /shop/{full_path}")
    print(f"Target URL: {target_url} (React SPA - all routes serve index.html)")

    try:
        url = httpx.URL(target_url, params=request.query_params)
        headers = dict(request.headers)
        
        headers["host"] = f"{SHOP_FRONTEND_HOST}:{SHOP_FRONTEND_PORT}"
        
        if "accept" not in headers:
            headers["accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
        
        # Build and send the new request
        req = proxy_client.build_request(
            method=request.method,
            url=url,
            headers=headers,
            content=await request.body()
        )
        
        print(f"Proxying {request.method} {target_url}")
        resp = await proxy_client.send(req, stream=True)
        
        # Get content type from response
        content_type = resp.headers.get("content-type", "text/html")
        print(f"Response: {resp.status_code}, Content-Type: {content_type}")
        
        # Handle 304 Not Modified responses - pass through directly with minimal processing
        if resp.status_code == 304:
            # For 304 responses, preserve original headers as much as possible
            response_headers = {}
            excluded_headers = ["content-encoding", "transfer-encoding", "content-length"]
            
            for key, value in resp.headers.items():
                if key.lower() not in excluded_headers:
                    response_headers[key] = value
            
            # Add minimal CORS headers for browser compatibility
            response_headers["Access-Control-Allow-Origin"] = "*"
            
            return Response(
                content=b"",  # Empty bytes for 304
                status_code=304,
                headers=response_headers
            )
        
        # Exclude headers that can cause issues but preserve important ones
        excluded_headers = ["content-encoding", "transfer-encoding"]
        response_headers = {}
        
        for key, value in resp.headers.items():
            if key.lower() not in excluded_headers:
                response_headers[key] = value
        
        # Ensure CORS headers for CSR applications
        response_headers["Access-Control-Allow-Origin"] = "*"
        response_headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response_headers["Access-Control-Allow-Headers"] = "*"
        
        # Handle different content types appropriately
        if "text/html" in content_type:
            # For HTML, read the full content
            content = await resp.aread()
            
            # Debug: Log content length and beginning of content
            print(f"HTML content length: {len(content)} bytes")
            if len(content) > 0:
                preview = content[:200].decode('utf-8', errors='ignore')
                print(f"HTML content preview: {preview}")
            else:
                print("HTML content is empty!")
            
            # Ensure proper charset
            if "charset" not in content_type:
                response_headers["Content-Type"] = "text/html; charset=utf-8"
            
            # Set content length for the full content
            response_headers["Content-Length"] = str(len(content))
            
            return Response(
                content=content,
                status_code=resp.status_code,
                headers=response_headers
            )
        else:
            # For other content types (JS, CSS, images, etc.), read full content too
            content = await resp.aread()
            response_headers["Content-Length"] = str(len(content))
            
            return Response(
                content=content,
                status_code=resp.status_code,
                headers=response_headers,
                media_type=content_type
            )

    except httpx.RequestError as e:
        logger.error(f"Failed to proxy request for '{host}' to '{target_url}': {e}")
        raise HTTPException(status_code=502, detail="Could not contact the backend shop service.")
    except Exception as e:
        logger.error(f"Unexpected error proxying request for '{host}': {e}")
        raise HTTPException(status_code=500, detail="Internal server error during proxying.")

@app.api_route("/{full_path:path}", include_in_schema=False)
async def custom_domain_catch_all(request: Request, full_path: str):
    """
    Catch-all route for custom domains that intelligently routes requests
    """
    host = request.headers.get("host")

    if not host or host in ["v2.noemt.dev", "noemt.dev"]:
        raise HTTPException(status_code=404, detail="Endpoint not found.")

    # Verify this is a valid custom domain
    bot_name, _ = await find_bot_by_domain(host)
    if not bot_name:
        return Response(
            content=f"Domain '{host}' is not configured for our service.", 
            status_code=404
        )

    # Determine the target URL based on the request path
    if full_path.startswith("static/"):
        # Static assets (CSS, JS, etc.)
        target_url = f"http://{SHOP_FRONTEND_HOST}:{SHOP_FRONTEND_PORT}/{full_path}"
    elif full_path.startswith("assets/"):
        # Asset files (images, icons, etc.)
        target_url = f"http://{SHOP_FRONTEND_HOST}:{SHOP_FRONTEND_PORT}/{full_path}"
    elif "." in full_path and full_path.split(".")[-1] in ["css", "js", "map", "ico", "png", "jpg", "jpeg", "gif", "webp", "svg", "woff", "woff2", "ttf", "eot", "json", "xml", "txt", "webmanifest"]:
        # File extensions - serve directly
        target_url = f"http://{SHOP_FRONTEND_HOST}:{SHOP_FRONTEND_PORT}/{full_path}"
    else:
        # Everything else - serve React app
        target_url = f"http://{SHOP_FRONTEND_HOST}:{SHOP_FRONTEND_PORT}/"
    
    print(f"Catch-all request: /{full_path}")
    print(f"Target URL: {target_url}")

    try:
        url = httpx.URL(target_url, params=request.query_params)
        headers = dict(request.headers)
        headers["host"] = f"{SHOP_FRONTEND_HOST}:{SHOP_FRONTEND_PORT}"
        
        req = proxy_client.build_request(
            method=request.method,
            url=url,
            headers=headers,
            content=await request.body()
        )
        
        resp = await proxy_client.send(req, stream=True)
        
        content_type = resp.headers.get("content-type", "application/octet-stream")
        print(f"Catch-all response: {resp.status_code}, Content-Type: {content_type}")
        
        excluded_headers = ["content-encoding", "transfer-encoding"]
        response_headers = {}
        
        for key, value in resp.headers.items():
            if key.lower() not in excluded_headers:
                response_headers[key] = value
        
        response_headers["Access-Control-Allow-Origin"] = "*"
        
        content = await resp.aread()
        response_headers["Content-Length"] = str(len(content))
        
        return Response(
            content=content,
            status_code=resp.status_code,
            headers=response_headers,
            media_type=content_type
        )

    except httpx.RequestError as e:
        logger.error(f"Failed to proxy catch-all request for '{host}' to '{target_url}': {e}")
        raise HTTPException(status_code=502, detail="Could not contact the backend shop service.")
    except Exception as e:
        logger.error(f"Unexpected error proxying catch-all request for '{host}': {e}")
        raise HTTPException(status_code=500, detail="Internal server error during proxying.")
    
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7000)