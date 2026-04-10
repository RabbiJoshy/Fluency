// Spotify OAuth PKCE + Web Playback SDK for in-browser playback.
// Key functions: spotifyLogin(), spotifyPlayTrack(trackId, positionMs), isSpotifyConnected().
import './state.js';

const SPOTIFY_SCOPES = 'streaming user-modify-playback-state user-read-playback-state user-read-email user-read-private';
const _isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
let _player = null;
let _deviceId = null;
let _playerReady = false;
let _playerInitStarted = false;
let _currentTrackId = null;
let _isPlaying = false;

// --- Mobile debug logging (Safari Web Inspector console is broken for remote iOS) ---

function _debugLog(msg) {
    console.log('[Spotify]', msg);
}

// --- PKCE helpers ---

function generateCodeVerifier() {
    const array = new Uint8Array(64);
    crypto.getRandomValues(array);
    return btoa(String.fromCharCode(...array))
        .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

// Pure JS SHA-256 fallback for insecure contexts (HTTP on non-localhost)
// where crypto.subtle is unavailable. Spotify requires S256 PKCE.
function _sha256bytes(bytes) {
    const K = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
        0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
        0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
        0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
        0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
        0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
        0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
    ];
    const rr = (x, n) => (x >>> n) | (x << (32 - n));
    const bitLen = bytes.length * 8;
    const padded = new Uint8Array(Math.ceil((bytes.length + 9) / 64) * 64);
    padded.set(bytes);
    padded[bytes.length] = 0x80;
    new DataView(padded.buffer).setUint32(padded.length - 4, bitLen, false);
    let [h0, h1, h2, h3, h4, h5, h6, h7] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
        0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19
    ];
    const dv = new DataView(padded.buffer);
    for (let i = 0; i < padded.length; i += 64) {
        const w = new Array(64);
        for (let j = 0; j < 16; j++) w[j] = dv.getUint32(i + j * 4, false);
        for (let j = 16; j < 64; j++) {
            const s0 = rr(w[j-15], 7) ^ rr(w[j-15], 18) ^ (w[j-15] >>> 3);
            const s1 = rr(w[j-2], 17) ^ rr(w[j-2], 19) ^ (w[j-2] >>> 10);
            w[j] = (w[j-16] + s0 + w[j-7] + s1) | 0;
        }
        let a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, h = h7;
        for (let j = 0; j < 64; j++) {
            const t1 = (h + (rr(e,6) ^ rr(e,11) ^ rr(e,25)) + ((e & f) ^ (~e & g)) + K[j] + w[j]) | 0;
            const t2 = ((rr(a,2) ^ rr(a,13) ^ rr(a,22)) + ((a & b) ^ (a & c) ^ (b & c))) | 0;
            h = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0;
        }
        h0 = (h0+a)|0; h1 = (h1+b)|0; h2 = (h2+c)|0; h3 = (h3+d)|0;
        h4 = (h4+e)|0; h5 = (h5+f)|0; h6 = (h6+g)|0; h7 = (h7+h)|0;
    }
    const out = new Uint8Array(32);
    new DataView(out.buffer).setUint32(0,h0); new DataView(out.buffer).setUint32(4,h1);
    new DataView(out.buffer).setUint32(8,h2); new DataView(out.buffer).setUint32(12,h3);
    new DataView(out.buffer).setUint32(16,h4); new DataView(out.buffer).setUint32(20,h5);
    new DataView(out.buffer).setUint32(24,h6); new DataView(out.buffer).setUint32(28,h7);
    return out;
}

