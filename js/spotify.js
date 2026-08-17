// Spotify OAuth PKCE + Web Playback SDK for in-browser playback.
// Key functions: spotifyLogin(), spotifyPlayTrack(trackId, positionMs), isSpotifyConnected().
import './state.js?v=20260817b';

const SPOTIFY_SCOPES = 'streaming user-modify-playback-state user-read-playback-state user-read-email user-read-private';
const _isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
let _player = null;
let _deviceId = null;
let _playerReady = false;
let _playerInitStarted = false;
let _sdkPlaybackActivated = false;
let _connectDeviceId = null;
let _currentTrackId = null;
let _currentTrackStartMs = null;
let _isPlaying = false;
let _snippetTimer = null;
let _snippetRunId = 0;

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

    // Always derive from the current origin rather than a fixed configured
    // value — this app runs from multiple origins (local dev server(s),
    // GitHub Pages, any custom domain), and a hardcoded redirect URI can
    // only ever be correct for one of them. Each real origin's own
    // callback.html still needs registering in the Spotify dashboard, but
    // which one gets sent now always matches wherever the app is actually
    // running.
    const redirectUri = new URL('callback.html', window.location.href).href;

    const verifier = generateCodeVerifier();
    const challenge = await generateCodeChallenge(verifier);
    return { clientId, redirectUri, verifier, challenge };
}

