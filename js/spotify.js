// Spotify OAuth PKCE + Web Playback SDK for in-browser playback.
// Key functions: spotifyLogin(), spotifyPlayTrack(trackId, positionMs), isSpotifyConnected().
import './state.js';

const SPOTIFY_SCOPES = 'streaming user-modify-playback-state user-read-playback-state user-read-email user-read-private';
const PLAYBACK_DURATION_MS = 15000;
let _player = null;
let _deviceId = null;
let _playerReady = false;
let _playerInitStarted = false;
let _stopTimer = null;

// --- PKCE helpers ---

function generateCodeVerifier() {
    const array = new Uint8Array(64);
    crypto.getRandomValues(array);
    return btoa(String.fromCharCode(...array))
        .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function generateCodeChallenge(verifier) {
    const data = new TextEncoder().encode(verifier);
    const digest = await crypto.subtle.digest('SHA-256', data);
    return btoa(String.fromCharCode(...new Uint8Array(digest)))
        .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

// --- Auth flow ---

function spotifyLogin() {
    return new Promise(async (resolve) => {
        const clientId = window._spotifyClientId;
        const redirectUri = window._spotifyRedirectUri;
        if (!clientId || !redirectUri) {
            console.error('Spotify client ID or redirect URI not configured in secrets.json');
            resolve(false);
            return;
        }

        const verifier = generateCodeVerifier();
        const challenge = await generateCodeChallenge(verifier);

        // Encode auth state in the Spotify `state` param so the callback can read it
        // (sessionStorage is per-origin, and the callback may be on 127.0.0.1 while app is on localhost)
        const stateObj = JSON.stringify({ verifier, clientId, redirectUri });
        const stateB64 = btoa(stateObj);

        const params = new URLSearchParams({
            response_type: 'code',
            client_id: clientId,
            scope: SPOTIFY_SCOPES,
            redirect_uri: redirectUri,
            code_challenge_method: 'S256',
            code_challenge: challenge,
            state: stateB64
        });

        const authUrl = `https://accounts.spotify.com/authorize?${params}`;
        const popup = window.open(authUrl, 'spotify-auth', 'width=500,height=700,left=200,top=100');

        // Poll for the popup closing (callback.html stores tokens and closes itself)
        const poll = setInterval(() => {
            if (!popup || popup.closed) {
                clearInterval(poll);
                const success = isSpotifyConnected();
                if (success) {
                    console.log('Spotify auth completed via popup');
                    initSpotifyPlayer();
                }
                resolve(success);
            }
        }, 300);
    });
}

async function refreshSpotifyToken() {
    const refreshToken = localStorage.getItem('spotify_refresh_token');
    const clientId = window._spotifyClientId;
    if (!refreshToken || !clientId) {
        spotifyLogout();
        return null;
    }

    try {
        const resp = await fetch('https://accounts.spotify.com/api/token', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({
                grant_type: 'refresh_token',
                refresh_token: refreshToken,
                client_id: clientId
            })
        });

        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error_description || 'Refresh failed');

        localStorage.setItem('spotify_access_token', data.access_token);
        localStorage.setItem('spotify_token_expiry', String(Date.now() + data.expires_in * 1000));
        if (data.refresh_token) {
            localStorage.setItem('spotify_refresh_token', data.refresh_token);
        }
        return data.access_token;
    } catch (err) {
        console.error('Spotify token refresh failed:', err);
        spotifyLogout();
        return null;
    }
}

async function getSpotifyToken() {
    const token = localStorage.getItem('spotify_access_token');
    const expiry = Number(localStorage.getItem('spotify_token_expiry') || 0);

    if (!token) return null;
    if (Date.now() > expiry - 60000) {
        return await refreshSpotifyToken();
    }
    return token;
}

function isSpotifyConnected() {
    return !!localStorage.getItem('spotify_access_token');
}

function spotifyLogout() {
    localStorage.removeItem('spotify_access_token');
    localStorage.removeItem('spotify_refresh_token');
    localStorage.removeItem('spotify_token_expiry');
    if (_player) {
        _player.disconnect();
        _player = null;
        _deviceId = null;
        _playerReady = false;
        _playerInitStarted = false;
    }
}

// --- Web Playback SDK ---