async function generateCodeChallenge(verifier) {
    let digest;
    if (window.crypto && window.crypto.subtle) {
        const data = new TextEncoder().encode(verifier);
        digest = new Uint8Array(await crypto.subtle.digest('SHA-256', data));
    } else {
        _debugLog('No crypto.subtle (HTTP), using JS SHA-256');
        digest = _sha256bytes(new TextEncoder().encode(verifier));
    }
    return btoa(String.fromCharCode(...digest))
        .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

// --- Auth flow ---

// Mobile: prepare PKCE + auth URL synchronously, then redirect the full page.
// We split the async work (code challenge) into a pre-computed step so that
// the actual navigation happens synchronously from the user gesture.
let _pendingAuth = null;

// Pre-compute PKCE challenge so mobile login can navigate synchronously
async function _prepareAuth() {
    const clientId = window._spotifyClientId;
    if (!clientId) {
        _debugLog('ERROR: No spotifyClientId loaded');
        return null;
    }

    const redirectUri = _isMobile
        ? new URL('callback.html', window.location.href).href
        : (window._spotifyRedirectUri || new URL('callback.html', window.location.href).href);

    const verifier = generateCodeVerifier();
    const challenge = await generateCodeChallenge(verifier);
    return { clientId, redirectUri, verifier, challenge };
}

function spotifyLogin(pendingTrackId, pendingPositionMs) {
    return new Promise(async (resolve) => {
        const clientId = window._spotifyClientId;
        const redirectUri = _isMobile
            ? new URL('callback.html', window.location.href).href
            : (window._spotifyRedirectUri || new URL('callback.html', window.location.href).href);

        if (!clientId) {
            _debugLog('ERROR: Spotify client ID not configured in secrets.json');
            resolve(false);
            return;
        }

        _debugLog('Starting login, mobile=' + _isMobile + ', redirect=' + redirectUri);

        if (_isMobile) {
            // --- Mobile: full-page redirect (popups are blocked on iOS Safari) ---

            // Use pre-computed auth if available (from synchronous gesture path),
            // otherwise compute now (may fail on iOS if called after async gap)
            let auth = _pendingAuth;
            _pendingAuth = null;
            if (!auth) {
                auth = await _prepareAuth();
            }
            if (!auth) { resolve(false); return; }

            // Save pending play so we can auto-play after returning from auth
            if (pendingTrackId) {
                sessionStorage.setItem('spotify_pending_play', JSON.stringify({
                    trackId: pendingTrackId,
                    positionMs: pendingPositionMs || 0
                }));
            }

            const stateObj = JSON.stringify({
                verifier: auth.verifier,
                clientId: auth.clientId,
                redirectUri: auth.redirectUri,
                returnUrl: window.location.href
            });
            const stateB64 = btoa(stateObj);

            const params = new URLSearchParams({
                response_type: 'code',
                client_id: auth.clientId,
                scope: SPOTIFY_SCOPES,
                redirect_uri: auth.redirectUri,
                code_challenge_method: 'S256',
                code_challenge: auth.challenge,
                state: stateB64
            });

            _debugLog('Redirecting to Spotify auth...');
            window.location.href = `https://accounts.spotify.com/authorize?${params}`;
            return;
        }

        // --- Desktop: popup flow (existing behavior) ---

        const verifier = generateCodeVerifier();
        const challenge = await generateCodeChallenge(verifier);

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
    // Auto-init if already authenticated (desktop only — SDK not supported on mobile)
    if (!_isMobile && isSpotifyConnected()) {
        initSpotifyPlayer();
    }
};

// --- Playback ---

async function spotifyPlayTrack(trackId, positionMs) {
  try {
    _debugLog('spotifyPlayTrack: ' + trackId + ' @' + positionMs + 'ms (' + (_isMobile ? 'mobile' : 'desktop') + ')');

    // Toggle play/pause if same track
    if (_currentTrackId === trackId) {
        if (_isPlaying) {
            if (_isMobile) {
                const t = await getSpotifyToken();
                if (t) await fetch('https://api.spotify.com/v1/me/player/pause', {
                    method: 'PUT',
                    headers: { 'Authorization': `Bearer ${t}` }
                });
            } else if (_player) {
                _player.pause();
            }
            _isPlaying = false;
            _debugLog('Paused');
        } else {
            if (_isMobile) {
                const t = await getSpotifyToken();
                if (t) await fetch('https://api.spotify.com/v1/me/player/play', {
                    method: 'PUT',
                    headers: { 'Authorization': `Bearer ${t}` }
                });
            } else if (_player) {
                _player.resume();
            }
            _isPlaying = true;
            _debugLog('Resumed');
        }
        return;
    }

    let token = await getSpotifyToken();

    if (!token) {
        _debugLog('No token, starting login...');
        // On mobile, pre-compute PKCE before any navigation to avoid async gaps
        if (_isMobile) {
            _pendingAuth = await _prepareAuth();
        }
        const loggedIn = await spotifyLogin(trackId, positionMs);
        // On mobile, spotifyLogin navigates away — we won't reach here
        if (!loggedIn) { _debugLog('Login failed or cancelled'); return; }
        token = await getSpotifyToken();
        if (!token) { _debugLog('Still no token after login'); return; }
    }

    if (_isMobile) {
        await _playViaConnect(trackId, positionMs, token);
    } else {
        await _playViaSdk(trackId, positionMs, token);
    }
  } catch (err) {
    _debugLog('ERROR in spotifyPlayTrack: ' + err.message);
  }
}

async function _playViaConnect(trackId, positionMs, token) {
    _debugLog('Connect: playing ' + trackId + ' @' + positionMs + 'ms');
    const body = JSON.stringify({
        uris: [`spotify:track:${trackId}`],
        position_ms: positionMs || 0
    });
    const headers = {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
    };

    try {
        const resp = await fetch('https://api.spotify.com/v1/me/player/play', {
            method: 'PUT', headers, body
        });

        _debugLog('Connect response: ' + resp.status);

        if (resp.status === 204 || resp.status === 202) {
            _debugLog('Connect: playing OK');
            _currentTrackId = trackId;
            _isPlaying = true;
            return;
        }

        if (resp.status === 401) {
            _debugLog('Connect: 401, refreshing token...');
            token = await refreshSpotifyToken();
            if (!token) { await spotifyLogin(trackId, positionMs); return; }
            const retry = await fetch('https://api.spotify.com/v1/me/player/play', {
                method: 'PUT',
                headers: { ...headers, 'Authorization': `Bearer ${token}` },
                body
            });
            if (retry.status === 204 || retry.status === 202) {
                _debugLog('Connect: playing OK (after refresh)');
                _currentTrackId = trackId;
                _isPlaying = true;
                return;
            }
        }

        if (resp.status === 404) {
            _debugLog('Connect: 404 — no active device');
            alert('No active Spotify device found. Open the Spotify app first, then try again.');
            return;
        }

        if (resp.status === 403) {
            _debugLog('Connect: 403 — Premium required');
            alert('Spotify Premium is required for playback control.');
            return;
        }

        const err = await resp.json().catch(() => ({}));
        _debugLog('Connect error: ' + resp.status + ' ' + JSON.stringify(err));
    } catch (err) {
        _debugLog('Connect request failed: ' + err.message);
    }
}

async function _playViaSdk(trackId, positionMs, token) {
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
            console.log(`Spotify SDK: playing track ${trackId} at ${positionMs}ms in browser`);
            _currentTrackId = trackId;
            _isPlaying = true;
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
                console.log(`Spotify SDK: playing track ${trackId} at ${positionMs}ms (after refresh)`);
                _currentTrackId = trackId;
                _isPlaying = true;
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

// --- Auto-play on return from mobile auth redirect ---

(function _checkPendingPlay() {
    const pending = sessionStorage.getItem('spotify_pending_play');
    if (pending && isSpotifyConnected()) {
        sessionStorage.removeItem('spotify_pending_play');
        const { trackId, positionMs } = JSON.parse(pending);
        _debugLog('Resuming pending play: ' + trackId + ' @' + positionMs + 'ms');
        // Small delay to let the page finish loading
        setTimeout(() => spotifyPlayTrack(trackId, positionMs), 800);
    }
})();

// Expose on window for inline onclick handlers
window.spotifyLogin = spotifyLogin;
window.spotifyPlayTrack = spotifyPlayTrack;
window.isSpotifyConnected = isSpotifyConnected;
window.spotifyLogout = spotifyLogout;