function spotifyLogin(pendingTrackId, pendingPositionMs) {
    return new Promise(async (resolve) => {
        const clientId = window._spotifyClientId;
        // See _prepareAuth() above — always derive from the current origin.
        const redirectUri = new URL('callback.html', window.location.href).href;

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
    cancelSpotifySnippet(false);
    localStorage.removeItem('spotify_access_token');
    localStorage.removeItem('spotify_refresh_token');
    localStorage.removeItem('spotify_token_expiry');
    _connectDeviceId = null;
    if (_player) {
        _player.disconnect();
        _player = null;
        _deviceId = null;
        _playerReady = false;
        _playerInitStarted = false;
        _sdkPlaybackActivated = false;
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

    // The only signal that audio has actually begun (a Web API 204 merely means
    // the command was accepted), so it is what clears the button's loading ring.
    // It is also the truth for the "playing" ripple: the SDK reports pause,
    // track end, and any externally driven change here, so the animation
    // follows real audio rather than our own optimistic flags.
    _player.addListener('player_state_changed', (state) => {
        const playing = !!state && state.paused === false;
        _setPlayingIndicator(playing);
        if (playing) _endButtonLoading();
    });

    _player.addListener('not_ready', ({ device_id }) => {
        console.log('Spotify player not ready:', device_id);
        _playerReady = false;
        _sdkPlaybackActivated = false;
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
    } else if (event.data && event.data.type === 'spotify-auth-error') {
        // The popup previously just closed/navigated away silently on
        // failure, so the only visible symptom here was the generic
        // "Login failed or cancelled" — this surfaces the actual reason
        // (redirect URI rejected, access denied, token exchange error, etc).
        console.error('[Spotify] Auth failed:', event.data.error);
    }
});

// Try to init player when both prerequisites are met: SDK loaded + client ID available
function _tryInitPlayer() {
    if (_isMobile || !isSpotifyConnected() || !window._spotifyClientId) return;
    initSpotifyPlayer();
}

// The SDK calls this global when it's loaded
window.onSpotifyWebPlaybackSDKReady = () => {
    console.log('Spotify Web Playback SDK loaded');
    window._spotifySdkReady = true;
    // Try init — may no-op if secrets haven't loaded yet (main.js retries after loadSecrets)
    _tryInitPlayer();
};

window._spotifyTryInit = _tryInitPlayer;

// --- Playback ---

function _normalizedSpotifyPosition(positionMs) {
    const value = Number(positionMs);
    return Number.isFinite(value) && value > 0 ? Math.round(value) : 0;
}

function _isCurrentPlaybackRequest(trackId, positionMs) {
    return _currentTrackId === trackId
        && _currentTrackStartMs === _normalizedSpotifyPosition(positionMs);
}

async function spotifyPlayTrack(trackId, positionMs, options = {}) {
  try {
    if (!options.fromSnippet) {
        _snippetRunId++;
        if (_snippetTimer) clearTimeout(_snippetTimer);
        _snippetTimer = null;
    }
    _debugLog('spotifyPlayTrack: ' + trackId + ' @' + positionMs + 'ms (' + (_isMobile ? 'mobile' : 'desktop') + ')');

    // Toggle only when this is the same example, not merely another lyric
    // line from the same song. A different timestamp must issue a fresh play
    // command so Spotify seeks to that example instead of continuing the
    // already-loaded track.
    if (_isCurrentPlaybackRequest(trackId, positionMs) && !options.forceStart) {
        if (_isPlaying) {
            if (_isMobile) {
                const t = await getSpotifyToken();
                const deviceQuery = _connectDeviceId ? `?device_id=${encodeURIComponent(_connectDeviceId)}` : '';
                if (t) await fetch(`https://api.spotify.com/v1/me/player/pause${deviceQuery}`, {
                    method: 'PUT',
                    headers: { 'Authorization': `Bearer ${t}` }
                });
            } else if (_player) {
                _player.pause();
            }
            _setPlaying(false);
            _debugLog('Paused');
        } else {
            if (_isMobile) {
                const t = await getSpotifyToken();
                const deviceQuery = _connectDeviceId ? `?device_id=${encodeURIComponent(_connectDeviceId)}` : '';
                if (t) await fetch(`https://api.spotify.com/v1/me/player/play${deviceQuery}`, {
                    method: 'PUT',
                    headers: { 'Authorization': `Bearer ${t}` }
                });
            } else if (_player) {
                _player.resume();
            }
            _setPlaying(true);
            _debugLog('Resumed');
        }
        return true;
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
        if (!loggedIn) { _debugLog('Login failed or cancelled'); return false; }
        token = await getSpotifyToken();
        if (!token) { _debugLog('Still no token after login'); return false; }
    }

    if (_isMobile) {
        return await _playViaConnect(trackId, positionMs, token);
    } else {
        return await _playViaSdk(trackId, positionMs, token);
    }
  } catch (err) {
    _debugLog('ERROR in spotifyPlayTrack: ' + err.message);
    return false;
  }
}

function _isPhoneConnectDevice(device) {
    const description = `${device?.type || ''} ${device?.name || ''}`.toLowerCase();
    return description.includes('smartphone') || description.includes('iphone')
        || description.includes('android') || description.includes('phone');
}

async function _findMobileConnectDevice(token) {
    const response = await fetch('https://api.spotify.com/v1/me/player/devices', {
        headers: { 'Authorization': `Bearer ${token}` }
    });
    if (response.status === 401) return { unauthorized: true, device: null };
    if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(`Device lookup failed (${response.status}): ${JSON.stringify(detail)}`);
    }

    const payload = await response.json().catch(() => ({ devices: [] }));
    const usable = (payload.devices || []).filter(device => device?.id && !device.is_restricted);
    // This code runs on a phone, so prefer the open phone app even when an
    // unrelated desktop/browser is Spotify's currently active device.
    const device = usable.find(item => _isPhoneConnectDevice(item) && item.is_active)
        || usable.find(item => _isPhoneConnectDevice(item) && item.id === _connectDeviceId)
        || usable.find(item => _isPhoneConnectDevice(item))
        || usable.find(item => item.is_active)
        || usable.find(item => item.id === _connectDeviceId)
        || usable[0]
        || null;
    if (device) _connectDeviceId = device.id;
    return { unauthorized: false, device };
}

async function _activateConnectDevice(device, token) {
    if (!device || device.is_active) return true;
    _debugLog(`Connect: transferring playback to ${device.name || device.type || 'phone'}`);
    const response = await fetch('https://api.spotify.com/v1/me/player', {
        method: 'PUT',
        headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ device_ids: [device.id], play: false })
    });
    if (response.status !== 204 && response.status !== 202) return false;
    // Spotify documents Connect commands as order-sensitive but not
    // guaranteed to execute in order. Give the handoff a brief head start
    // before issuing the seek/play command.
    await new Promise(resolve => setTimeout(resolve, 350));
    return true;
}