async function initSpotifyPlayer() {
    if (_playerInitStarted) return;
    _playerInitStarted = true;

    const token = await getSpotifyToken();
    if (!token) { _playerInitStarted = false; return; }

    _player = new Spotify.Player({
        name: 'Fluency',
        getOAuthToken: async cb => {
            const t = await getSpotifyToken();
            cb(t);
        },
        volume: 0.5
    });

    _player.addListener('ready', ({ device_id }) => {
        console.log('Spotify player ready, device:', device_id);
        _deviceId = device_id;
        _playerReady = true;
    });

    _player.addListener('not_ready', ({ device_id }) => {
        console.log('Spotify player not ready:', device_id);
        _playerReady = false;
    });

    _player.addListener('initialization_error', ({ message }) => {
        console.error('Spotify init error:', message);
        _playerInitStarted = false;
    });

    _player.addListener('authentication_error', ({ message }) => {
        console.error('Spotify auth error:', message);
        _playerInitStarted = false;
        spotifyLogout();
    });

    _player.addListener('account_error', ({ message }) => {
        console.error('Spotify account error (Premium required?):', message);
        alert('Spotify Premium is required for in-browser playback.');
        _playerInitStarted = false;
    });

    const connected = await _player.connect();
    if (!connected) {
        console.error('Spotify player failed to connect');
        _playerInitStarted = false;
    }
}

// Listen for tokens from the auth popup (handles cross-origin: localhost vs 127.0.0.1)
window.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'spotify-auth' && event.data.tokens) {
        const { access_token, refresh_token, token_expiry } = event.data.tokens;
        localStorage.setItem('spotify_access_token', access_token);
        localStorage.setItem('spotify_refresh_token', refresh_token);
        localStorage.setItem('spotify_token_expiry', token_expiry);
        console.log('Spotify tokens received from auth popup');
    }
});

// The SDK calls this global when it's loaded
window.onSpotifyWebPlaybackSDKReady = () => {
    console.log('Spotify Web Playback SDK loaded');
    // Auto-init if already authenticated
    if (isSpotifyConnected()) {
        initSpotifyPlayer();
    }
};

// --- Playback ---

async function spotifyPlayTrack(trackId, positionMs) {
    console.log('spotifyPlayTrack called:', trackId, positionMs);
    let token = await getSpotifyToken();

    if (!token) {
        console.log('No token, starting login...');
        const loggedIn = await spotifyLogin();
        if (!loggedIn) { console.log('Login failed or cancelled'); return; }
        token = await getSpotifyToken();
        if (!token) { console.log('Still no token after login'); return; }
    }

    console.log('Token available, player ready:', _playerReady, 'device:', _deviceId);

    // Ensure the player is initialized
    if (!_playerReady) {
        console.log('Initializing player...');
        await initSpotifyPlayer();
        // Wait up to 10s for the player to become ready
        for (let i = 0; i < 100 && !_playerReady; i++) {
            await new Promise(r => setTimeout(r, 100));
        }
        if (!_playerReady) {
            console.error('Player failed to become ready after 10s');
            alert('Spotify player is still connecting. Please try again in a moment.');
            return;
        }
        console.log('Player ready, device:', _deviceId);
    }

    try {
        // Transfer playback to the browser device first
        await fetch('https://api.spotify.com/v1/me/player', {
            method: 'PUT',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ device_ids: [_deviceId] })
        });

        const resp = await fetch(`https://api.spotify.com/v1/me/player/play?device_id=${_deviceId}`, {
            method: 'PUT',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                uris: [`spotify:track:${trackId}`],
                position_ms: positionMs || 0
            })
        });

        if (resp.status === 204 || resp.status === 202) {
            console.log(`Spotify: playing track ${trackId} at ${positionMs}ms in browser`);
            // Auto-pause after 15 seconds
            if (_stopTimer) clearTimeout(_stopTimer);
            _stopTimer = setTimeout(() => {
                if (_player) _player.pause();
                console.log('Spotify: auto-paused after 15s');
            }, PLAYBACK_DURATION_MS);
            return;
        }

        if (resp.status === 401) {
            token = await refreshSpotifyToken();
            if (!token) { await spotifyLogin(); return; }

            const retry = await fetch(`https://api.spotify.com/v1/me/player/play?device_id=${_deviceId}`, {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    uris: [`spotify:track:${trackId}`],
                    position_ms: positionMs || 0
                })
            });
            if (retry.status === 204 || retry.status === 202) {
                console.log(`Spotify: playing track ${trackId} at ${positionMs}ms (after refresh)`);
                return;
            }
        }

        if (resp.status === 403) {
            alert('Spotify Premium is required for playback control.');
            return;
        }

        const err = await resp.json().catch(() => ({}));
        console.error('Spotify playback error:', resp.status, err);
    } catch (err) {
        console.error('Spotify playback request failed:', err);
    }
}

// Expose on window for inline onclick handlers
window.spotifyLogin = spotifyLogin;
window.spotifyPlayTrack = spotifyPlayTrack;
window.isSpotifyConnected = isSpotifyConnected;
window.spotifyLogout = spotifyLogout;