async function _playViaConnect(trackId, positionMs, token, retry = {}) {
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
        const lookup = await _findMobileConnectDevice(token);
        if (lookup.unauthorized && !retry.refreshed) {
            const refreshed = await refreshSpotifyToken();
            return refreshed
                ? _playViaConnect(trackId, positionMs, refreshed, { ...retry, refreshed: true })
                : false;
        }
        if (!lookup.device) {
            _debugLog('Connect: Spotify returned no usable devices');
            alert('Spotify is open, but it is not advertising a controllable device yet. Play any song in Spotify once, then return here and try again.');
            return false;
        }
        if (!await _activateConnectDevice(lookup.device, token)) {
            _debugLog('Connect: device transfer was rejected');
        }

        const playUrl = `https://api.spotify.com/v1/me/player/play?device_id=${encodeURIComponent(lookup.device.id)}`;
        const resp = await fetch(playUrl, {
            method: 'PUT', headers, body
        });

        _debugLog('Connect response: ' + resp.status);

        if (resp.status === 204 || resp.status === 202) {
            _debugLog('Connect: playing OK');
            _currentTrackId = trackId;
            _currentTrackStartMs = _normalizedSpotifyPosition(positionMs);
            _setPlaying(true);
            return true;
        }

        if (resp.status === 401 && !retry.refreshed) {
            _debugLog('Connect: 401, refreshing token...');
            const refreshed = await refreshSpotifyToken();
            return refreshed
                ? _playViaConnect(trackId, positionMs, refreshed, { ...retry, refreshed: true })
                : false;
        }

        if (resp.status === 404 && !retry.rediscovered) {
            _debugLog('Connect: device went stale, discovering it again');
            _connectDeviceId = null;
            return _playViaConnect(trackId, positionMs, token, { ...retry, rediscovered: true });
        }

        if (resp.status === 404) {
            alert('Spotify could not activate the phone app. Play any song in Spotify once, then return here and try again.');
            return false;
        }

        if (resp.status === 403) {
            _debugLog('Connect: 403 — Premium required');
            alert('Spotify Premium is required for playback control.');
            return false;
        }

        const err = await resp.json().catch(() => ({}));
        _debugLog('Connect error: ' + resp.status + ' ' + JSON.stringify(err));
        return false;
    } catch (err) {
        _debugLog('Connect request failed: ' + err.message);
        return false;
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
            return false;
        }
        console.log('Player ready, device:', _deviceId);
    }

    try {
        // Transfer only once per SDK device session. Repeating this before
        // every lyric line adds a full Spotify Connect handoff delay.
        if (!_sdkPlaybackActivated) {
            await fetch('https://api.spotify.com/v1/me/player', {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ device_ids: [_deviceId] })
            });
        }

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
            _currentTrackStartMs = _normalizedSpotifyPosition(positionMs);
            _setPlaying(true);
            _sdkPlaybackActivated = true;
            return true;
        }

        if (resp.status === 401) {
            token = await refreshSpotifyToken();
            if (!token) { await spotifyLogin(); return false; }

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
                _currentTrackStartMs = _normalizedSpotifyPosition(positionMs);
                _setPlaying(true);
                _sdkPlaybackActivated = true;
                return true;
            }
        }

        if (resp.status === 403) {
            alert('Spotify Premium is required for playback control.');
            return false;
        }

        const err = await resp.json().catch(() => ({}));
        console.error('Spotify playback error:', resp.status, err);
        return false;
    } catch (err) {
        console.error('Spotify playback request failed:', err);
        return false;
    }
}

async function spotifyPausePlayback(clearTrack = false) {
    if (!_isPlaying) {
        // Nothing to pause, but never leave the playing ripple behind.
        _setPlayingIndicator(false);
        if (clearTrack) {
            _currentTrackId = null;
            _currentTrackStartMs = null;
        }
        return true;
    }
    try {
        if (_isMobile) {
            const token = await getSpotifyToken();
            if (!token) return false;
            const deviceQuery = _connectDeviceId ? `?device_id=${encodeURIComponent(_connectDeviceId)}` : '';
            const response = await fetch(`https://api.spotify.com/v1/me/player/pause${deviceQuery}`, {
                method: 'PUT',
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (response.status !== 204 && response.status !== 202) return false;
        } else if (_player) {
            await _player.pause();
        } else {
            return false;
        }
        _setPlaying(false);
        if (clearTrack) {
            _currentTrackId = null;
            _currentTrackStartMs = null;
        }
        return true;
    } catch (error) {
        _debugLog('Pause failed: ' + error.message);
        return false;
    }
}

function spotifySnippetSupported() {
    // Mobile Connect handoff cannot guarantee a foreground timer will fire at
    // the line boundary, so strict line-only autoplay is desktop-only.
    return !_isMobile;
}

async function cancelSpotifySnippet(pause = true, clearTrack = true) {
    _snippetRunId++;
    if (_snippetTimer) clearTimeout(_snippetTimer);
    _snippetTimer = null;
    if (pause) {
        await spotifyPausePlayback(clearTrack);
    } else if (clearTrack) {
        _currentTrackId = null;
        _currentTrackStartMs = null;
        _setPlaying(false);
    }
}

async function _resumeCurrentSdkTrackAt(positionMs) {
    if (!_player || !_playerReady) return false;
    try {
        await _player.seek(positionMs);
        await _player.resume();
        _currentTrackStartMs = _normalizedSpotifyPosition(positionMs);
        _setPlaying(true);
        _debugLog('SDK: reused current track @' + positionMs + 'ms');
        return true;
    } catch (error) {
        _debugLog('SDK seek/resume failed: ' + error.message);
        return false;
    }
}

async function _waitForSdkSnippetStart(trackId, startMs, runId) {
    if (!_player || !_playerReady) return startMs;
    const deadline = Date.now() + 3000;
    while (Date.now() < deadline && runId === _snippetRunId) {
        try {
            const state = await _player.getCurrentState();
            const activeTrackId = state?.track_window?.current_track?.id || '';
            const position = Number(state?.position);
            if (activeTrackId === trackId && !state.paused && Number.isFinite(position)
                    && position >= startMs - 1000 && position <= startMs + 3000) {
                return position;
            }
        } catch (error) {
            _debugLog('SDK state check failed: ' + error.message);
            break;
        }
        await new Promise(resolve => setTimeout(resolve, 80));
    }
    return runId === _snippetRunId ? startMs : null;
}

async function spotifyPlaySnippet(trackId, startMs, endMs, onEnded) {
    const start = Number(startMs);
    const end = Number(endMs);
    const duration = end - start;
    if (!spotifySnippetSupported() || !trackId || !Number.isFinite(start)
            || !Number.isFinite(end) || duration < 350 || duration > 30000) {
        return false;
    }

    const canReuseCurrentTrack = !_isMobile && _playerReady
        && _currentTrackId === trackId;
    await cancelSpotifySnippet(true, !canReuseCurrentTrack);
    const runId = ++_snippetRunId;
    let started = canReuseCurrentTrack
        ? await _resumeCurrentSdkTrackAt(start)
        : false;
    if (!started) {
        // If local seek/resume lost its SDK state, fall back to the full play
        // command instead of aborting the rest of the autoplay queue.
        _currentTrackId = null;
        started = await spotifyPlayTrack(trackId, start, {
            forceStart: true,
            fromSnippet: true,
        });
    }
    if (!started) return false;
    if (runId !== _snippetRunId) {
        await spotifyPausePlayback(true);
        return false;
    }

    // A Web API 204 means the command was accepted, not that audio has begun.
    // Start the boundary timer from confirmed SDK playback position so a slow
    // song load does not consume the lyric's listening time.
    const confirmedPosition = await _waitForSdkSnippetStart(trackId, start, runId);
    if (confirmedPosition === null || runId !== _snippetRunId) return false;
    const stopAfterMs = Math.max(100, end - confirmedPosition - 120);
    _snippetTimer = setTimeout(async () => {
        if (runId !== _snippetRunId) return;
        _snippetTimer = null;
        // Preserve the track identity: the next queued example may seek within
        // this same song without another transfer/reload.
        await spotifyPausePlayback(false);
        if (runId === _snippetRunId && typeof onEnded === 'function') onEnded();
    }, stopAfterMs);
    return true;
}

// Background tabs can throttle timers; stop immediately on hide rather than
// risk allowing a line-only snippet to continue into the song.
document.addEventListener('visibilitychange', () => {
    if (document.hidden) cancelSpotifySnippet(true);
});
window.addEventListener('pagehide', () => cancelSpotifySnippet(true));

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

// --- Spotify button UI: loading ring + long-press autoplay popover ---
//
// The button markup itself is rendered by flashcards.js / about-example.js.
// Everything interactive about it lives here so the behaviour is identical
// wherever a `.spotify-btn` appears, and so the loading state can be driven by
// the real playback signals this module already owns.

const SPOTIFY_LONG_PRESS_MS = 500;
// Playback can legitimately take a few seconds (token refresh, device
// handoff, track load). This is only a failsafe so the ring can never spin
// forever if a signal never arrives.
const SPOTIFY_LOADING_MAX_MS = 15000;
// Once the play command is accepted the SDK's player_state_changed normally
// lands within a second; this bounds the wait when it doesn't.
const SPOTIFY_LOADING_ACCEPTED_MS = 4000;
const AUTOPLAY_PREF_KEY = 'fluency_global_study_defaults_v1';
const AUTOPLAY_PREF_NAME = 'lyricAutoplay';

let _loadingBtn = null;
let _loadingTimer = null;
// The button the learner last activated — remembered past _endButtonLoading()
// so the playing indicator knows which button owns the audio.
let _activatedBtn = null;
let _pressTimer = null;
let _pressFired = false;
let _autoplayPopover = null;
let _autoplayPopoverAnchor = null;

function _startButtonLoading(btn) {
    if (!btn) return;
    _endButtonLoading();
    _loadingBtn = btn;
    _activatedBtn = btn;
    // The two states are mutually exclusive: a new tap is "starting", not
    // "playing", so any lingering ripple goes now.
    _setPlayingIndicator(false);
    btn.classList.add('spotify-loading');
    _loadingTimer = setTimeout(() => _endButtonLoading(), SPOTIFY_LOADING_MAX_MS);
}

function _endButtonLoading() {
    if (_loadingTimer) clearTimeout(_loadingTimer);
    _loadingTimer = null;
    if (_loadingBtn) _loadingBtn.classList.remove('spotify-loading');
    // Belt and braces: a card re-render can replace the node we were holding.
    document.querySelectorAll('.spotify-btn.spotify-loading')
        .forEach(el => el.classList.remove('spotify-loading'));
    _loadingBtn = null;
}

// --- "Audio is playing right now" indicator ---
// Visually distinct from the loading ring (ripples radiating outward vs one
// sweeping arc) and mutually exclusive with it. Driven only by the real
// playback signals below, never by the tap.

function _playingTargetButton() {
    if (_loadingBtn && _loadingBtn.isConnected) return _loadingBtn;
    if (_activatedBtn && _activatedBtn.isConnected) return _activatedBtn;
    // Autoplay snippets never go through the loading state; when the card shows
    // exactly one Spotify button there is no ambiguity about which one to mark.
    const all = document.querySelectorAll('.spotify-btn');
    return all.length === 1 ? all[0] : null;
}

function _setPlayingIndicator(on) {
    const target = on ? _playingTargetButton() : null;
    // Card re-renders replace button nodes, so clear by query rather than
    // trusting a retained reference.
    document.querySelectorAll('.spotify-btn.spotify-playing')
        .forEach(el => { if (el !== target) el.classList.remove('spotify-playing'); });
    if (target) target.classList.add('spotify-playing');
}

// Single writer for _isPlaying so the animation can never drift from the
// real playback state.
function _setPlaying(value) {
    _isPlaying = value;
    _setPlayingIndicator(value);
}

// Mobile Connect has no state callback, so the accepted play command is the
// best available start signal there. Desktop waits for player_state_changed
// (see initSpotifyPlayer) with this as the upper bound.
function _playCommandAccepted() {
    if (!_loadingBtn) return;
    if (_isMobile) { _endButtonLoading(); return; }
    if (_loadingTimer) clearTimeout(_loadingTimer);
    _loadingTimer = setTimeout(() => _endButtonLoading(), SPOTIFY_LOADING_ACCEPTED_MS);
}

async function _playTrackWithLoadingState(trackId, positionMs, options = {}) {
    // Autoplay snippets drive their own indicator on the autoplay control.
    if (options.fromSnippet) return spotifyPlayTrack(trackId, positionMs, options);
    try {
        const ok = await spotifyPlayTrack(trackId, positionMs, options);
        // A tap on the already-playing track pauses it — nothing is starting,
        // so the ring must not linger.
        if (ok && _isPlaying) _playCommandAccepted();
        else _endButtonLoading();
        return ok;
    } catch (error) {
        _endButtonLoading();
        throw error;
    }
}

// --- Autoplay preference (shares the standard study-defaults store) ---

function _readStudyDefaults() {
    try {
        const saved = JSON.parse(localStorage.getItem(AUTOPLAY_PREF_KEY) || 'null');
        return saved && typeof saved === 'object' ? saved : {};
    } catch (_) {
        return {};
    }
}

function _getAutoplayPref() {
    return _readStudyDefaults()[AUTOPLAY_PREF_NAME] === true;
}

function _setAutoplayPref(value) {
    const saved = _readStudyDefaults();
    saved[AUTOPLAY_PREF_NAME] = !!value;
    try {
        localStorage.setItem(AUTOPLAY_PREF_KEY, JSON.stringify(saved));
    } catch (_) { /* private mode — the session state still applies */ }
}

function _autoplayIsLive() {
    return !!document.querySelector('.spotify-btn.autoplay-active')
        || !!document.querySelector('#exampleAutoplayBtn.is-active');
}

// --- Long-press popover ---

function _closeAutoplayPopover() {
    if (!_autoplayPopover) return;
    _autoplayPopover.remove();
    _autoplayPopover = null;
    _autoplayPopoverAnchor = null;
    document.removeEventListener('click', _dismissAutoplayPopover, true);
    window.removeEventListener('scroll', _closeAutoplayPopover, true);
    window.removeEventListener('resize', _closeAutoplayPopover);
}

function _dismissAutoplayPopover(event) {
    if (_autoplayPopover && _autoplayPopover.contains(event.target)) return;
    // The finger release that *ended* the long press still emits a click on the
    // anchor. Forgive exactly that one, or the popover closes the instant it opens.
    if (_autoplayPopoverAnchor && _autoplayPopoverAnchor.contains(event.target)) {
        _autoplayPopoverAnchor = null;
        return;
    }
    _closeAutoplayPopover();
}

function _renderAutoplayPopoverState() {
    if (!_autoplayPopover) return;
    const on = _getAutoplayPref();
    const toggle = _autoplayPopover.querySelector('.spotify-autoplay-toggle');
    toggle.classList.toggle('is-on', on);
    toggle.setAttribute('aria-pressed', on ? 'true' : 'false');
    toggle.querySelector('.spotify-autoplay-toggle-label').textContent =
        on ? 'Autoplay on' : 'Autoplay off';
}

function _openAutoplayPopover(btn) {
    _closeAutoplayPopover();
    _autoplayPopoverAnchor = btn;
    const popover = document.createElement('div');
    popover.className = 'spotify-autoplay-popover';
    popover.setAttribute('role', 'dialog');
    popover.setAttribute('aria-label', 'Lyric autoplay');
    popover.innerHTML = `
        <span class="spotify-autoplay-popover-text">Autoplay each lyric example on this card in turn.</span>
        <button type="button" class="spotify-autoplay-toggle">
            <span class="spotify-autoplay-toggle-dot" aria-hidden="true"></span>
            <span class="spotify-autoplay-toggle-label"></span>
        </button>`;
    document.body.appendChild(popover);
    _autoplayPopover = popover;
    _renderAutoplayPopoverState();

    // Fixed positioning keeps this independent of whatever the credit strip's
    // containing block happens to be on either card surface.
    const rect = btn.getBoundingClientRect();
    const width = popover.offsetWidth;
    const left = Math.min(
        Math.max(8, rect.left + rect.width / 2 - width / 2),
        Math.max(8, window.innerWidth - width - 8)
    );
    let top = rect.top - popover.offsetHeight - 10;
    if (top < 8) top = Math.min(rect.bottom + 10, window.innerHeight - popover.offsetHeight - 8);
    popover.style.left = `${Math.round(left)}px`;
    popover.style.top = `${Math.round(top)}px`;

    popover.querySelector('.spotify-autoplay-toggle').addEventListener('click', (event) => {
        event.stopPropagation();
        event.preventDefault();
        const next = !_getAutoplayPref();
        _setAutoplayPref(next);
        _renderAutoplayPopoverState();
        // Apply the choice to the card in front of the learner right now; the
        // toggle itself is the user gesture playback needs.
        if (next !== _autoplayIsLive()) window.toggleExampleAutoplay?.(event);
        btn.classList.toggle('autoplay-active', next && _autoplayIsLive());
    });

    // Same dismiss contract as the lookup sheet: anything outside closes it.
    setTimeout(() => {
        document.addEventListener('click', _dismissAutoplayPopover, true);
        window.addEventListener('scroll', _closeAutoplayPopover, true);
        window.addEventListener('resize', _closeAutoplayPopover);
    }, 0);
}

// --- Press handling ---

function _eligibleSpotifyButton(target) {
    const btn = target?.closest?.('.spotify-btn');
    if (!btn || btn.tagName !== 'BUTTON') return null;
    return btn;
}

function _pressStart(event) {
    const btn = _eligibleSpotifyButton(event.target);
    if (!btn) return;
    clearTimeout(_pressTimer);
    _pressFired = false;
    // The About tour's replica card has no live deck behind it, so a
    // long-press there would have nothing to toggle.
    if (btn.closest('.about-example-card-inner')) return;
    _pressTimer = setTimeout(() => {
        _pressFired = true;
        _openAutoplayPopover(btn);
    }, SPOTIFY_LONG_PRESS_MS);
}

function _pressEnd() {
    clearTimeout(_pressTimer);
    _pressTimer = null;
}

document.addEventListener('pointerdown', _pressStart, true);
document.addEventListener('pointerup', _pressEnd, true);
document.addEventListener('pointercancel', _pressEnd, true);
document.addEventListener('pointerleave', _pressEnd, true);
// A long-press on touch otherwise raises the OS callout over our popover.
document.addEventListener('contextmenu', (event) => {
    if (_eligibleSpotifyButton(event.target)) event.preventDefault();
});

// Start the ring on the actual activation, not on press, so holding the button
// for the popover never flashes a loading state.
document.addEventListener('click', (event) => {
    const btn = _eligibleSpotifyButton(event.target);
    if (!btn || _pressFired) return;
    _startButtonLoading(btn);
}, true);

// flashcards.js wires the button's inline handlers to these globals. Its own
// long-press toggled autoplay directly; it is superseded here by the popover,
// so the press hooks become no-ops and activation only has to keep the
// stray post-long-press click from playing the track.
const _flashcardsSpotifyActivate = typeof window.spotifyBtnActivate === 'function'
    ? window.spotifyBtnActivate
    : null;

window.spotifyBtnPressStart = () => {};
window.spotifyBtnPressEnd = () => {};
window.spotifyBtnActivate = function (event, trackId, positionMs) {
    event?.stopPropagation();
    if (event?.cancelable) event.preventDefault();
    _pressEnd();
    if (_pressFired) {
        _pressFired = false;
        _endButtonLoading();
        return;
    }
    // On touch this runs from ontouchend, whose preventDefault suppresses the
    // click the delegated listener above would have seen — so start the ring
    // here too rather than only on desktop.
    _startButtonLoading(_eligibleSpotifyButton(event?.target));
    if (_flashcardsSpotifyActivate) {
        _flashcardsSpotifyActivate(event, trackId, positionMs);
        return;
    }
    _playTrackWithLoadingState(trackId, positionMs);
};

window.spotifyAutoplayPreference = _getAutoplayPref;

// Expose on window for inline onclick handlers
window.spotifyLogin = spotifyLogin;
window.spotifyPlayTrack = _playTrackWithLoadingState;
window.spotifyPlaySnippet = spotifyPlaySnippet;
window.cancelSpotifySnippet = cancelSpotifySnippet;
window.spotifySnippetSupported = spotifySnippetSupported;
window.isSpotifyConnected = isSpotifyConnected;
window.spotifyLogout = spotifyLogout;
